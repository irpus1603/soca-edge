import json
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from models.schemas import JobConfig, JobStartResponse, JobStatusResponse
from models.db import get_session, DBJob, DBEvent
from workers.detection_worker import DetectionWorker
from core import monitor_stream
import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

_workers: dict[str, DetectionWorker] = {}


def _get_db_job(job_id: str) -> DBJob:
    session = get_session()
    try:
        job = session.query(DBJob).filter_by(id=job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        session.expunge(job)
        return job
    finally:
        session.close()


@router.post("/start", response_model=JobStartResponse, status_code=200)
def start_job(cfg: JobConfig):
    if cfg.job_id in _workers and _workers[cfg.job_id].is_alive():
        raise HTTPException(status_code=409, detail=f"Job {cfg.job_id} is already running")

    active = sum(1 for w in _workers.values() if w.is_alive())
    if active >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=503, detail="Max concurrent jobs reached")

    now = datetime.now(timezone.utc)
    session = get_session()
    try:
        session.add(DBJob(id=cfg.job_id, config=cfg.model_dump(), status="started", started_at=now))
        session.commit()
    finally:
        session.close()

    worker = DetectionWorker(cfg)
    _workers[cfg.job_id] = worker
    worker.start()

    return JobStartResponse(job_id=cfg.job_id, status="started", started_at=now)


@router.post("/{job_id}/stop")
def stop_job(job_id: str):
    worker = _workers.get(job_id)
    if not worker or not worker.is_alive():
        raise HTTPException(status_code=404, detail=f"Job {job_id} is not running")
    worker.stop()
    return {"job_id": job_id, "status": "stopped"}


@router.get("/{job_id}/monitor")
def monitor_job(job_id: str):
    worker = _workers.get(job_id)
    if not worker or not worker.is_alive():
        raise HTTPException(status_code=404, detail=f"Job {job_id} is not running")
    if monitor_stream._buffers.get(job_id) is None:
        raise HTTPException(status_code=400, detail=f"Job {job_id} was not started with monitor=true")
    return StreamingResponse(
        monitor_stream.generate_mjpeg(job_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    job = _get_db_job(job_id)
    return JobStatusResponse(
        job_id=job.id, status=job.status, started_at=job.started_at,
        frames_processed=job.frames_processed, events_triggered=job.events_triggered,
        last_frame_at=job.last_frame_at, error_msg=job.error_msg,
    )


@router.get("/{job_id}/crossing-counts")
def crossing_counts(job_id: str, minutes: int = Query(default=60, ge=1, le=1440)):
    """Return time-series of line crossing counts per rule for the last N minutes."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    session = get_session()
    try:
        events = (
            session.query(DBEvent.timestamp, DBEvent.rule_name, DBEvent.crossing_counts)
            .filter(DBEvent.job_id == job_id, DBEvent.timestamp >= since)
            .order_by(DBEvent.timestamp.asc())
            .all()
        )
        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "rule_name": e.rule_name,
                "crossing_counts": e.crossing_counts or {},
            }
            for e in events
        ]
    finally:
        session.close()


@router.get("/{job_id}/plates")
def list_plates(job_id: str):
    """Return all LPR plate detections logged for this job."""
    session = get_session()
    try:
        events = (
            session.query(DBEvent.timestamp, DBEvent.lpr_results)
            .filter(DBEvent.job_id == job_id)
            .order_by(DBEvent.timestamp.desc())
            .all()
        )
        plates = []
        for e in events:
            results = e.lpr_results or []
            if isinstance(results, str):
                try:
                    results = json.loads(results)
                except Exception:
                    results = []
            for r in results:
                plates.append({
                    "timestamp": e.timestamp.isoformat(),
                    "plate_number": r.get("plate_number"),
                    "plate_confidence": r.get("plate_confidence"),
                    "track_id": r.get("track_id"),
                })
        return plates
    finally:
        session.close()


@router.get("/")
def list_jobs():
    session = get_session()
    try:
        jobs = session.query(DBJob).order_by(DBJob.started_at.desc()).limit(50).all()
        return [
            {"job_id": j.id, "status": j.status, "started_at": j.started_at,
             "frames_processed": j.frames_processed, "events_triggered": j.events_triggered,
             "camera_id": (j.config or {}).get("camera_id", ""),
             "camera_name": (j.config or {}).get("camera_name", "")}
            for j in jobs
        ]
    finally:
        session.close()
