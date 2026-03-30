import logging
import threading
import time as _time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import config
from models.schemas import JobConfig, FrameResult
from models.db import get_session, DBJob, DBEvent, DBFrame
from core.rtsp_capture import RTSPCapture, RTSPConnectionError
from core.frame_gate import FrameGate
from core.state_tracker import StateTracker
from core.snapshot_manager import SnapshotManager
from core import yolo_inference, roi_filter, rule_engine, action_dispatcher, monitor_stream

logger = logging.getLogger(__name__)

_LPR_VEHICLE_CLS = {2, 5, 7}   # COCO: car, bus, truck — skip LPR if none present


def _generate_frame_id(camera_id: str, ts: datetime) -> str:
    return f"{camera_id}_{ts.strftime('%Y%m%d_%H%M%S_%f')}"


def _update_job(job_id: str, **kwargs):
    session = get_session()
    try:
        session.query(DBJob).filter_by(id=job_id).update(kwargs)
        session.commit()
    finally:
        session.close()


def _write_frame(result: FrameResult):
    session = get_session()
    try:
        triggered = any(r.triggered for r in result.rule_results)

        session.add(DBFrame(
            frame_id=result.frame_id,
            job_id=result.job_id,
            timestamp=result.timestamp,
            detection_count=len(result.detections),
            in_roi_count=sum(1 for d in result.detections if d.in_roi),
            rule_triggered=triggered,
        ))

        for rr in result.rule_results:
            if not rr.triggered:
                continue
            cls_counts = {}
            for d in result.detections:
                cls_counts[str(d.cls_id)] = cls_counts.get(str(d.cls_id), 0) + 1

            cls_name_counts = _build_cls_name_summary(result.detections)

            session.add(DBEvent(
                job_id=result.job_id,
                frame_id=result.frame_id,
                timestamp=result.timestamp,
                rule_name=rr.rule_name,
                actions_fired=rr.actions_fired,
                detection_count=len(result.detections),
                in_roi_count=sum(1 for d in result.detections if d.in_roi),
                cls_summary=cls_counts,
                cls_name_summary=cls_name_counts,
                aging_snapshot=result.aging,
                snapshot_path=result.snapshot_path,
                alert_category=result.alert_category,
                snapshot_message=result.snapshot_message,
                raw_detections=[
                    {"cls_id": d.cls_id, "cls_name": d.cls_name,
                     "confidence": d.confidence, "bbox": list(d.bbox),
                     "track_id": d.track_id, "in_roi": d.in_roi,
                     "plate_number": d.plate_number, "plate_expiry": d.plate_expiry,
                     "plate_confidence": d.plate_confidence}
                    for d in result.detections
                ],
                crossing_counts=result.crossing_counts,
                crowd_count=result.crowd_count,
                lpr_results=result.lpr_results,
            ))

        session.commit()
    except Exception as e:
        logger.error(f"DB write failed: {e}")
        session.rollback()
    finally:
        session.close()


def _update_dwell(detections, dwell_tracker: dict) -> None:
    """Update dwell_seconds on each Detection based on first-seen time per track_id."""
    now = _time.time()
    for det in detections:
        if det.track_id is None:
            det.dwell_seconds = 0.0
            continue
        key = str(det.track_id)
        if key not in dwell_tracker:
            dwell_tracker[key] = now
        det.dwell_seconds = now - dwell_tracker[key]
    # Evict stale track_ids
    seen = {str(d.track_id) for d in detections if d.track_id is not None}
    for tid in list(dwell_tracker):
        if tid not in seen:
            del dwell_tracker[tid]


def _cron_active(cron_expr: str) -> bool:
    """Return True if current time falls within the cron expression window."""
    from croniter import croniter
    try:
        now = datetime.now()
        c = croniter(cron_expr, now)
        prev = c.get_prev(datetime)
        return (now - prev).total_seconds() < 60
    except Exception:
        return True   # malformed cron → fail open (always active)


def _in_cooldown(rule: dict, rule_last_fired: dict) -> bool:
    """Return True if this rule fired too recently to fire again."""
    last = rule_last_fired.get(rule['name'], 0)
    return (_time.time() - last) < rule.get('cooldown_seconds', 60)


def _filter_processing(rule: dict, detections) -> list:
    """Filter detections by processing mode: in_roi keeps only ROI hits; detected keeps all."""
    if rule.get('processing') == 'detected':
        return list(detections)
    return [d for d in detections if d.in_roi]


def _filter_cls(rule: dict, detections) -> list:
    """Filter detections by cls_operator + cls_ids."""
    ids = rule.get('cls_ids') or []
    op = rule.get('cls_operator', 'in')
    if not ids:
        return list(detections)
    if op == 'in':
        return [d for d in detections if d.cls_id in ids]
    if op == 'not_in':
        return [d for d in detections if d.cls_id not in ids]
    if op == 'eq':
        return [d for d in detections if d.cls_id == ids[0]]
    return list(detections)


def _build_cls_name_summary(detections) -> dict:
    """Count in-ROI detections by cls_name."""
    counts: dict[str, int] = {}
    for d in detections:
        if d.in_roi:
            counts[d.cls_name] = counts.get(d.cls_name, 0) + 1
    return counts


def _passes_duration(rule: dict, detections) -> bool:
    """Return True if dwell duration condition is satisfied."""
    op = rule.get('duration_op', 'immediate')
    if op == 'immediate':
        return True
    if not detections:
        return False
    threshold = rule.get('duration_seconds', 0)
    max_dwell = max((d.dwell_seconds for d in detections), default=0.0)
    return {
        'gte': max_dwell >= threshold,
        'lte': max_dwell <= threshold,
        'eq':  abs(max_dwell - threshold) < 1.0,
    }.get(op, True)


def _evaluate_rules_new_path(rules: list, detections: list, rule_last_fired: dict, rule_last_seen: dict = None,
                             crossing_counts: dict = None, crowd_count: int = 0,
                             rule_last_in_count: dict = None):
    """
    Evaluate rules using new-path logic (cls_operator, processing, dwell, cron, per-rule cooldown).
    Accepts rules as either list[dict] (from tests) or list[Rule] (Pydantic from engine).
    Updates rule_last_fired in-place for rules that fire.
    """
    from models.schemas import RuleResult

    def _get(rule, key, default=None):
        """Get attribute from either dict or Pydantic model."""
        if isinstance(rule, dict):
            return rule.get(key, default)
        return getattr(rule, key, default)

    if rule_last_seen is None:
        rule_last_seen = {}
    if crossing_counts is None:
        crossing_counts = {}
    if rule_last_in_count is None:
        rule_last_in_count = {}

    results = []

    for rule in sorted(rules, key=lambda r: _get(r, 'priority', 100)):
        name = _get(rule, 'name', '')
        category = _get(rule, 'category', '')
        cron = _get(rule, 'cron_schedule', '* * * * *')

        if not _cron_active(cron):
            results.append(RuleResult(rule_name=name, category=category, triggered=False))
            continue

        rule_dict = {'name': name, 'cooldown_seconds': _get(rule, 'cooldown_seconds', 60)}
        if _in_cooldown(rule_dict, rule_last_fired):
            results.append(RuleResult(rule_name=name, category=category, triggered=False))
            continue

        # cls_ids: dict rules use 'cls_ids', Pydantic Rule uses 'cls_ids_filter'
        if isinstance(rule, dict):
            cls_ids = _get(rule, 'cls_ids', [])
        else:
            cls_ids = getattr(rule, 'cls_ids_filter', [])
        cls_operator = _get(rule, 'cls_operator', 'in')
        processing = _get(rule, 'processing', 'in_roi')
        duration_op = _get(rule, 'duration_op', 'immediate')
        duration_seconds = _get(rule, 'duration_seconds', 0)

        mode = _get(rule, 'mode', 'detection')

        # --- People Counting (line crossing) ---
        if mode == 'people_count':
            threshold = _get(rule, 'count_threshold', 0)
            counts = crossing_counts.get(name, {"in": 0, "out": 0})
            in_count = counts.get("in", 0)
            # Compare against delta (crossings since last fire), not cumulative total.
            # This prevents re-firing on old crossings after cooldown expires.
            last_in = rule_last_in_count.get(name, 0)
            new_crossings = in_count - last_in
            # threshold=0 → fire on any new crossing; threshold>0 → fire every N new crossings
            should_fire = new_crossings > 0 and (threshold <= 0 or new_crossings >= threshold)
            if should_fire:
                raw_actions = _get(rule, 'actions', [])
                actions_fired = [a['type'] if isinstance(a, dict) else a.type for a in raw_actions]
                results.append(RuleResult(rule_name=name, category=category, triggered=True, actions_fired=actions_fired))
                rule_last_fired[name] = _time.time()
                rule_last_in_count[name] = in_count  # update baseline so next fire uses delta
            else:
                results.append(RuleResult(rule_name=name, category=category, triggered=False))
            continue

        # --- Crowd Detection (ROI threshold) ---
        if mode == 'crowd':
            threshold = _get(rule, 'count_threshold', 0)
            # threshold=0 → fire whenever anyone is in the ROI; threshold>0 → fire when count >= N
            should_fire = crowd_count > 0 if threshold <= 0 else crowd_count >= threshold
            if should_fire:
                raw_actions = _get(rule, 'actions', [])
                actions_fired = [a['type'] if isinstance(a, dict) else a.type for a in raw_actions]
                results.append(RuleResult(rule_name=name, category=category, triggered=True, actions_fired=actions_fired))
                rule_last_fired[name] = _time.time()
            else:
                results.append(RuleResult(rule_name=name, category=category, triggered=False))
            continue

        trigger = _get(rule, 'trigger', 'present')

        if trigger == 'absent':
            # Absent detection: fire when matching objects are NOT found for duration_seconds
            relevant = _filter_processing({'processing': processing}, detections)
            relevant = _filter_cls({'cls_operator': cls_operator, 'cls_ids': cls_ids}, relevant)
            if relevant:
                # Objects found — reset absence timer, do NOT fire
                rule_last_seen[name] = _time.time()
                results.append(RuleResult(rule_name=name, category=category, triggered=False))
                continue

            # No matching objects — measure absence duration
            last_seen = rule_last_seen.get(name)
            if last_seen is None:
                # First frame: start absence timer, don't fire yet
                rule_last_seen[name] = _time.time()
                results.append(RuleResult(rule_name=name, category=category, triggered=False))
                continue

            absent_secs = _time.time() - last_seen
            threshold = _get(rule, 'duration_seconds', 120)
            if absent_secs < threshold:
                results.append(RuleResult(rule_name=name, category=category, triggered=False))
                continue

            # Absent long enough — fire
            raw_actions = _get(rule, 'actions', [])
            actions_fired = [a['type'] if isinstance(a, dict) else a.type for a in raw_actions]
            results.append(RuleResult(rule_name=name, category=category, triggered=True, actions_fired=actions_fired))
            rule_last_fired[name] = _time.time()
            continue

        # Present detection (default) — existing logic below
        relevant = _filter_processing({'processing': processing}, detections)
        relevant = _filter_cls({'cls_operator': cls_operator, 'cls_ids': cls_ids}, relevant)

        if not relevant or not _passes_duration(
            {'duration_op': duration_op, 'duration_seconds': duration_seconds}, relevant
        ):
            results.append(RuleResult(rule_name=name, category=category, triggered=False))
            continue

        # Rule fires
        raw_actions = _get(rule, 'actions', [])
        actions_fired = [
            a['type'] if isinstance(a, dict) else a.type
            for a in raw_actions
        ]
        results.append(RuleResult(
            rule_name=name, category=category,
            triggered=True, actions_fired=actions_fired,
        ))
        rule_last_fired[name] = _time.time()

    return results


class DetectionWorker:
    def __init__(self, cfg: JobConfig):
        self.cfg = cfg
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"worker-{cfg.job_id}")
        self._db_executor = ThreadPoolExecutor(max_workers=1)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=5)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self):
        cfg = self.cfg
        _update_job(cfg.job_id, status="running")

        gate         = FrameGate(cfg.frame_interval_ms)
        tracker      = StateTracker(cfg.aging)
        snapshot_mgr = SnapshotManager(cfg.output.snapshot_dir, cfg.aging.cooldown_seconds)

        if cfg.monitor:
            monitor_stream.get_or_create_buffer(cfg.job_id)

        try:
            capture = RTSPCapture(cfg.rtsp_url)
        except RTSPConnectionError as e:
            _update_job(cfg.job_id, status="error", error_msg=str(e), stopped_at=datetime.now(timezone.utc))
            return

        frames_processed = 0
        events_triggered = 0
        dwell_tracker: dict = {}
        rule_last_fired: dict = {}
        rule_last_seen: dict = {}
        rule_last_in_count: dict = {}   # people_count: cumulative in_count at last fire

        # Build per-rule line crossing counters
        from core.line_crossing import LineCrossing
        line_counters: dict = {
            rule.name: LineCrossing(rule.crossing_line, rule.direction)
            for rule in cfg.rules
            if getattr(rule, 'mode', 'detection') == 'people_count'
            and getattr(rule, 'crossing_line', [])
        }

        # --- Dedicated RTSP reader thread ---
        # Decouples network I/O from inference: inference thread always gets the
        # freshest frame without blocking on RTSP latency.
        _latest_frame: list = [None]
        _frame_error:  list = [None]
        _frame_lock  = threading.Lock()
        _reader_stop = threading.Event()

        def _rtsp_reader():
            while not _reader_stop.is_set():
                try:
                    ok, frame = capture.read_frame()
                    if ok and frame is not None:
                        with _frame_lock:
                            _latest_frame[0] = frame
                except Exception as exc:
                    with _frame_lock:
                        _frame_error[0] = exc
                    break

        _reader_thread = threading.Thread(target=_rtsp_reader, daemon=True, name=f"rtsp-{cfg.job_id}")
        _reader_thread.start()

        try:
            while not self._stop_event.is_set():
                with _frame_lock:
                    frame = _latest_frame[0]
                    _latest_frame[0] = None
                    err = _frame_error[0]
                if err:
                    raise err
                if frame is None:
                    _time.sleep(0.005)   # 5 ms back-off — avoids busy-spin between frames
                    continue

                if not gate.should_process(frame):
                    continue

                now = datetime.now(timezone.utc)
                frame_id = _generate_frame_id(cfg.camera_id, now)

                detections = yolo_inference.infer(frame, cfg.model_path, cfg.cls_ids,
                                                  cfg.conf_threshold, cfg.iou_threshold,
                                                  imgsz=cfg.imgsz)
                detections = roi_filter.annotate_in_roi(detections, cfg.roi, frame.shape)
                aging      = tracker.update(detections)

                # --- Line crossing counts (people_count rules) ---
                crossing_counts: dict = {}
                for rule in cfg.rules:
                    if getattr(rule, 'mode', 'detection') == 'people_count':
                        lc = line_counters.get(rule.name)
                        if lc:
                            person_dets = [d for d in detections if d.cls_id == 0]
                            crossing_counts[rule.name] = lc.update(person_dets, frame.shape)

                # --- Crowd count (in-ROI persons) ---
                crowd_count = sum(1 for d in detections if d.in_roi and d.cls_id == 0)

                # --- LPR ---
                lpr_results: list = []
                has_vehicles = any(d.cls_id in _LPR_VEHICLE_CLS for d in detections)
                if cfg.lpr_model_path and has_vehicles:
                    from core.lpr_engine import get_lpr_engine
                    # LPR-v1n.pt is a direct plate detector — run on full frame, no car filter needed
                    lpr_results = get_lpr_engine(cfg.lpr_model_path).process(frame, detections)
                    plate_map = {r["track_id"]: r for r in lpr_results if r.get("track_id") is not None}
                    for d in detections:
                        if d.track_id in plate_map:
                            d.plate_number     = plate_map[d.track_id]["plate_number"]
                            d.plate_expiry     = plate_map[d.track_id].get("plate_expiry", "")
                            d.plate_confidence = plate_map[d.track_id]["plate_confidence"]
                            d.plate_bbox       = tuple(plate_map[d.track_id]["plate_bbox"])

                frame_meta = {"id": frame_id, "timestamp": now.isoformat(),
                              "camera_id": cfg.camera_id, "job_id": cfg.job_id}

                if cfg.rules:
                    # New-rules path — per-rule cron, cls, processing, dwell, cooldown
                    _update_dwell(detections, dwell_tracker)
                    rule_results = _evaluate_rules_new_path(
                        cfg.rules, detections, rule_last_fired, rule_last_seen,
                        crossing_counts=crossing_counts, crowd_count=crowd_count,
                        rule_last_in_count=rule_last_in_count,
                    )
                else:
                    # Legacy path — existing rule evaluation
                    rule_results = rule_engine.evaluate(cfg.rules, detections, aging, frame_meta)

                triggered = [r for r in rule_results if r.triggered]
                if triggered:
                    triggered_cls = list({d.cls_id for d in detections if d.in_roi})
                    if tracker.any_in_cooldown(triggered_cls):
                        # Suppress: cooldown not yet expired — clear triggered flags
                        for r in triggered:
                            r.triggered = False
                        triggered = []
                    else:
                        tracker.mark_triggered(triggered_cls)
                        events_triggered += len(triggered)

                result = FrameResult(
                    frame_id=frame_id, job_id=cfg.job_id, camera_id=cfg.camera_id,
                    camera_name=cfg.camera_name,
                    edge_name=config.EDGE_NAME,
                    timestamp=now, detections=detections, aging=aging, rule_results=rule_results,
                    crossing_counts=crossing_counts,
                    crowd_count=crowd_count,
                    lpr_results=lpr_results,
                )

                dispatched = action_dispatcher.dispatch(result, frame, cfg.rules, snapshot_mgr, cfg.output.stream_name, cfg.roi)

                if cfg.monitor and frame is not None:
                    monitor_stream.push_frame(cfg.job_id, frame, result, cfg.roi, cfg.rules)

                frames_processed += 1
                if dispatched:
                    self._db_executor.submit(_write_frame, result)
                _update_job(cfg.job_id, frames_processed=frames_processed,
                            events_triggered=events_triggered, last_frame_at=now)

        except RTSPConnectionError as e:
            _update_job(cfg.job_id, status="error", error_msg=str(e), stopped_at=datetime.now(timezone.utc))
        except Exception as e:
            logger.exception(f"Worker {cfg.job_id} crashed: {e}")
            _update_job(cfg.job_id, status="error", error_msg=str(e), stopped_at=datetime.now(timezone.utc))
        else:
            _update_job(cfg.job_id, status="stopped", stopped_at=datetime.now(timezone.utc))
        finally:
            _reader_stop.set()
            _reader_thread.join(timeout=3)
            capture.release()
            yolo_inference.unload_model(cfg.model_path)
            if cfg.lpr_model_path:
                from core.lpr_engine import unload_lpr_engine
                unload_lpr_engine(cfg.lpr_model_path)
            self._db_executor.shutdown(wait=False)
            if cfg.monitor:
                monitor_stream.remove_buffer(cfg.job_id)
