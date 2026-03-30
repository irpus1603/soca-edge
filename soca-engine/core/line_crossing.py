"""
Virtual line crossing counter.

Each LineCrossing instance manages one rule's crossing line and maintains
cumulative in/out counts for the lifetime of a job.

Cross-product sign determines which side of the line a centroid is on:
  side = sign((B-A) × (P-A))  where A,B are line endpoints, P is centroid
A sign change between frames → crossing event.
Direction mapping:
  left_to_right  → centroid x increasing across line  → 'in'
  right_to_left  → centroid x decreasing across line  → 'in'
  top_to_bottom  → centroid y increasing across line  → 'in'
  bottom_to_top  → centroid y decreasing across line  → 'in'
  any            → both sides count as 'in'
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.schemas import Detection

logger = logging.getLogger(__name__)


def _sign(v: float) -> int:
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _cross_sign(ax, ay, bx, by, px, py) -> int:
    """Sign of the cross product of (B-A) and (P-A)."""
    return _sign((bx - ax) * (py - ay) - (by - ay) * (px - ax))


def _is_forward(direction: str, prev_cx, prev_cy, cur_cx, cur_cy) -> bool | None:
    """
    Return True  → counts as 'in'
           False → counts as 'out'
           None  → direction='any', always 'in'
    """
    if direction == 'any':
        return None
    dx = cur_cx - prev_cx
    dy = cur_cy - prev_cy
    if direction == 'left_to_right':
        return dx > 0
    if direction == 'right_to_left':
        return dx < 0
    if direction == 'top_to_bottom':
        return dy > 0
    if direction == 'bottom_to_top':
        return dy < 0
    return None


class LineCrossing:
    def __init__(self, line: list[list[float]], direction: str = 'any'):
        """
        Args:
            line: [[x1,y1],[x2,y2]] in normalized 0-1 coords
            direction: 'any' | 'left_to_right' | 'right_to_left' |
                       'top_to_bottom' | 'bottom_to_top'
        """
        self.line = line
        self.direction = direction
        self._prev_side: dict[int, int] = {}   # track_id → side (-1/0/+1)
        self._prev_centroid: dict[int, tuple] = {}  # track_id → (cx, cy) pixels
        self.count_in = 0
        self.count_out = 0

    def update(self, detections: list, frame_shape: tuple) -> dict:
        """
        Process detections for one frame. Only detections with a track_id are counted.

        Args:
            detections: list of Detection objects (already filtered to cls_id=0 / persons)
            frame_shape: (height, width, channels) from frame.shape

        Returns:
            {"in": count_in, "out": count_out}
        """
        if len(self.line) < 2:
            return {"in": self.count_in, "out": self.count_out}

        h, w = frame_shape[0], frame_shape[1]
        (x1n, y1n), (x2n, y2n) = self.line[0], self.line[1]
        ax, ay = x1n * w, y1n * h
        bx, by = x2n * w, y2n * h

        seen_ids = set()
        for det in detections:
            if det.track_id is None:
                continue
            tid = int(det.track_id)
            seen_ids.add(tid)
            cx, cy = det.centroid

            cur_side = _cross_sign(ax, ay, bx, by, cx, cy)
            prev_side = self._prev_side.get(tid)

            if prev_side is not None and prev_side != 0 and cur_side != 0 and prev_side != cur_side:
                # Crossing detected
                prev_c = self._prev_centroid.get(tid, (cx, cy))
                forward = _is_forward(self.direction, prev_c[0], prev_c[1], cx, cy)
                if forward is None:
                    # 'any' direction: every crossing counts as IN regardless of line orientation
                    self.count_in += 1
                elif forward:
                    self.count_in += 1
                else:
                    self.count_out += 1

            self._prev_side[tid] = cur_side
            self._prev_centroid[tid] = (cx, cy)

        # Evict stale track ids
        for tid in list(self._prev_side):
            if tid not in seen_ids:
                del self._prev_side[tid]
                self._prev_centroid.pop(tid, None)

        return {"in": self.count_in, "out": self.count_out}

    def reset(self):
        self._prev_side.clear()
        self._prev_centroid.clear()
        self.count_in = 0
        self.count_out = 0
