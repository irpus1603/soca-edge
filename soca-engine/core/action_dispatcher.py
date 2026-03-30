import logging
import os
import threading
from datetime import timezone, timedelta

import numpy as np
import httpx

from models.schemas import FrameResult, Rule, RuleAction
from core.snapshot_manager import SnapshotManager
from core import output_publisher
from core.monitor_stream import _draw_roi, _draw_detection, _draw_crossing_lines

logger = logging.getLogger(__name__)

_TZ_GMT7 = timezone(timedelta(hours=7))


def _get_stream_name(action, fallback: str) -> str:
    stream = getattr(action, 'stream', None)
    return stream if stream else fallback


def _format_message(template: str, result: FrameResult) -> str:
    """Fill template placeholders from FrameResult.

    Placeholders: {count} {in_roi_count} {time} {camera_name} {camera_id}
                  {job_id} {category} {crowd_count} {crossing_in} {crossing_out}
                  {plate_number} {plate_expiry} {lpr_count} {violations}
    """
    if not template:
        return ""
    template = template.replace(r'\n', '\n').replace(r'\t', '\t')
    in_roi = sum(1 for d in result.detections if d.in_roi)
    ts_gmt7 = result.timestamp.astimezone(_TZ_GMT7).strftime("%Y-%m-%d %H:%M:%S GMT+7")

    # Aggregate crossing counts across all rules
    total_in = sum(v.get("in", 0) for v in (result.crossing_counts or {}).values())
    total_out = sum(v.get("out", 0) for v in (result.crossing_counts or {}).values())

    # Best plate from lpr_results
    best_plate = ""
    best_expiry = ""
    if result.lpr_results:
        best = max(result.lpr_results, key=lambda r: r.get("plate_confidence", 0))
        best_plate = best.get("plate_number", "")
        best_expiry = best.get("plate_expiry", "")

    # Violations: in_roi detections grouped by cls_name, sorted by count desc
    _cls_counts: dict[str, int] = {}
    for d in result.detections:
        if d.in_roi:
            _cls_counts[d.cls_name] = _cls_counts.get(d.cls_name, 0) + 1
    violations = ', '.join(
        f"{cnt} {name}"
        for name, cnt in sorted(_cls_counts.items(), key=lambda x: (-x[1], x[0]))
    ) or '—'

    try:
        return template.format(
            count=len(result.detections),
            in_roi_count=in_roi,
            time=ts_gmt7,
            camera_name=result.camera_name or result.camera_id,
            camera_id=result.camera_id,
            job_id=result.job_id,
            category=result.alert_category or "",
            crowd_count=result.crowd_count or 0,
            crossing_in=total_in,
            crossing_out=total_out,
            plate_number=best_plate,
            plate_expiry=best_expiry,
            lpr_count=len(result.lpr_results or []),
            violations=violations,
        )
    except (KeyError, IndexError) as e:
        logger.warning(f"Message template error ({e}): {template!r}")
        return template


def _crop_lpr_frame(frame: np.ndarray, lpr_results: list) -> np.ndarray:
    """Crop frame centered on the highest-confidence plate, showing car context."""
    if not lpr_results:
        return frame
    best = max(lpr_results, key=lambda r: r.get("plate_confidence", 0))
    bbox = best.get("plate_bbox")
    if not bbox or len(bbox) < 4:
        return frame
    px1, py1, px2, py2 = bbox
    plate_w = px2 - px1
    plate_h = py2 - py1
    cx = (px1 + px2) // 2
    cy = (py1 + py2) // 2
    # Expand 4× plate width and 6× plate height to capture car context
    hw = max(plate_w * 4, 300)
    hh = max(plate_h * 6, 250)
    h, w = frame.shape[:2]
    x1 = max(0, cx - hw)
    y1 = max(0, cy - hh)
    x2 = min(w, cx + hw)
    y2 = min(h, cy + hh)
    cropped = frame[y1:y2, x1:x2]
    return cropped if cropped.size > 0 else frame


def _annotate_snapshot(frame: np.ndarray, result: FrameResult, roi, rules=None) -> np.ndarray:
    """Annotate frame with ROI, crossing lines, and detection bboxes."""
    out = frame.copy()
    _draw_roi(out, roi)
    _draw_crossing_lines(out, rules, result.crossing_counts or {})
    for det in result.detections:
        _draw_detection(out, det)
    return out


def dispatch(result: FrameResult, frame: np.ndarray, rules: list[Rule],
             snapshot_mgr: SnapshotManager, stream_name: str, roi=None) -> bool:
    """Execute triggered rule actions. Returns True only if any rule fired."""
    triggered_rules = {r.name: r for r in rules
                       if r.name in {rr.rule_name for rr in result.rule_results if rr.triggered}}
    if not triggered_rules:
        return False

    for rule_result in result.rule_results:
        if not rule_result.triggered:
            continue
        rule = triggered_rules.get(rule_result.rule_name)
        if not rule:
            continue

        if rule.category and not result.alert_category:
            result.alert_category = rule.category

        for action in rule.actions:
            if action.type == "save_snapshot":
                # Use LPR-cropped frame when plates are detected, otherwise full annotated frame
                if result.lpr_results:
                    snap_frame = _crop_lpr_frame(frame, result.lpr_results)
                    _draw_crossing_lines(snap_frame, rules, result.crossing_counts or {})
                    for det in result.detections:
                        _draw_detection(snap_frame, det)
                else:
                    snap_frame = _annotate_snapshot(frame, result, roi, rules)
                path = snapshot_mgr.save(snap_frame, result.job_id, result.frame_id)
                if path:
                    result.snapshot_path = path

            elif action.type == "publish_queue":
                if not result.snapshot_message and action.message_template:
                    result.snapshot_message = _format_message(action.message_template, result)
                effective_stream = _get_stream_name(action, stream_name)
                threading.Thread(
                    target=output_publisher.publish_to_queue,
                    args=(result, effective_stream),
                    daemon=True,
                ).start()

            elif action.type == "webhook" and action.url:
                msg = _format_message(action.message_template or "", result)
                if msg:
                    result.snapshot_message = msg
                _fire_webhook(action.url, action.headers or {}, result)

            elif action.type == "telegram" and action.bot_token and action.chat_id:
                msg = _format_message(
                    action.message_template or "{in_roi_count} object(s) detected at {time}",
                    result,
                )
                result.snapshot_message = msg
                _fire_telegram(action.bot_token, action.chat_id, msg, result.snapshot_path)

            elif action.type == "log":
                getattr(logger, action.level, logger.info)(
                    f"Rule triggered | job={result.job_id} rule={rule_result.rule_name} frame={result.frame_id}"
                )

    return True


def _fire_webhook(url: str, headers: dict, result: FrameResult):
    def send():
        try:
            httpx.post(url, json={
                "job_id": result.job_id,
                "frame_id": result.frame_id,
                "timestamp": result.timestamp.isoformat(),
                "alert_category": result.alert_category,
                "snapshot_message": result.snapshot_message,
                "detection_count": len(result.detections),
                "in_roi_count": sum(1 for d in result.detections if d.in_roi),
            }, headers=headers, timeout=5)
        except Exception as e:
            logger.warning(f"Webhook failed {url}: {e}")
    threading.Thread(target=send, daemon=True).start()


def _fire_telegram(bot_token: str, chat_id: str, text: str, snapshot_path: str | None = None):
    def send():
        try:
            base = f"https://api.telegram.org/bot{bot_token}"
            for cid in [c.strip() for c in chat_id.split(",") if c.strip()]:
                if snapshot_path and os.path.exists(snapshot_path):
                    with open(snapshot_path, "rb") as f:
                        httpx.post(f"{base}/sendPhoto",
                                   data={"chat_id": cid, "caption": text, "parse_mode": "Markdown"},
                                   files={"photo": ("snapshot.jpg", f, "image/jpeg")}, timeout=15)
                else:
                    httpx.post(f"{base}/sendMessage",
                               json={"chat_id": cid, "text": text, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")
    threading.Thread(target=send, daemon=True).start()
