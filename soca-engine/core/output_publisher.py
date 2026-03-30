import json
import logging
import os
from datetime import datetime, timezone
from dataclasses import asdict

import redis

from models.schemas import FrameResult
import config

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)
            _redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis unavailable: {e}")
            _redis_client = None
    return _redis_client


def _to_dict(result: FrameResult) -> dict:
    detections = [
        {
            "cls_id": d.cls_id, "cls_name": d.cls_name,
            "confidence": d.confidence, "bbox": list(d.bbox),
            "track_id": d.track_id, "in_roi": d.in_roi,
            "plate_number": d.plate_number, "plate_expiry": d.plate_expiry,
            "plate_confidence": d.plate_confidence,
        }
        for d in result.detections
    ]
    in_roi = [d for d in result.detections if d.in_roi]
    cls_counts = {}
    for d in in_roi:
        cls_counts[str(d.cls_id)] = cls_counts.get(str(d.cls_id), 0) + 1
    cls_name_counts: dict[str, int] = {}
    for d in in_roi:
        cls_name_counts[d.cls_name] = cls_name_counts.get(d.cls_name, 0) + 1

    return {
        "schema_version":   "2.3",
        "edge_name":        result.edge_name,
        "job_id":           result.job_id,
        "frame_id":         result.frame_id,
        "camera_id":        result.camera_id,
        "camera_name":      result.camera_name,
        "timestamp":        result.timestamp.isoformat(),
        "alert_category":   result.alert_category,
        "snapshot_message": result.snapshot_message,
        "detections":       detections,
        "roi_summary": {
            "total_count":      len(result.detections),
            "in_roi_count":     len(in_roi),
            "cls_counts":       cls_counts,
            "cls_name_summary": cls_name_counts,
        },
        "aging":            result.aging,
        "rule_results": [
            {"rule_name": r.rule_name, "triggered": r.triggered, "actions_fired": r.actions_fired}
            for r in result.rule_results
        ],
        "snapshot_path":    result.snapshot_path,
        "crossing_counts":  result.crossing_counts,
        "crowd_count":      result.crowd_count,
        "lpr_results":      result.lpr_results,
    }


def publish_to_queue(result: FrameResult, stream_name: str):
    payload = _to_dict(result)

    if config.PUBLISHER_TYPE == "pubsub":
        if config.PUBSUB_PROJECT_ID and config.PUBSUB_TOPIC:
            topic_path = f"projects/{config.PUBSUB_PROJECT_ID}/topics/{config.PUBSUB_TOPIC}"
            try:
                from core.pubsub_publisher import publish_to_pubsub
                publish_to_pubsub(topic_path, payload)
                return
            except Exception as e:
                logger.warning(f"Pub/Sub publish failed, falling back to DLQ: {e}")
        else:
            logger.warning("PUBLISHER_TYPE=pubsub but PUBSUB_PROJECT_ID or PUBSUB_TOPIC not set; using DLQ")
        _write_dlq(result.job_id, json.dumps(payload))
        return

    # Redis path (default)
    serialised = json.dumps(payload)
    client = get_redis()
    if client:
        try:
            client.xadd(stream_name, {"payload": serialised}, maxlen=config.REDIS_STREAM_MAXLEN, approximate=True)
            return
        except Exception as e:
            logger.warning(f"Redis publish failed, falling back to DLQ: {e}")
    _write_dlq(result.job_id, serialised)


def _write_dlq(job_id: str, payload: str):
    os.makedirs(config.DLQ_DIR, exist_ok=True)
    path = os.path.join(config.DLQ_DIR, f"{job_id}.jsonl")
    with open(path, "a") as f:
        f.write(payload + "\n")
