import time
import pytest
from models.schemas import Detection


def _det(track_id=1, cls_id=0, in_roi=True):
    d = Detection(cls_id=cls_id, cls_name='person', confidence=0.9, bbox=(0,0,10,10),
                  track_id=track_id, in_roi=in_roi)
    return d


from workers.detection_worker import (
    _update_dwell, _cron_active, _in_cooldown,
    _filter_processing, _filter_cls, _passes_duration,
    _build_cls_name_summary,
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


def _det_named(cls_name, in_roi=True, cls_id=1):
    return Detection(cls_id=cls_id, cls_name=cls_name, confidence=0.9,
                     bbox=(0, 0, 10, 10), in_roi=in_roi)


def test_cls_name_summary_counts_in_roi():
    dets = [
        _det_named('no-vest'), _det_named('no-vest'),
        _det_named('no-gloves'),
        _det_named('no-vest', in_roi=False),  # excluded
    ]
    result = _build_cls_name_summary(dets)
    assert result == {'no-vest': 2, 'no-gloves': 1}


def test_cls_name_summary_empty():
    assert _build_cls_name_summary([]) == {}
