import numpy as np
import pytest
from core.monitor_stream import _draw_roi


class _ROI:
    def __init__(self, roi_type, points):
        self.type = roi_type
        self.points = points


def test_line_roi_draws_pixels():
    """LINE ROI must be rendered — pixels must change from zero."""
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    roi = _ROI('LINE', [[0.1, 0.1], [0.9, 0.9]])
    _draw_roi(frame, roi)
    assert frame.sum() > 0, "LINE ROI drew nothing — crossing line is invisible"


def test_polygon_roi_still_draws():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    roi = _ROI('POLYGON', [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]])
    _draw_roi(frame, roi)
    assert frame.sum() > 0
