from unittest.mock import patch

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from app.models import Camera, EdgeConfig, Schedule, Rule


def _make_schedule():
    cam = Camera.objects.create(name='cam1', rtsp_url='rtsp://localhost/test')
    EdgeConfig.objects.create()
    return Schedule.objects.create(name='test', camera=cam, model_path='yolo/yolov8n.pt')


class RuleModelTest(TestCase):
    def test_rule_defaults(self):
        s = _make_schedule()
        r = Rule.objects.create(schedule=s, name='Test Rule')
        self.assertEqual(r.cls_operator, 'in')
        self.assertEqual(r.processing, 'in_roi')
        self.assertEqual(r.duration_op, 'immediate')
        self.assertEqual(r.duration_seconds, 0)
        self.assertEqual(r.cooldown_seconds, 60)
        self.assertEqual(r.cron_schedule, '* * * * *')
        self.assertEqual(r.message_template, '')
        self.assertFalse(r.action_telegram)
        self.assertFalse(r.action_redis)
        self.assertTrue(r.action_snapshot)
        self.assertEqual(r.priority, 100)
        self.assertTrue(r.is_active)

    def test_rule_name_required_at_view_layer(self):
        # Model allows empty name at DB level; view blocks it
        # This is covered in RuleViewTest.test_rule_save_requires_name
        pass

    def test_to_job_config_with_rules(self):
        s = _make_schedule()
        s.iou_threshold = 0.45
        s.save()
        Rule.objects.create(
            schedule=s, name='Person Alert',
            category='Intrusion', cls_ids=[0],
            cls_operator='in', processing='in_roi',
            duration_op='gte', duration_seconds=3,
            cooldown_seconds=60, cron_schedule='* * * * *',
            action_snapshot=True, action_redis=True,
            priority=100, is_active=True,
        )
        cfg = s.to_job_config()
        self.assertEqual(cfg['iou_threshold'], 0.45)
        self.assertEqual(len(cfg['rules']), 1)
        rule = cfg['rules'][0]
        self.assertEqual(rule['name'], 'Person Alert')
        self.assertEqual(rule['cls_ids'], [0])
        self.assertEqual(rule['cls_operator'], 'in')
        self.assertEqual(rule['processing'], 'in_roi')
        self.assertEqual(rule['duration_op'], 'gte')
        self.assertEqual(rule['duration_seconds'], 3)
        self.assertEqual(rule['cooldown_seconds'], 60)
        # Union of cls_ids at job level
        self.assertIn(0, cfg['cls_ids'])

    def test_to_job_config_fallback_no_rules(self):
        s = _make_schedule()
        s.alert_category = 'Intrusion'
        s.min_count = 2
        s.save()
        cfg = s.to_job_config()
        # Legacy single rule
        self.assertEqual(len(cfg['rules']), 1)
        self.assertEqual(cfg['rules'][0]['name'], 'alert')

    def test_inactive_rules_excluded(self):
        s = _make_schedule()
        Rule.objects.create(schedule=s, name='Active', is_active=True)
        Rule.objects.create(schedule=s, name='Inactive', is_active=False)
        cfg = s.to_job_config()
        self.assertEqual(len(cfg['rules']), 1)
        self.assertEqual(cfg['rules'][0]['name'], 'Active')

    def test_redis_stream_from_edge_config(self):
        s = _make_schedule()
        edge = EdgeConfig.objects.first()
        edge.redis_stream = 'custom:stream'
        edge.save()
        Rule.objects.create(schedule=s, name='R', action_redis=True, is_active=True)
        cfg = s.to_job_config()
        publish_action = next((a for a in cfg['rules'][0]['actions'] if a['type'] == 'publish_queue'), None)
        self.assertIsNotNone(publish_action)
        self.assertEqual(publish_action['stream'], 'custom:stream')


class EngineClientTest(TestCase):
    @patch('engine_client.requests.get')
    def test_get_model_labels_success(self, mock_get):
        mock_get.return_value.json.return_value = [
            {"id": 0, "name": "person"}, {"id": 2, "name": "car"}
        ]
        import engine_client
        result = engine_client.get_model_labels('yolo/yolov8n.pt')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'person')

    @patch('engine_client.requests.get', side_effect=Exception('unreachable'))
    def test_get_model_labels_failure_returns_empty(self, _):
        import engine_client
        result = engine_client.get_model_labels('yolo/yolov8n.pt')
        self.assertEqual(result, [])


class RuleViewTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.client = Client()
        User.objects.create_superuser('admin', '', 'pass')
        self.client.login(username='admin', password='pass')
        self.schedule = _make_schedule()

    def test_rule_save_creates_rule(self):
        resp = self.client.post(f'/schedules/{self.schedule.pk}/rules/save/', {
            'rule_name': 'Test Rule',
            'rule_category': 'Intrusion',
            'cls_operator': 'in',
            'processing': 'in_roi',
            'duration_op': 'immediate',
            'duration_seconds': '0',
            'cooldown_seconds': '60',
            'cron_schedule': '* * * * *',
            'action_snapshot': 'on',
            'priority': '100',
            'is_active': 'on',
        })
        self.assertRedirects(resp, f'/schedules/{self.schedule.pk}/edit/')
        self.assertEqual(Rule.objects.filter(schedule=self.schedule).count(), 1)

    def test_rule_save_requires_name(self):
        resp = self.client.post(f'/schedules/{self.schedule.pk}/rules/save/', {
            'rule_name': '',
            'cls_operator': 'in',
        })
        self.assertEqual(Rule.objects.filter(schedule=self.schedule).count(), 0)

    def test_rule_delete(self):
        rule = Rule.objects.create(schedule=self.schedule, name='To Delete')
        resp = self.client.post(f'/schedules/{self.schedule.pk}/rules/{rule.pk}/delete/')
        self.assertRedirects(resp, f'/schedules/{self.schedule.pk}/edit/')
        self.assertFalse(Rule.objects.filter(pk=rule.pk).exists())

    def test_rule_save_updates_existing(self):
        rule = Rule.objects.create(schedule=self.schedule, name='Original')
        self.client.post(f'/schedules/{self.schedule.pk}/rules/save/', {
            'rule_id': str(rule.pk),
            'rule_name': 'Updated',
            'cls_operator': 'in',
            'processing': 'in_roi',
            'duration_op': 'immediate',
            'duration_seconds': '0',
            'cooldown_seconds': '60',
            'cron_schedule': '* * * * *',
            'priority': '100',
            'is_active': 'on',
        })
        rule.refresh_from_db()
        self.assertEqual(rule.name, 'Updated')
