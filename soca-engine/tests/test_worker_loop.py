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
    results = _evaluate_rules_new_path([rule], [det], {})
    assert results[0].triggered


def test_new_rules_path_skips_wrong_cls():
    from workers.detection_worker import _evaluate_rules_new_path
    det = Detection(cls_id=2, cls_name='car', confidence=0.9, bbox=(0,0,10,10),
                    track_id=1, in_roi=True, dwell_seconds=0.0)
    rule = _make_rule_config(cls_ids=[0])  # only person
    results = _evaluate_rules_new_path([rule], [det], {})
    assert not results[0].triggered


def test_new_rules_path_respects_cooldown():
    import time
    from workers.detection_worker import _evaluate_rules_new_path
    det = Detection(cls_id=0, cls_name='person', confidence=0.9, bbox=(0,0,10,10),
                    track_id=1, in_roi=True, dwell_seconds=0.0)
    rule = _make_rule_config(cooldown_seconds=60)
    rule_last_fired = {'test': time.time()}  # just fired
    results = _evaluate_rules_new_path([rule], [det], rule_last_fired)
    assert not results[0].triggered


def test_absent_rule_does_not_fire_when_objects_present():
    from workers.detection_worker import _evaluate_rules_new_path
    det = Detection(cls_id=0, cls_name='person', confidence=0.9, bbox=(0,0,10,10),
                    track_id=1, in_roi=True, dwell_seconds=0.0)
    rule = _make_rule_config(name='guard', cooldown_seconds=1)
    rule['trigger'] = 'absent'
    rule['duration_seconds'] = 5
    rule_last_seen = {}
    results = _evaluate_rules_new_path([rule], [det], {}, rule_last_seen)
    assert not results[0].triggered
    # last_seen should be reset because objects were found
    assert 'guard' in rule_last_seen


def test_absent_rule_does_not_fire_immediately_on_first_empty_frame():
    from workers.detection_worker import _evaluate_rules_new_path
    rule = _make_rule_config(name='guard', cooldown_seconds=1)
    rule['trigger'] = 'absent'
    rule['duration_seconds'] = 5
    rule_last_seen = {}
    results = _evaluate_rules_new_path([rule], [], {}, rule_last_seen)
    assert not results[0].triggered  # first frame — start timer, don't fire yet


def test_absent_rule_fires_after_duration():
    import time
    from workers.detection_worker import _evaluate_rules_new_path
    rule = _make_rule_config(name='guard', cooldown_seconds=1)
    rule['trigger'] = 'absent'
    rule['duration_seconds'] = 0  # fire immediately after absence starts
    rule_last_seen = {'guard': time.time() - 10}  # absent for 10s
    results = _evaluate_rules_new_path([rule], [], {}, rule_last_seen)
    assert results[0].triggered
