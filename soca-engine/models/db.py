from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
import config

engine = create_engine(f"sqlite:///{config.DB_PATH}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)
Base = declarative_base()


class DBJob(Base):
    __tablename__ = "detection_jobs"

    id               = Column(String, primary_key=True)
    config           = Column(JSON,    nullable=False)
    status           = Column(String,  nullable=False, default="started")
    started_at       = Column(DateTime, nullable=False, default=datetime.utcnow)
    stopped_at       = Column(DateTime, nullable=True)
    frames_processed = Column(Integer,  nullable=False, default=0)
    events_triggered = Column(Integer,  nullable=False, default=0)
    last_frame_at    = Column(DateTime, nullable=True)
    error_msg        = Column(Text,     nullable=True)


class DBEvent(Base):
    __tablename__ = "detection_events"

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    job_id           = Column(String,   nullable=False, index=True)
    frame_id         = Column(String,   nullable=False)
    timestamp        = Column(DateTime, nullable=False, index=True)
    rule_name        = Column(String,   nullable=False, index=True)
    actions_fired    = Column(JSON,     nullable=False, default=list)
    detection_count  = Column(Integer,  nullable=False, default=0)
    in_roi_count     = Column(Integer,  nullable=False, default=0)
    cls_summary      = Column(JSON,     nullable=False, default=dict)
    cls_name_summary = Column(JSON,     nullable=False, default=dict)
    aging_snapshot   = Column(JSON,     nullable=False, default=dict)
    snapshot_path    = Column(Text,     nullable=True)
    alert_category   = Column(String,   nullable=True)
    snapshot_message = Column(Text,     nullable=True)
    raw_detections   = Column(JSON,     nullable=False, default=list)
    crossing_counts  = Column(JSON,     nullable=False, default=dict)   # {rule_name: {in, out}}
    crowd_count      = Column(Integer,  nullable=False, default=0)
    lpr_results      = Column(JSON,     nullable=False, default=list)   # [{track_id, plate_number, plate_confidence}]


class DBFrame(Base):
    __tablename__ = "frame_index"

    frame_id         = Column(String,   primary_key=True)
    job_id           = Column(String,   nullable=False, index=True)
    timestamp        = Column(DateTime, nullable=False, index=True)
    detection_count  = Column(Integer,  nullable=False, default=0)
    in_roi_count     = Column(Integer,  nullable=False, default=0)
    rule_triggered   = Column(Boolean,  nullable=False, default=False)


def init_db():
    Base.metadata.create_all(engine)
    # Add columns that may not exist in older databases
    with engine.connect() as conn:
        for col, ddl in [
            ("alert_category",   "ALTER TABLE detection_events ADD COLUMN alert_category TEXT"),
            ("snapshot_message", "ALTER TABLE detection_events ADD COLUMN snapshot_message TEXT"),
            ("crossing_counts",  "ALTER TABLE detection_events ADD COLUMN crossing_counts TEXT DEFAULT '{}'"),
            ("crowd_count",      "ALTER TABLE detection_events ADD COLUMN crowd_count INTEGER DEFAULT 0"),
            ("lpr_results",      "ALTER TABLE detection_events ADD COLUMN lpr_results TEXT DEFAULT '[]'"),
            ("cls_name_summary", "ALTER TABLE detection_events ADD COLUMN cls_name_summary TEXT DEFAULT '{}'"),
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(ddl))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_session():
    return Session()
