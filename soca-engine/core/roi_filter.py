import cv2
import numpy as np
from models.schemas import Detection, ROIConfig


def _scale_points(points: list, frame_shape: tuple) -> list:
    """Scale normalized 0-1 points to pixel coordinates for the given frame shape."""
    h, w = frame_shape[:2]
    return [[int(p[0] * w), int(p[1] * h)] for p in points]


def _build_polygon(roi: ROIConfig, frame_shape: tuple) -> np.ndarray | None:
    if not roi.points:
        return None

    points = _scale_points(roi.points, frame_shape)

    if roi.type == "RECT" and len(points) == 2:
        x1, y1 = points[0]
        x2, y2 = points[1]
        points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    return np.array(points, dtype=np.int32)


def annotate_in_roi(detections: list[Detection], roi: ROIConfig, frame_shape: tuple) -> list[Detection]:
    polygon = _build_polygon(roi, frame_shape)

    for det in detections:
        if polygon is None:
            det.in_roi = True
        else:
            det.in_roi = cv2.pointPolygonTest(polygon, det.centroid, False) >= 0

    return detections
