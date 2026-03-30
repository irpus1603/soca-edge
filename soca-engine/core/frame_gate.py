import time
import cv2
import numpy as np


class FrameGate:
    def __init__(self, frame_interval_ms: int):
        self.interval_s = frame_interval_ms / 1000.0
        self._last_processed = 0.0

    def should_process(self, frame: np.ndarray) -> bool:
        if self._is_blank(frame) or self._is_uniform(frame):
            return False
        if (time.monotonic() - self._last_processed) < self.interval_s:
            return False
        self._last_processed = time.monotonic()
        return True

    def _is_blank(self, frame: np.ndarray) -> bool:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(np.std(gray)) < 10.0

    def _is_uniform(self, frame: np.ndarray) -> bool:
        return bool(np.all(np.abs(frame - frame.mean()) < 15))
