import pytest
from datetime import datetime, timezone
from core.action_dispatcher import _get_stream_name, _format_message
from models.schemas import RuleAction, Detection, FrameResult, RuleResult


def test_get_stream_name_uses_action_stream():
    action = RuleAction(type='publish_queue', stream='override:stream')
    assert _get_stream_name(action, 'fallback:stream') == 'override:stream'


def test_publish_queue_falls_back_to_stream_name_param():
    action = RuleAction(type='publish_queue', stream=None)
    assert _get_stream_name(action, 'fallback:stream') == 'fallback:stream'


# Test fixtures for violations placeholder
def _make_result(detections):
    return FrameResult(
        frame_id='f1', job_id='j1', camera_id='c1',
        camera_name='Cam A', edge_name='edge-1',
        timestamp=datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc),
        detections=detections, aging={}, rule_results=[],
    )


def _det(cls_name, in_roi=True):
    return Detection(cls_id=1, cls_name=cls_name, confidence=0.9,
                     bbox=(0, 0, 10, 10), in_roi=in_roi)


def test_violations_placeholder_formats_cls_names():
    result = _make_result([
        _det('no-vest'), _det('no-vest'), _det('no-vest'),
        _det('no-gloves'), _det('no-gloves'),
    ])
    msg = _format_message('{violations}', result)
    assert '3 no-vest' in msg
    assert '2 no-gloves' in msg


def test_violations_excludes_out_of_roi():
    result = _make_result([
        _det('no-vest', in_roi=True),
        _det('no-vest', in_roi=False),   # should not count
    ])
    msg = _format_message('{violations}', result)
    assert '1 no-vest' in msg
    assert '2' not in msg


def test_violations_empty_when_no_detections():
    result = _make_result([])
    msg = _format_message('{violations}', result)
    assert msg == '—'
