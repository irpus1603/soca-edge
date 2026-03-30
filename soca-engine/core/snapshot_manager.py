import os
import time
import cv2
import logging
import numpy as np

import config

logger = logging.getLogger(__name__)


class SnapshotManager:
    def __init__(self, snapshot_dir: str, min_interval_seconds: int):
        self.snapshot_dir = snapshot_dir
        self.min_interval_seconds = min_interval_seconds
        self._last_saved: float = 0.0  # monotonic time of last successful save

    def should_save(self) -> bool:
        return (time.monotonic() - self._last_saved) >= self.min_interval_seconds

    def save(self, frame: np.ndarray, job_id: str, frame_id: str) -> str | None:
        if not self.should_save():
            return None

        out_dir = os.path.join(self.snapshot_dir, job_id)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{frame_id}.jpg")

        h, w = frame.shape[:2]
        if w > config.SNAPSHOT_MAX_WIDTH:
            scale = config.SNAPSHOT_MAX_WIDTH / w
            frame = cv2.resize(frame, (config.SNAPSHOT_MAX_WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA)

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.SNAPSHOT_JPEG_QUALITY])
        if ok:
            with open(path, "wb") as f:
                f.write(buf.tobytes())
            self._last_saved = time.monotonic()
            return path

        logger.error(f"Failed to write snapshot: {path}")
        return None
