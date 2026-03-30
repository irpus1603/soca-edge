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


from models.schemas import Rule

def test_rule_trigger_default():
    r = Rule(name='test')
    assert r.trigger == 'present'
