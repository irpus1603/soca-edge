import json
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

CONFIG_JSON = BASE_DIR / "config.json"


def _load_config_json() -> dict:
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text())
        except Exception as exc:
            import sys
            print(f"WARNING: config.json parse error (ignored): {exc}", file=sys.stderr)
            return {}
    return {}


_cfg = _load_config_json()


def _get(key: str, default: str = "") -> str:
    """Read from config.json first, then env vars, then default."""
    val = _cfg.get(key)
    if val is not None:
        return str(val)
    return os.getenv(key, default)


def _path(env_key: str, default: str) -> str:
    """Resolve a path relative to BASE_DIR if not absolute."""
    val = _get(env_key, default)
    p = Path(val)
    return str(p if p.is_absolute() else BASE_DIR / p)


REDIS_URL            = _get("REDIS_URL", "redis://localhost:6379")
REDIS_STREAM_NAME    = _get("REDIS_STREAM_NAME", "soca:detections")
REDIS_STREAM_MAXLEN  = int(_get("REDIS_STREAM_MAXLEN", "10000"))

PUBLISHER_TYPE    = _get("PUBLISHER_TYPE", "redis")
PUBSUB_PROJECT_ID = _get("PUBSUB_PROJECT_ID", "")
PUBSUB_TOPIC      = _get("PUBSUB_TOPIC", "soca-detections")
PUBSUB_KEY_PATH   = _get("PUBSUB_KEY_PATH", "")

GCS_BUCKET      = _get("GCS_BUCKET", "")
GCS_KEY_PATH    = _get("GCS_KEY_PATH", "")

ENGINE_API_KEY = _get("ENGINE_API_KEY", "")

DB_PATH       = _path("DB_PATH", "soca_engine.db")
MODELS_DIR    = _path("MODELS_DIR", "yolo/")
SNAPSHOTS_DIR = _path("SNAPSHOTS_DIR", "snapshots/")
DLQ_DIR       = _path("DLQ_DIR", "dlq/")

EDGE_NAME = _get("EDGE_NAME", "")
if not EDGE_NAME:
    raise RuntimeError(
        "EDGE_NAME env var is required but not set. "
        "Set it to a unique name identifying this edge device."
    )

# Default GCS path prefix to EDGE_NAME so uploads land under the edge's own folder
# automatically, without needing GCS_PATH_PREFIX set explicitly in .env.
GCS_PATH_PREFIX = _get("GCS_PATH_PREFIX", EDGE_NAME)

MAX_CONCURRENT_JOBS = int(_get("MAX_CONCURRENT_JOBS", "4"))
MAX_LOADED_MODELS   = int(_get("MAX_LOADED_MODELS", "3"))

SNAPSHOT_JPEG_QUALITY = int(_get("SNAPSHOT_JPEG_QUALITY", "60"))
SNAPSHOT_MAX_WIDTH    = int(_get("SNAPSHOT_MAX_WIDTH", "1280"))

INFER_DEVICE = _get("INFER_DEVICE", "auto")
INFER_IMGSZ  = int(_get("INFER_IMGSZ", "640"))
INFER_HALF   = _get("INFER_HALF", "false").lower() == "true"

LOG_LEVEL = _get("LOG_LEVEL", "INFO")
