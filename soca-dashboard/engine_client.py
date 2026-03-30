import requests
from django.conf import settings


def _base():
    from app.models import EdgeConfig
    cfg = EdgeConfig.objects.first()
    return cfg.engine_url if cfg else settings.ENGINE_BASE_URL


def health():
    try:
        return requests.get(f"{_base()}/health", timeout=3).json()
    except Exception:
        return {"status": "unreachable", "redis": "unknown", "active_jobs": 0}


def list_jobs():
    try:
        return requests.get(f"{_base()}/jobs/", timeout=5).json()
    except Exception:
        return []


def get_job(job_id):
    try:
        return requests.get(f"{_base()}/jobs/{job_id}", timeout=3).json()
    except Exception:
        return None


def start_job(payload: dict):
    r = requests.post(f"{_base()}/jobs/start", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def stop_job(job_id: str):
    r = requests.post(f"{_base()}/jobs/{job_id}/stop", timeout=10)
    r.raise_for_status()
    return r.json()


def cpu_info():
    try:
        return requests.get(f"{_base()}/cpu", timeout=3).json()
    except Exception:
        return {}


def system_info():
    try:
        return requests.get(f"{_base()}/system", timeout=3).json()
    except Exception:
        return {}


def list_models():
    try:
        return requests.get(f"{_base()}/models", timeout=3).json().get("models", [])
    except Exception:
        return []


def get_model_labels(model_path: str):
    """Fetch class labels for a model. Returns [{id, name}, ...] or [] on failure."""
    try:
        return requests.get(f"{_base()}/models/labels/", params={"path": model_path}, timeout=5).json()
    except Exception:
        return []
