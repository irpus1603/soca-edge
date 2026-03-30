"""
Async background task: sync local snapshots/ to GCS.

Polls SNAPSHOTS_DIR every SYNC_INTERVAL_SECONDS, uploads any .jpg not yet
uploaded this session. GCS object key: {prefix}snapshots/{job_id}/{frame}.jpg
— matches the path that soca-control's Alert.snapshot_url expects.
"""

import asyncio
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 10

_task: asyncio.Task | None = None


def _build_blob_name(jpg: Path, snapshots_root: Path) -> str:
    rel = jpg.relative_to(snapshots_root)          # {job_id}/{frame}.jpg
    prefix = config.GCS_PATH_PREFIX.strip('/')
    if prefix:
        return f"{prefix}/snapshots/{rel}"
    return f"snapshots/{rel}"


def _gcs_client():
    """Return a GCS client, using explicit credentials when GCS_KEY_PATH is set."""
    from google.cloud import storage as gcs
    key = config.GCS_KEY_PATH
    if key and Path(key).exists():
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            key,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return gcs.Client(credentials=creds)
    return gcs.Client()


def _upload(blob_name: str, local_path: str) -> None:
    """Synchronous GCS upload — called via asyncio.to_thread."""
    client = _gcs_client()
    bucket = client.bucket(config.GCS_BUCKET)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path, content_type="image/jpeg")


async def _sync_loop() -> None:
    uploaded: set[str] = set()
    snapshots_root = Path(config.SNAPSHOTS_DIR)
    logger.info(f"GCS sync started — bucket={config.GCS_BUCKET} dir={snapshots_root}")

    while True:
        try:
            if snapshots_root.exists():
                for jpg in snapshots_root.rglob("*.jpg"):
                    abs_path = str(jpg)
                    if abs_path in uploaded:
                        continue
                    blob_name = _build_blob_name(jpg, snapshots_root)
                    try:
                        await asyncio.to_thread(_upload, blob_name, abs_path)
                        uploaded.add(abs_path)
                        logger.debug(f"GCS sync: uploaded {blob_name}")
                    except Exception as exc:
                        logger.warning(f"GCS sync: upload failed {blob_name}: {exc}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"GCS sync loop error: {exc}")

        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


def start() -> None:
    """Start the GCS sync background task. No-op if GCS_BUCKET is not set."""
    global _task
    if not config.GCS_BUCKET:
        logger.debug("GCS sync disabled (GCS_BUCKET not set)")
        return
    _task = asyncio.create_task(_sync_loop(), name="gcs-sync")


def stop() -> None:
    """Cancel the GCS sync background task."""
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None
