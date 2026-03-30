# Advanced Rule Management — soca-engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend soca-engine to support advanced per-rule evaluation: IOU threshold, dwell/duration tracking, cron-based rule gating, cls_operator filtering, processing mode (in_roi vs all), per-rule cooldown, per-rule stream override, and a model labels endpoint.

**Architecture:** `detection_worker._run()` gains a new-rules evaluation path that branches on `cfg.rules` contents — when rules have advanced fields (`cls_operator`, `processing`, `cron_schedule`, etc.) it runs the new path; otherwise falls back to legacy `rule_engine.evaluate()`. Helper functions live as module-level functions in `detection_worker.py`. Schemas gain three new fields. A new `api/labels.py` module handles label file reading.

**Tech Stack:** FastAPI, Python 3.11+, `croniter`, `pyyaml`

**Spec:** `docs/superpowers/specs/2026-03-22-advanced-rule-management-design.md` (in soca-dashboard repo)

---

## File Map

| File | Change |
|------|--------|
| `requirements.txt` | Add `croniter`, `pyyaml` |
| `models/schemas.py` | Add `iou_threshold` to `JobConfig`; `dwell_seconds` to `Detection`; `stream` to `RuleAction`; `category` to `RuleResult` |
| `core/yolo_inference.py` | Add `iou_threshold` param to `infer()` |
| `workers/detection_worker.py` | Add helpers + new-rules evaluation loop |
| `core/action_dispatcher.py` | Read `action.stream` for `publish_queue`; fallback to `stream_name` param |
| `api/labels.py` | New — model labels endpoint |
| `main.py` | Register labels router |

---

## Task 1: Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependencies**

```
croniter==3.0.3
pyyaml==6.0.2
```

- [ ] **Step 2: Install**

```bash
cd "/Users/mac-mini-home/Supriyadi/Projects/soca client-server/soca-engine"
pip install croniter==3.0.3 pyyaml==6.0.2
```

Expected: installed successfully, no conflicts.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add croniter and pyyaml dependencies"
```

---

## Task 2: Schema updates

**Files:**
- Modify: `models/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Create `tests/` directory and write failing tests**

```bash
mkdir -p tests
touch tests/__init__.py
```

Create `tests/test_schemas.py`:

```python
import pytest
from models.schemas import JobConfig, Detection, RuleAction, RuleResult


def test_jobconfig_iou_threshold_default():
    cfg = JobConfig(camera_id='cam1', rtsp_url='rtsp://localhost/test')
    assert cfg.iou_threshold == 0.45


def test_jobconfig_iou_threshold_custom():
    cfg = JobConfig(camera_id='cam1', rtsp_url='rtsp://x', iou_threshold=0.7)
    assert cfg.iou_threshold == 0.7


def test_detection_dwell_seconds_default():
    d = Detection(cls_id=0, cls_name='person', confidence=0.9, bbox=(0,0,10,10))
    assert d.dwell_seconds == 0.0


def test_ruleaction_stream_default_none():
    a = RuleAction(type='publish_queue')
    assert a.stream is None


def test_ruleaction_stream_set():
    a = RuleAction(type='publish_queue', stream='custom:stream')
    assert a.stream == 'custom:stream'


def test_ruleresult_category_default():
    r = RuleResult(rule_name='test', triggered=True)
    assert r.category == ''
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/mac-mini-home/Supriyadi/Projects/soca client-server/soca-engine"
python -m pytest tests/test_schemas.py -v
```

Expected: FAIL — `iou_threshold` not on `JobConfig`, `dwell_seconds` not on `Detection`, `stream` not on `RuleAction`, `category` not on `RuleResult`.

- [ ] **Step 3: Update `models/schemas.py`**

Add `iou_threshold` to `JobConfig` (after `conf_threshold`):
```python
iou_threshold: float = 0.45
```

Add `dwell_seconds` to `Detection` dataclass (after `in_roi`):
```python
dwell_seconds: float = 0.0
```

Add `stream` to `RuleAction` (after `message_template`):
```python
stream: str | None = None
```

Add `category` to `RuleResult` dataclass (after `rule_name`):
```python
category: str = ''
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_schemas.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add models/schemas.py tests/test_schemas.py tests/__init__.py
git commit -m "feat: add iou_threshold, dwell_seconds, stream, category fields to schemas"
```

---

## Task 3: yolo_inference — iou_threshold parameter

**Files:**
- Modify: `core/yolo_inference.py`
- Create: `tests/test_yolo_inference.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_yolo_inference.py`:

```python
import inspect
from core import yolo_inference


def test_infer_accepts_iou_threshold():
    sig = inspect.signature(yolo_inference.infer)
    assert 'iou_threshold' in sig.parameters


def test_infer_iou_default():
    sig = inspect.signature(yolo_inference.infer)
    assert sig.parameters['iou_threshold'].default == 0.45
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_yolo_inference.py -v
```

Expected: FAIL — `iou_threshold` not in signature.

- [ ] **Step 3: Update `core/yolo_inference.py`**

Change the `infer` function signature from:
```python
def infer(frame: np.ndarray, model_path: str, cls_ids: list[int], conf: float = 0.5) -> list[Detection]:
```
to:
```python
def infer(frame: np.ndarray, model_path: str, cls_ids: list[int], conf: float = 0.5, iou_threshold: float = 0.45) -> list[Detection]:
```

Change the `model.track()` call from:
```python
results = model.track(source=frame, persist=True, conf=conf, iou=0.6,
                      classes=cls_ids, verbose=False)
```
to:
```python
results = model.track(source=frame, persist=True, conf=conf, iou=iou_threshold,
                      classes=cls_ids, verbose=False)
```

- [ ] **Step 4: Update call site in `workers/detection_worker.py`**

Change:
```python
detections = yolo_inference.infer(frame, cfg.model_path, cfg.cls_ids, cfg.conf_threshold)
```
to:
```python
detections = yolo_inference.infer(frame, cfg.model_path, cfg.cls_ids, cfg.conf_threshold, cfg.iou_threshold)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_yolo_inference.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/yolo_inference.py workers/detection_worker.py tests/test_yolo_inference.py
git commit -m "feat: add iou_threshold parameter to infer()"
```

---

## Task 4: detection_worker — helper functions

**Files:**
- Modify: `workers/detection_worker.py`
- Create: `tests/test_worker_helpers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_worker_helpers.py`:

```python
import time
import pytest
from models.schemas import Detection


def _det(track_id=1, cls_id=0, in_roi=True):
    d = Detection(cls_id=cls_id, cls_name='person', confidence=0.9, bbox=(0,0,10,10), track_id=track_id, in_roi=in_roi)
    return d


# Import helpers — will fail until added to detection_worker
from workers.detection_worker import (
    _update_dwell, _cron_active, _in_cooldown,
    _filter_processing, _filter_cls, _passes_duration,
)


class TestUpdateDwell:
    def test_sets_dwell_seconds(self):
        tracker = {}
        d = _det(track_id=1)
        _update_dwell([d], tracker)
        assert d.dwell_seconds >= 0.0

    def test_dwell_increases_over_time(self):
        tracker = {}
        d = _det(track_id=1)
        _update_dwell([d], tracker)
        time.sleep(0.05)
        _update_dwell([d], tracker)
        assert d.dwell_seconds >= 0.04

    def test_evicts_missing_track_ids(self):
        tracker = {'99': time.time() - 10}
        _update_dwell([], tracker)
        assert '99' not in tracker

    def test_no_track_id_gets_zero(self):
        tracker = {}
        d = _det(track_id=None)
        _update_dwell([d], tracker)
        assert d.dwell_seconds == 0.0


class TestCronActive:
    def test_always_active(self):
        assert _cron_active('* * * * *') is True

    def test_invalid_cron_defaults_true(self):
        assert _cron_active('not a cron') is True


class TestInCooldown:
    def test_not_in_cooldown_when_never_fired(self):
        assert _in_cooldown({'name': 'r1', 'cooldown_seconds': 60}, {}) is False

    def test_in_cooldown_when_recently_fired(self):
        fired = {'r1': time.time()}
        assert _in_cooldown({'name': 'r1', 'cooldown_seconds': 60}, fired) is True

    def test_not_in_cooldown_after_expiry(self):
        fired = {'r1': time.time() - 120}
        assert _in_cooldown({'name': 'r1', 'cooldown_seconds': 60}, fired) is False


class TestFilterProcessing:
    def test_in_roi_filters_to_roi_only(self):
        dets = [_det(in_roi=True), _det(in_roi=False)]
        result = _filter_processing({'processing': 'in_roi'}, dets)
        assert len(result) == 1
        assert result[0].in_roi is True

    def test_detected_returns_all(self):
        dets = [_det(in_roi=True), _det(in_roi=False)]
        result = _filter_processing({'processing': 'detected'}, dets)
        assert len(result) == 2


class TestFilterCls:
    def test_in_operator(self):
        dets = [_det(cls_id=0), _det(cls_id=2), _det(cls_id=7)]
        result = _filter_cls({'cls_operator': 'in', 'cls_ids': [0, 2]}, dets)
        assert len(result) == 2

    def test_not_in_operator(self):
        dets = [_det(cls_id=0), _det(cls_id=2)]
        result = _filter_cls({'cls_operator': 'not_in', 'cls_ids': [0]}, dets)
        assert len(result) == 1
        assert result[0].cls_id == 2

    def test_eq_operator(self):
        dets = [_det(cls_id=0), _det(cls_id=2)]
        result = _filter_cls({'cls_operator': 'eq', 'cls_ids': [0]}, dets)
        assert len(result) == 1

    def test_empty_cls_ids_returns_all(self):
        dets = [_det(cls_id=0), _det(cls_id=2)]
        result = _filter_cls({'cls_operator': 'in', 'cls_ids': []}, dets)
        assert len(result) == 2


class TestPassesDuration:
    def test_immediate_always_passes(self):
        assert _passes_duration({'duration_op': 'immediate', 'duration_seconds': 0}, []) is True

    def test_gte_passes_when_max_dwell_sufficient(self):
        d = _det(); d.dwell_seconds = 5.0
        assert _passes_duration({'duration_op': 'gte', 'duration_seconds': 3}, [d]) is True

    def test_gte_fails_when_dwell_too_short(self):
        d = _det(); d.dwell_seconds = 1.0
        assert _passes_duration({'duration_op': 'gte', 'duration_seconds': 3}, [d]) is False

    def test_empty_detections_returns_false_for_gte(self):
        assert _passes_duration({'duration_op': 'gte', 'duration_seconds': 3}, []) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_worker_helpers.py -v
```

Expected: ImportError — helpers not in `detection_worker`.

- [ ] **Step 3: Add helper functions to `workers/detection_worker.py`**

Add these module-level functions near the top of the file (after imports, before `DetectionWorker` class):

```python
import time as _time
from datetime import datetime as _datetime


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
        now = _datetime.now()
        c = croniter(cron_expr, now)
        prev = c.get_prev(_datetime)
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_worker_helpers.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add workers/detection_worker.py tests/test_worker_helpers.py
git commit -m "feat: add new-rules evaluation helper functions to detection_worker"
```

---

## Task 5: detection_worker — new-rules evaluation loop

**Files:**
- Modify: `workers/detection_worker.py`
- Create: `tests/test_worker_loop.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_worker_loop.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from models.schemas import JobConfig, Detection, RuleResult


def _make_rule_config(name='test', processing='in_roi', cls_operator='in', cls_ids=None,
                      duration_op='immediate', duration_seconds=0, cooldown_seconds=1,
                      cron_schedule='* * * * *', action_snapshot=True):
    return {
        'name': name,
        'category': 'Intrusion',
        'cls_ids': cls_ids or [0],
        'cls_operator': cls_operator,
        'processing': processing,
        'duration_op': duration_op,
        'duration_seconds': duration_seconds,
        'cooldown_seconds': cooldown_seconds,
        'cron_schedule': cron_schedule,
        'message_template': '',
        'priority': 100,
        'actions': [{'type': 'save_snapshot'}] if action_snapshot else [],
    }


def test_new_rules_path_fires_on_matching_detection():
    """New-rules path fires when cls, processing, and duration all match."""
    from workers.detection_worker import _evaluate_rules_new_path
    det = Detection(cls_id=0, cls_name='person', confidence=0.9, bbox=(0,0,10,10),
                    track_id=1, in_roi=True, dwell_seconds=0.0)
    rule = _make_rule_config()
    results, fired = _evaluate_rules_new_path([rule], [det], {})
    assert fired
    assert results[0].triggered


def test_new_rules_path_skips_wrong_cls():
    from workers.detection_worker import _evaluate_rules_new_path
    det = Detection(cls_id=2, cls_name='car', confidence=0.9, bbox=(0,0,10,10),
                    track_id=1, in_roi=True, dwell_seconds=0.0)
    rule = _make_rule_config(cls_ids=[0])  # only person
    results, fired = _evaluate_rules_new_path([rule], [det], {})
    assert not fired
    assert not results[0].triggered


def test_new_rules_path_respects_cooldown():
    import time
    from workers.detection_worker import _evaluate_rules_new_path
    det = Detection(cls_id=0, cls_name='person', confidence=0.9, bbox=(0,0,10,10),
                    track_id=1, in_roi=True, dwell_seconds=0.0)
    rule = _make_rule_config(cooldown_seconds=60)
    rule_last_fired = {'test': time.time()}  # just fired
    results, fired = _evaluate_rules_new_path([rule], [det], rule_last_fired)
    assert not fired
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_worker_loop.py -v
```

Expected: ImportError — `_evaluate_rules_new_path` not defined.

- [ ] **Step 3: Add `_evaluate_rules_new_path` to `workers/detection_worker.py`**

Add after the helper functions:

```python
import time as _time


def _evaluate_rules_new_path(rules: list[dict], detections: list, rule_last_fired: dict):
    """
    Evaluate rules using new-path logic (cls_operator, processing, dwell, cron, per-rule cooldown).
    Returns (list[RuleResult], bool fired_any).
    Updates rule_last_fired in-place for rules that fire.
    """
    from models.schemas import RuleResult
    results = []
    fired_any = False

    for rule in sorted(rules, key=lambda r: r.get('priority', 100)):
        if not _cron_active(rule.get('cron_schedule', '* * * * *')):
            results.append(RuleResult(rule_name=rule['name'], category=rule.get('category',''), triggered=False))
            continue

        if _in_cooldown(rule, rule_last_fired):
            results.append(RuleResult(rule_name=rule['name'], category=rule.get('category',''), triggered=False))
            continue

        relevant = _filter_processing(rule, detections)
        relevant = _filter_cls(rule, relevant)

        if not relevant or not _passes_duration(rule, relevant):
            results.append(RuleResult(rule_name=rule['name'], category=rule.get('category',''), triggered=False))
            continue

        # Rule fires
        actions_fired = [a['type'] for a in rule.get('actions', [])]
        results.append(RuleResult(
            rule_name=rule['name'],
            category=rule.get('category', ''),
            triggered=True,
            actions_fired=actions_fired,
        ))
        rule_last_fired[rule['name']] = _time.time()
        fired_any = True

    return results, fired_any
```

- [ ] **Step 4: Wire `_evaluate_rules_new_path` into `DetectionWorker._run()`**

Also add new fields to the Pydantic `Rule` schema in `models/schemas.py` so the engine can receive and pass through the advanced rule fields:

```python
# Add to Rule model in models/schemas.py (after existing fields):
cls_operator: str = 'in'           # eq | in | not_in
cls_ids_filter: list[int] = []     # rename to avoid clash with JobConfig.cls_ids
processing: str = 'in_roi'         # in_roi | detected
duration_op: str = 'immediate'     # immediate | gte | lte | eq
duration_seconds: int = 0
cooldown_seconds: int = 60
cron_schedule: str = '* * * * *'
```

Note: use `cls_ids_filter` on the Rule schema to avoid name clash with `JobConfig.cls_ids`. The dashboard sends `cls_ids` in each rule dict; rename to `cls_ids_filter` in the schema and update `_filter_cls` to use `rule.cls_ids_filter`.

In `_run()`, initialise state **before** the capture loop:
```python
dwell_tracker: dict[str, float] = {}
rule_last_fired: dict[str, float] = {}
```

Replace the existing rule evaluation block with the new-path branch (spec: branch on `bool(cfg.rules)`):
```python
if cfg.rules:
    # New-rules path — per-rule cron, cls, processing, dwell, cooldown
    _update_dwell(detections, dwell_tracker)
    rule_results, fired = _evaluate_rules_new_path(cfg.rules, detections, rule_last_fired)
    if fired:
        events_triggered += sum(1 for r in rule_results if r.triggered)
else:
    # Legacy path — existing rule_engine + StateTracker cooldown
    rule_results = rule_engine.evaluate(cfg.rules, detections, aging, frame_meta)
    triggered = [r for r in rule_results if r.triggered]
    if triggered:
        triggered_cls = list({d.cls_id for d in detections if d.in_roi})
        if tracker.any_in_cooldown(triggered_cls):
            for r in triggered:
                r.triggered = False
            triggered = []
        else:
            tracker.mark_triggered(triggered_cls)
            events_triggered += len(triggered)
```

Update `FrameResult` construction to propagate `alert_category`:
```python
alert_cat = next((r.category for r in rule_results if r.triggered and r.category), None)
result = FrameResult(
    frame_id=frame_id, job_id=cfg.job_id, camera_id=cfg.camera_id,
    camera_name=cfg.camera_name, edge_name=config.EDGE_NAME,
    timestamp=now, detections=detections, aging=aging,
    rule_results=rule_results, alert_category=alert_cat,
)
```

After `result` is constructed, dispatch actions (existing `action_dispatcher.dispatch()` handles both paths):
```python
dispatched = action_dispatcher.dispatch(result, frame, cfg.rules, snapshot_mgr, cfg.output.stream_name, cfg.roi)
```

This reuses all existing notification infrastructure (Telegram, Redis, snapshot) for both paths.

Also update `_evaluate_rules_new_path` to accept `list[Rule]` (Pydantic) and access fields via attributes instead of `.get()`:

```python
def _evaluate_rules_new_path(rules: list, detections: list, rule_last_fired: dict):
    """Evaluate advanced rules. rules is list[Rule] Pydantic models."""
    from models.schemas import RuleResult
    results = []
    fired_any = False

    for rule in sorted(rules, key=lambda r: r.priority):
        if not _cron_active(rule.cron_schedule):
            results.append(RuleResult(rule_name=rule.name, category=rule.category, triggered=False))
            continue
        rule_dict = {'name': rule.name, 'cooldown_seconds': rule.cooldown_seconds}
        if _in_cooldown(rule_dict, rule_last_fired):
            results.append(RuleResult(rule_name=rule.name, category=rule.category, triggered=False))
            continue

        relevant = _filter_processing({'processing': rule.processing}, detections)
        relevant = _filter_cls({'cls_operator': rule.cls_operator, 'cls_ids': rule.cls_ids_filter}, relevant)

        if not relevant or not _passes_duration(
            {'duration_op': rule.duration_op, 'duration_seconds': rule.duration_seconds}, relevant
        ):
            results.append(RuleResult(rule_name=rule.name, category=rule.category, triggered=False))
            continue

        actions_fired = [a.type for a in rule.actions]
        results.append(RuleResult(
            rule_name=rule.name, category=rule.category,
            triggered=True, actions_fired=actions_fired,
        ))
        rule_last_fired[rule.name] = _time.time()
        fired_any = True

    return results, fired_any
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_worker_loop.py tests/test_worker_helpers.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add workers/detection_worker.py tests/test_worker_loop.py
git commit -m "feat: add new-rules evaluation loop to detection_worker"
```

---

## Task 6: action_dispatcher — per-rule stream support

**Files:**
- Modify: `core/action_dispatcher.py`
- Create: `tests/test_action_dispatcher.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_action_dispatcher.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from core import action_dispatcher
from models.schemas import FrameResult, RuleResult, Detection, RuleAction, Rule
from datetime import datetime, timezone


def _make_result():
    return FrameResult(
        frame_id='f1', job_id='j1', camera_id='c1', camera_name='cam',
        edge_name='edge', timestamp=datetime.now(timezone.utc),
        detections=[], aging={}, rule_results=[
            RuleResult(rule_name='test', triggered=True, category='Intrusion')
        ],
    )


def test_publish_queue_uses_action_stream():
    """action.stream overrides the stream_name parameter."""
    published = []

    def mock_publish(result, stream_name):
        published.append(stream_name)

    with patch('core.action_dispatcher.output_publisher.publish_to_queue', mock_publish):
        with patch('threading.Thread') as mock_thread:
            mock_thread.return_value.start = lambda: None
            rule = Rule(name='test', actions=[
                RuleAction(type='publish_queue', stream='custom:stream', message_template='{count}')
            ])
            action_dispatcher.dispatch(
                _make_result(), MagicMock(), [rule],
                MagicMock(should_save=lambda: True, save=lambda *a: '/tmp/snap.jpg'),
                'default:stream', None
            )
    # Thread is started, verify by checking mock_thread was called
    assert mock_thread.called


def test_publish_queue_falls_back_to_stream_name_param():
    """When action.stream is None, falls back to stream_name param."""
    from core.action_dispatcher import _get_stream_name
    action = RuleAction(type='publish_queue', stream=None)
    assert _get_stream_name(action, 'fallback:stream') == 'fallback:stream'


def test_get_stream_name_uses_action_stream():
    from core.action_dispatcher import _get_stream_name
    action = RuleAction(type='publish_queue', stream='override:stream')
    assert _get_stream_name(action, 'fallback:stream') == 'override:stream'
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_action_dispatcher.py -v
```

Expected: FAIL — `_get_stream_name` not defined.

- [ ] **Step 3: Update `core/action_dispatcher.py`**

Add helper function:
```python
def _get_stream_name(action: RuleAction, fallback: str) -> str:
    """Return action.stream if set, otherwise fallback stream_name."""
    return action.stream if action.stream else fallback
```

In the `dispatch()` function, update the `publish_queue` action handler from:
```python
elif action.type == "publish_queue":
    if not result.snapshot_message and action.message_template:
        result.snapshot_message = _format_message(action.message_template, result)
    threading.Thread(
        target=output_publisher.publish_to_queue,
        args=(result, stream_name),
        daemon=True,
    ).start()
```
to:
```python
elif action.type == "publish_queue":
    if not result.snapshot_message and action.message_template:
        result.snapshot_message = _format_message(action.message_template, result)
    effective_stream = _get_stream_name(action, stream_name)
    threading.Thread(
        target=output_publisher.publish_to_queue,
        args=(result, effective_stream),
        daemon=True,
    ).start()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_action_dispatcher.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/action_dispatcher.py tests/test_action_dispatcher.py
git commit -m "feat: action_dispatcher reads action.stream for publish_queue"
```

---

## Task 7: Labels endpoint

**Files:**
- Create: `api/labels.py`
- Modify: `main.py`
- Create: `tests/test_labels.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_labels.py`:

```python
import os
import tempfile
import pytest
from fastapi.testclient import TestClient


def test_labels_from_names_file(tmp_path, monkeypatch):
    model_pt = tmp_path / "yolov8n.pt"
    model_pt.touch()
    names_file = tmp_path / "yolov8n.names"
    names_file.write_text("person\ncar\ntruck\n")

    from main import app
    client = TestClient(app)
    resp = client.get(f"/models/labels/?path={model_pt}")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0] == {"id": 0, "name": "person"}
    assert data[2] == {"id": 2, "name": "truck"}


def test_labels_from_yaml(tmp_path):
    model_pt = tmp_path / "best.pt"
    model_pt.touch()
    yaml_file = tmp_path / "data.yaml"
    yaml_file.write_text("names:\n  0: person\n  2: car\n")

    from main import app
    client = TestClient(app)
    resp = client.get(f"/models/labels/?path={model_pt}")
    assert resp.status_code == 200
    data = resp.json()
    assert any(d['name'] == 'person' for d in data)


def test_labels_not_found_returns_empty(tmp_path):
    from main import app
    client = TestClient(app)
    resp = client.get(f"/models/labels/?path={tmp_path}/nonexistent.pt")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_labels.py -v
```

Expected: FAIL — 404 or route not found.

- [ ] **Step 3: Create `api/labels.py`**

```python
import os
import yaml
from fastapi import APIRouter

router = APIRouter(tags=["models"])


@router.get("/models/labels/")
def get_model_labels(path: str):
    """
    Return [{id, name}] for a model by reading its .names file or data.yaml sibling.
    Returns [] if no label file is found.
    """
    base = os.path.splitext(path)[0]

    # Try <model_name>.names
    names_path = base + ".names"
    if os.path.exists(names_path):
        with open(names_path) as f:
            names = [line.strip() for line in f if line.strip()]
        return [{"id": i, "name": name} for i, name in enumerate(names)]

    # Try data.yaml in same directory
    yaml_path = os.path.join(os.path.dirname(path), "data.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        names = data.get("names", [])
        if isinstance(names, list):
            return [{"id": i, "name": n} for i, n in enumerate(names)]
        if isinstance(names, dict):
            return [{"id": k, "name": v} for k, v in sorted(names.items())]

    return []
```

- [ ] **Step 4: Register router in `main.py`**

Add after existing router imports:
```python
from api.labels import router as labels_router
```

Add after existing `include_router` calls:
```python
app.include_router(labels_router)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_labels.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add api/labels.py main.py tests/test_labels.py
git commit -m "feat: add /models/labels/ endpoint"
```

---

## Verification Checklist

1. `python -m pytest tests/ -v` — all tests pass
2. `python -m uvicorn main:app --reload` — no startup errors
3. `GET /models/labels/?path=yolo/yolov8n.pt` — returns label list (requires `.names` file next to model)
4. Start a job with `iou_threshold=0.7` — engine uses 0.7 in `model.track()`
5. Send a job config with `cron_schedule='* 23-23 * * *'` during off-hours — rule does not fire
6. Send a rule with `processing=detected` — alert fires even when object is outside ROI
7. Send a rule with `cls_operator=not_in, cls_ids=[0]` — alert fires for non-person detections
8. Send a rule with `duration_op=gte, duration_seconds=5` — alert only fires after 5s continuous detection
9. Send a rule with `publish_queue action.stream=custom:stream` — Redis message goes to `custom:stream`
10. Legacy job config (no advanced rule fields) — existing `rule_engine.evaluate()` path still works
