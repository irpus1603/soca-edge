import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_DAYS = {30, 90, 180, 365}


def _cutoff(older_than_days: int) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=older_than_days)


def purge_preview(engine_db_path: str, snapshots_root: str, older_than_days: int) -> dict:
    """Return counts and disk usage of records older than cutoff. No deletion."""
    if older_than_days not in VALID_DAYS:
        raise ValueError(f"older_than must be one of {VALID_DAYS}")
    cutoff = _cutoff(older_than_days)
    cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')

    con = sqlite3.connect(engine_db_path)
    try:
        rows = con.execute(
            "SELECT snapshot_path FROM detection_events WHERE timestamp < ?",
            (cutoff_str,)
        ).fetchall()
    finally:
        con.close()

    record_count = len(rows)
    file_count = 0
    disk_bytes = 0
    snapshots_root_path = Path(snapshots_root)

    for (snap_path,) in rows:
        if not snap_path:
            continue
        full = (snapshots_root_path / snap_path).resolve()
        if not str(full).startswith(str(snapshots_root_path)):
            continue  # path traversal guard
        try:
            size = full.stat().st_size
            file_count += 1
            disk_bytes += size
        except OSError:
            pass  # missing file — skip

    return {
        'older_than_days': older_than_days,
        'cutoff_date': cutoff.strftime('%Y-%m-%d'),
        'record_count': record_count,
        'file_count': file_count,
        'disk_bytes': disk_bytes,
    }


def purge_execute(engine_db_path: str, snapshots_root: str, older_than_days: int) -> dict:
    """Delete records and snapshot files older than cutoff."""
    if older_than_days not in VALID_DAYS:
        raise ValueError(f"older_than must be one of {VALID_DAYS}")
    cutoff = _cutoff(older_than_days)
    cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')

    con = sqlite3.connect(engine_db_path)
    try:
        rows = con.execute(
            "SELECT snapshot_path FROM detection_events WHERE timestamp < ?",
            (cutoff_str,)
        ).fetchall()
        con.execute("DELETE FROM detection_events WHERE timestamp < ?", (cutoff_str,))
        con.commit()
        deleted_records = len(rows)
    finally:
        con.close()

    snapshots_root_path = Path(snapshots_root)
    deleted_files = 0
    skipped_files = 0
    freed_bytes = 0

    for (snap_path,) in rows:
        if not snap_path:
            continue
        full = (snapshots_root_path / snap_path).resolve()
        if not str(full).startswith(str(snapshots_root_path)):
            skipped_files += 1
            continue  # path traversal guard
        try:
            size = full.stat().st_size
            freed_bytes += size
            os.remove(full)
            deleted_files += 1
        except OSError as e:
            logger.warning('purge: could not delete %s: %s', full, e)
            skipped_files += 1

    return {
        'deleted_records': deleted_records,
        'deleted_files': deleted_files,
        'skipped_files': skipped_files,
        'freed_bytes': freed_bytes,
    }
