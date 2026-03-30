import os
import cv2
import logging
import time
import numpy as np

logger = logging.getLogger(__name__)

# Force TCP transport for RTSP — more reliable than UDP on most networks
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


class RTSPConnectionError(Exception):
    pass


class RTSPCapture:
    def __init__(self, rtsp_url: str, max_retries: int = 5):
        self.rtsp_url = rtsp_url
        self.max_retries = max_retries
        self._cap = None
        self._failures = 0
        self._connect()

    def _connect(self):
        if self._cap:
            self._cap.release()

        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.rtsp_url)

        if not cap.isOpened():
            raise RTSPConnectionError(f"Cannot open stream: {self.rtsp_url}")

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        self._failures = 0
        logger.info(f"RTSP connected: {self.rtsp_url}")

    def read_frame(self) -> tuple[bool, np.ndarray | None]:
        ret, frame = self._cap.read()

        if not ret:
            self._failures += 1
            if self._failures >= self.max_retries:
                raise RTSPConnectionError(f"Max retries reached for {self.rtsp_url}")
            delay = min(2 ** self._failures, 32)
            logger.warning(f"Frame read failed, retry {self._failures}/{self.max_retries} in {delay}s")
            time.sleep(delay)
            self._connect()
            return False, None

        self._failures = 0
        return True, frame

    def release(self):
        if self._cap:
            self._cap.release()
            self._cap = None
