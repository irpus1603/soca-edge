import base64
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/config", tags=["config"])
_bearer = HTTPBearer()


def _require_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    if not config.ENGINE_API_KEY:
        raise HTTPException(status_code=503, detail="ENGINE_API_KEY not configured on this engine")
    if creds.credentials != config.ENGINE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid ENGINE_API_KEY")


class ConfigPayload(BaseModel):
    gcs_bucket: str = ""
    gcs_path_prefix: str = ""
    gcs_key: str = ""       # base64-encoded JSON key file content
    publisher_type: str = "redis"
    pubsub_project_id: str = ""
    pubsub_topic: str = "soca-detections"
    pubsub_key: str = ""    # base64-encoded JSON key file content


@router.post("", dependencies=[Security(_require_auth)])
def apply_config(payload: ConfigPayload):
    creds_dir = config.BASE_DIR / "credentials"
    creds_dir.mkdir(exist_ok=True)

    cfg: dict = {}

    if payload.gcs_key:
        gcs_path = creds_dir / "gcs.json"
        gcs_path.write_bytes(base64.b64decode(payload.gcs_key))
        cfg["gcs_key_path"] = str(gcs_path)
        logger.info("GCS key written to %s", gcs_path)

    if payload.pubsub_key:
        pubsub_path = creds_dir / "pubsub.json"
        pubsub_path.write_bytes(base64.b64decode(payload.pubsub_key))
        cfg["pubsub_key_path"] = str(pubsub_path)
        logger.info("Pub/Sub key written to %s", pubsub_path)

    cfg.update({
        "gcs_bucket":       payload.gcs_bucket,
        "gcs_path_prefix":  payload.gcs_path_prefix,
        "publisher_type":   payload.publisher_type,
        "pubsub_project_id": payload.pubsub_project_id,
        "pubsub_topic":     payload.pubsub_topic,
    })

    config_json = config.BASE_DIR / "config.json"
    existing: dict = {}
    if config_json.exists():
        try:
            existing = json.loads(config_json.read_text())
        except Exception:
            pass
    # Only overwrite non-empty values so a partial push doesn't clear existing config
    existing.update({k: v for k, v in cfg.items() if v != ""})
    config_json.write_text(json.dumps(existing, indent=2))
    logger.info("config.json updated — restart engine to apply")

    return {"status": "ok"}
