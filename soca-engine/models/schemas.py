from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
import uuid
import config


# ---------- Incoming job config ----------

class ROIConfig(BaseModel):
    type: str = "POLYGON"               # POLYGON | RECT
    points: list[list[float]] = []      # [[x,y], ...] normalized 0-1

class AgingConfig(BaseModel):
    window_seconds: int = 60
    cooldown_seconds: int = 60

class RuleCondition(BaseModel):
    path: str
    op: str
    value: Any

class RuleAction(BaseModel):
    type: str                           # save_snapshot | publish_queue | webhook | telegram | log
    url: str | None = None              # webhook only
    headers: dict | None = None
    level: str = "info"                 # log only
    # telegram action fields
    bot_token: str | None = None
    chat_id: str | None = None
    message_template: str | None = None  # e.g. "{count} people detected at {time} [{category}]"
    stream: str | None = None

class Rule(BaseModel):
    name: str
    priority: int = 100
    category: str = ""                  # alert category label (max 255 chars)
    when_all: list[RuleCondition] = []
    when_any: list[RuleCondition] = []
    actions: list[RuleAction] = []
    cls_operator: str = 'in'           # eq | in | not_in
    cls_ids_filter: list[int] = []     # per-rule cls filter (avoid clash with JobConfig.cls_ids)
    processing: str = 'in_roi'         # in_roi | detected
    duration_op: str = 'immediate'     # immediate | gte | lte | eq
    duration_seconds: int = 0
    cooldown_seconds: int = 60
    cron_schedule: str = '* * * * *'
    trigger: str = 'present'           # present | absent
    # --- counting / crowd ---
    mode: str = 'detection'            # detection | people_count | crowd
    direction: str = 'any'            # any | left_to_right | right_to_left | top_to_bottom | bottom_to_top
    count_threshold: int = 0           # min count to trigger (0 = not used)
    crossing_line: list[list[float]] = []  # [[x1,y1],[x2,y2]] normalized, for mode=people_count

class OutputConfig(BaseModel):
    redis_url: str = "redis://localhost:6379"
    stream_name: str = "soca:detections"
    max_snapshot_per_minute: int = 5
    snapshot_dir: str = Field(default_factory=lambda: config.SNAPSHOTS_DIR)

class JobConfig(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str
    camera_name: str = ""
    rtsp_url: str
    model_path: str = "yolo/yolo11n.pt"
    cls_ids: list[int] = [0]
    conf_threshold: float = 0.5
    iou_threshold: float = 0.45
    roi: ROIConfig = Field(default_factory=ROIConfig)
    frame_interval_ms: int = Field(default=1000, ge=33)
    aging: AgingConfig = Field(default_factory=AgingConfig)
    rules: list[Rule] = []
    output: OutputConfig = Field(default_factory=OutputConfig)
    monitor: bool = False
    lpr_model_path: str | None = None   # optional YOLO plate detection model
    imgsz: int | None = None            # per-job inference resolution; None = use INFER_IMGSZ env var


# ---------- Runtime data ----------

@dataclass
class Detection:
    cls_id:     int
    cls_name:   str
    confidence: float
    bbox:       tuple[int, int, int, int]    # x1,y1,x2,y2
    track_id:      int | None = None
    in_roi:        bool = True
    dwell_seconds: float = 0.0
    plate_number:     str | None = None
    plate_expiry:     str | None = None      # "MM/YY" parsed from second row of plate
    plate_confidence: float | None = None
    plate_bbox:       tuple | None = None    # x1,y1,x2,y2 of plate within frame

    @property
    def centroid(self) -> tuple[int, int]:
        return ((self.bbox[0] + self.bbox[2]) // 2, (self.bbox[1] + self.bbox[3]) // 2)


@dataclass
class RuleResult:
    rule_name:     str
    triggered:     bool
    category:      str = ''
    actions_fired: list[str] = field(default_factory=list)


@dataclass
class FrameResult:
    frame_id:         str
    job_id:           str
    camera_id:        str
    camera_name:      str
    edge_name:        str
    timestamp:        datetime
    detections:       list[Detection]
    aging:            dict
    rule_results:     list[RuleResult]
    snapshot_path:    str | None = None
    alert_category:   str | None = None   # from triggered rule's category
    snapshot_message: str | None = None   # formatted message after template substitution
    crossing_counts:  dict = field(default_factory=dict)  # {rule_name: {"in": N, "out": N}}
    crowd_count:      int = 0                              # in-ROI person count this frame
    lpr_results:      list = field(default_factory=list)  # [{track_id, plate_number, plate_confidence}]


# ---------- API responses ----------

class JobStartResponse(BaseModel):
    job_id: str
    status: str
    started_at: datetime

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    started_at: datetime
    frames_processed: int
    events_triggered: int
    last_frame_at: datetime | None
    error_msg: str | None
