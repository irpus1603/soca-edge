import json
from urllib.parse import urlparse, urlunparse, quote
from django.db import models
from django.contrib.auth.models import AbstractUser


class SiteConfig(models.Model):
    company_name = models.CharField(max_length=200, default='My Company')
    app_name     = models.CharField(max_length=200, default='SOCA Dashboard')
    company_logo = models.FileField(upload_to='logos/', blank=True)
    logo_height  = models.PositiveIntegerField(default=40, help_text='Logo height in pixels')

    class Meta:
        verbose_name = 'Site Config'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class User(AbstractUser):
    ROLES = [('admin', 'Admin'), ('operator', 'Operator'), ('viewer', 'Viewer')]
    role = models.CharField(max_length=20, choices=ROLES, default='viewer')


class EdgeConfig(models.Model):
    edge_name = models.CharField(max_length=100, default="edge-1")
    engine_url = models.CharField(max_length=200, default="http://localhost:8001")
    mediamtx_url = models.CharField(max_length=200, default="http://localhost:8888")
    mediamtx_rtsp_url = models.CharField(max_length=200, blank=True, default="rtsp://localhost:8554",
        help_text="MediaMTX RTSP relay base URL used by soca-engine, e.g. rtsp://localhost:8554")
    mediamtx_yml_path = models.CharField(max_length=500, default="../soca-engine/MediaMTX/mediamtx.yml")
    engine_env_path = models.CharField(max_length=500, default="../soca-engine/.env")
    telegram_bot_token = models.CharField(max_length=200, blank=True)
    telegram_chat_id = models.CharField(max_length=100, blank=True)
    # Location & site info (exposed via /api/edge-info/)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    address = models.CharField(max_length=500, blank=True)
    building = models.CharField(max_length=200, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    site_notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    api_key = models.CharField(max_length=64, blank=True, default='')
    engine_db_path = models.CharField(max_length=500, blank=True, default='',
        help_text="Absolute path to soca-engine's SQLite file, e.g. /opt/soca-engine/db.sqlite3")
    snapshots_root = models.CharField(max_length=500, blank=True, default='',
        help_text="Absolute path to snapshots directory, e.g. /opt/soca-engine/snapshots")
    redis_stream = models.CharField(max_length=200, default='soca:detections')
    publisher_type    = models.CharField(
        max_length=10, default='redis',
        choices=[('redis', 'Redis Stream'), ('pubsub', 'Google Pub/Sub')],
        help_text='Transport for publishing detection events'
    )
    pubsub_project_id = models.CharField(max_length=200, blank=True, default='',
        help_text='Google Cloud project ID, e.g. my-gcp-project')
    pubsub_topic      = models.CharField(max_length=200, blank=True, default='soca-detections',
        help_text='Pub/Sub topic name (not full path), e.g. soca-detections')
    gcs_key_path    = models.CharField(max_length=500, blank=True, default='',
        help_text='Path to GCS service account JSON key file')
    gcs_bucket      = models.CharField(max_length=200, blank=True, default='',
        help_text='GCS bucket name, e.g. soca-snapshot-bucket')
    gcs_path_prefix = models.CharField(max_length=200, blank=True, default='',
        help_text='GCS path prefix for this edge, e.g. edge-bekasi')
    pubsub_key_path = models.CharField(max_length=500, blank=True, default='',
        help_text='Path to Pub/Sub service account JSON key file')
    engine_api_key  = models.CharField(max_length=64, blank=True, default='',
        help_text='ENGINE_API_KEY set on soca-engine — required to push config')
    last_engine_push_at = models.DateTimeField(null=True, blank=True)
    last_engine_push_ok = models.BooleanField(null=True, blank=True)

    class Meta:
        verbose_name = "Edge Config"

    def __str__(self):
        return self.edge_name


class Camera(models.Model):
    name = models.CharField(max_length=100, unique=True)
    site_name = models.CharField(max_length=100, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=200, blank=True)
    rtsp_url = models.TextField()
    username = models.CharField(max_length=100, blank=True)
    password = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def full_rtsp_url(self):
        """Return RTSP URL with credentials embedded: rtsp://user:pass@host:port/path"""
        if not self.username:
            return self.rtsp_url
        parsed = urlparse(self.rtsp_url)
        netloc = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))

    def __str__(self):
        return self.name


class Schedule(models.Model):
    name = models.CharField(max_length=100)
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE)
    model_path = models.CharField(max_length=200, default="yolo/yolo11n.pt")
    cls_ids = models.JSONField(default=list)
    conf_threshold = models.FloatField(default=0.5)
    iou_threshold = models.FloatField(default=0.45)
    frame_interval_ms = models.IntegerField(default=1000)
    roi_type = models.CharField(max_length=20, default="POLYGON", choices=[("POLYGON", "Polygon"), ("RECT", "Rectangle"), ("LINE", "Crossing Line")])
    roi_points = models.JSONField(default=list)
    aging_window = models.IntegerField(default=60)
    aging_cooldown = models.IntegerField(default=60)
    min_count = models.IntegerField(default=1)
    save_snapshot = models.BooleanField(default=True)
    publish_redis = models.BooleanField(default=True)
    redis_stream = models.CharField(max_length=100, default="soca:detections")
    alert_category = models.CharField(max_length=255, blank=True)
    snapshot_message = models.TextField(
        blank=True,
        default="{in_roi_count} object(s) detected at {time}",
        help_text="Placeholders: {count}, {in_roi_count}, {time}, {camera_id}, {job_id}, {category}",
    )
    enable_monitor = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    current_job_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    lpr_model_path = models.CharField(max_length=200, blank=True, default="",
        help_text="Optional YOLO plate detection model, e.g. yolo/plate_det.pt")
    crossing_direction = models.CharField(
        max_length=20, default='any',
        choices=[('any','Any'),('left_to_right','Left → Right'),('right_to_left','Right → Left'),
                 ('top_to_bottom','Top → Bottom'),('bottom_to_top','Bottom → Top')],
        help_text="Default crossing direction used by People Counting rules"
    )

    def __str__(self):
        return self.name

    def to_job_config(self):
        edge = EdgeConfig.objects.first()
        stream_name = (edge.redis_stream if edge and edge.redis_stream else getattr(self, 'redis_stream', 'soca:detections'))
        active_rules = list(self.rules.filter(is_active=True).order_by('priority'))

        if active_rules:
            all_cls_ids = list({cid for rule in active_rules for cid in (rule.cls_ids or [])})
            rules_config = []
            for rule in active_rules:
                actions = []
                if rule.action_snapshot:
                    actions.append({"type": "save_snapshot"})
                if rule.action_redis:
                    actions.append({
                        "type": "publish_queue",
                        "stream": stream_name,
                        "message_template": rule.message_template or "{in_roi_count} object(s) detected at {time}",
                    })
                if rule.action_telegram and edge and edge.telegram_bot_token and edge.telegram_chat_id:
                    actions.append({
                        "type": "telegram",
                        "bot_token": edge.telegram_bot_token,
                        "chat_id": edge.telegram_chat_id,
                        "message_template": rule.message_template or "{in_roi_count} object(s) detected at {time}",
                    })
                rules_config.append({
                    "name": rule.name,
                    "category": rule.category,
                    "cls_ids": rule.cls_ids or [],
                    "cls_operator": rule.cls_operator,
                    "processing": rule.processing,
                    "trigger": rule.trigger,
                    "duration_op": rule.duration_op,
                    "duration_seconds": rule.duration_seconds,
                    "cooldown_seconds": rule.cooldown_seconds,
                    "cron_schedule": rule.cron_schedule,
                    "message_template": rule.message_template,
                    "priority": rule.priority,
                    "actions": actions,
                    "mode": rule.mode,
                    # Direction and crossing line come from the schedule's ROI section (single source of truth)
                    "direction": self.crossing_direction,
                    "count_threshold": rule.count_threshold,
                    "crossing_line": self.roi_points if self.roi_type == 'LINE' else [],
                })
            rtsp_url = (
                f"{edge.mediamtx_rtsp_url.rstrip('/')}/{self.camera.name}"
                if edge and edge.mediamtx_rtsp_url
                else self.camera.full_rtsp_url
            )
            return {
                "camera_id": str(self.camera.id),
                "camera_name": self.camera.name,
                "rtsp_url": rtsp_url,
                "model_path": self.model_path,
                "cls_ids": all_cls_ids or [0],
                "conf_threshold": self.conf_threshold,
                "iou_threshold": self.iou_threshold,
                "frame_interval_ms": self.frame_interval_ms,
                "roi": {"type": self.roi_type, "points": self.roi_points},
                "aging": {"window_seconds": self.aging_window, "cooldown_seconds": self.aging_cooldown},
                "rules": rules_config,
                "output": {"stream_name": stream_name},
                "monitor": self.enable_monitor,
                "lpr_model_path": self.lpr_model_path or None,
            }

        # Legacy fallback — no rules defined
        actions = []
        if self.save_snapshot:
            actions.append({"type": "save_snapshot"})
        if self.publish_redis:
            actions.append({
                "type": "publish_queue",
                "message_template": self.snapshot_message or "{in_roi_count} object(s) detected at {time}",
            })
        if edge and edge.telegram_bot_token and edge.telegram_chat_id:
            actions.append({
                "type": "telegram",
                "bot_token": edge.telegram_bot_token,
                "chat_id": edge.telegram_chat_id,
                "message_template": self.snapshot_message or "{in_roi_count} object(s) detected at {time}",
            })
        rules = []
        if actions:
            rules.append({
                "name": self.name,
                "priority": 100,
                "category": self.alert_category or "",
                "when_all": [{"path": "detections.in_roi_count", "op": "gte", "value": self.min_count}],
                "when_any": [],
                "actions": actions,
            })
        rtsp_url = (
            f"{edge.mediamtx_rtsp_url.rstrip('/')}/{self.camera.name}"
            if edge and edge.mediamtx_rtsp_url
            else self.camera.full_rtsp_url
        )
        return {
            "camera_id": str(self.camera.id),
            "camera_name": self.camera.name,
            "rtsp_url": rtsp_url,
            "model_path": self.model_path,
            "cls_ids": self.cls_ids,
            "conf_threshold": self.conf_threshold,
            "iou_threshold": self.iou_threshold,
            "frame_interval_ms": self.frame_interval_ms,
            "roi": {"type": self.roi_type, "points": self.roi_points},
            "aging": {"window_seconds": self.aging_window, "cooldown_seconds": self.aging_cooldown},
            "rules": rules,
            "output": {"stream_name": stream_name},
            "monitor": self.enable_monitor,
            "lpr_model_path": self.lpr_model_path or None,
        }


class Rule(models.Model):
    schedule         = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='rules')
    name             = models.CharField(max_length=100)
    CATEGORIES = [('Intrusion', 'Intrusion'), ('PPE', 'PPE'), ('Detection', 'Detection'),
                  ('Crowd', 'Crowd'), ('Counting', 'Counting'), ('LPR', 'LPR')]
    category         = models.CharField(max_length=100, choices=CATEGORIES, default='Intrusion')
    cls_operator     = models.CharField(max_length=10, default='in')    # eq | in | not_in
    cls_ids          = models.JSONField(default=list)
    processing       = models.CharField(max_length=20, default='in_roi') # in_roi | detected
    trigger          = models.CharField(max_length=10, default='present')  # present | absent
    duration_op      = models.CharField(max_length=15, default='immediate')  # immediate | gte | lte | eq
    duration_seconds = models.IntegerField(default=0)
    cooldown_seconds = models.IntegerField(default=60)
    cron_schedule    = models.CharField(max_length=50, default='* * * * *')
    message_template = models.TextField(blank=True, default='')
    action_telegram  = models.BooleanField(default=False)
    action_redis     = models.BooleanField(default=False)
    action_snapshot  = models.BooleanField(default=True)
    priority         = models.IntegerField(default=100)
    is_active        = models.BooleanField(default=True)
    # --- counting / crowd ---
    MODE_CHOICES = [('detection', 'Detection'), ('people_count', 'People Counting'), ('crowd', 'Crowd Detection')]
    mode             = models.CharField(max_length=20, choices=MODE_CHOICES, default='detection')
    DIRECTION_CHOICES = [
        ('any', 'Any'),
        ('left_to_right', 'Left → Right'),
        ('right_to_left', 'Right → Left'),
        ('top_to_bottom', 'Top → Bottom'),
        ('bottom_to_top', 'Bottom → Top'),
    ]
    direction        = models.CharField(max_length=20, choices=DIRECTION_CHOICES, default='any')
    count_threshold  = models.IntegerField(default=0, help_text="Min count to trigger (0 = not used)")
    crossing_line    = models.JSONField(default=list, help_text="[[x1,y1],[x2,y2]] normalized, for People Counting mode")

    class Meta:
        ordering = ['priority', 'id']

    def __str__(self):
        return f"{self.schedule.name} / {self.name}"
