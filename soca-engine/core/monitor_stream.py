import math
import time
import cv2
import numpy as np
from queue import Queue, Empty
from models.schemas import FrameResult, Detection

# One frame buffer per job_id
_buffers: dict[str, Queue] = {}


def get_or_create_buffer(job_id: str) -> Queue:
    if job_id not in _buffers:
        _buffers[job_id] = Queue(maxsize=2)
    return _buffers[job_id]


def remove_buffer(job_id: str):
    _buffers.pop(job_id, None)


def push_frame(job_id: str, frame: np.ndarray, result: FrameResult, roi=None, rules=None):
    buf = _buffers.get(job_id)
    if buf is None:
        return
    annotated = _annotate(frame.copy(), result, roi, rules)
    if buf.full():
        try:
            buf.get_nowait()
        except Empty:
            pass
    buf.put_nowait(annotated)


def _draw_roi(frame: np.ndarray, roi) -> None:
    if not roi or not roi.points:
        return
    h, w = frame.shape[:2]
    if getattr(roi, 'type', '') == 'LINE':
        if len(roi.points) >= 2:
            p1 = (int(roi.points[0][0] * w), int(roi.points[0][1] * h))
            p2 = (int(roi.points[1][0] * w), int(roi.points[1][1] * h))
            _draw_dashed_line(frame, p1, p2, (0, 165, 255), thickness=2)
            cv2.circle(frame, p1, 5, (0, 165, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, p2, 5, (0, 165, 255), -1, cv2.LINE_AA)
        return
    scaled = [[int(p[0] * w), int(p[1] * h)] for p in roi.points]
    arr = np.array(scaled, dtype=np.int32)
    overlay = frame.copy()
    if roi.type == "POLYGON":
        cv2.fillPoly(overlay, [arr], color=(0, 255, 255))
        cv2.addWeighted(overlay, 0, frame, 0.85, 0, frame)
        cv2.polylines(frame, [arr], isClosed=True, color=(0, 255, 255), thickness=2)
    elif roi.type == "RECT" and len(arr) >= 2:
        cv2.rectangle(overlay, tuple(arr[0]), tuple(arr[1]), (0, 255, 255), -1)
        cv2.addWeighted(overlay, 0, frame, 0.85, 0, frame)
        cv2.rectangle(frame, tuple(arr[0]), tuple(arr[1]), (0, 255, 255), 2)


def _draw_dashed_line(frame: np.ndarray, p1: tuple, p2: tuple, color: tuple,
                      thickness: int = 2, dash_len: int = 14, gap_len: int = 6) -> None:
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    pos, draw = 0.0, True
    while pos < length:
        seg = dash_len if draw else gap_len
        x1 = int(p1[0] + ux * pos)
        y1 = int(p1[1] + uy * pos)
        end = min(pos + seg, length)
        x2 = int(p1[0] + ux * end)
        y2 = int(p1[1] + uy * end)
        if draw:
            cv2.line(frame, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)
        pos += seg
        draw = not draw


def _put_text_bg(frame: np.ndarray, text: str, pos: tuple, color: tuple,
                 scale: float = 0.42, thickness: int = 1) -> None:
    """Draw text with a semi-transparent dark pill behind it."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), bl = cv2.getTextSize(text, font, scale, thickness)
    x, y = pos
    cv2.rectangle(frame, (x - 2, y - th - 2), (x + tw + 3, y + bl + 1), (0, 0, 0), -1)
    cv2.putText(frame, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)


def _draw_crossing_lines(frame: np.ndarray, rules, crossing_counts: dict) -> None:
    """Draw all people_count rule crossing lines with direction arrows and live counts."""
    h, w = frame.shape[:2]
    LINE_COLOR = (0, 165, 255)   # amber (BGR)
    IN_COLOR   = (60, 255, 80)   # green
    arrow_len  = max(22, min(50, int(w * 0.04)))

    for rule in (rules or []):
        if getattr(rule, 'mode', 'detection') != 'people_count':
            continue
        line = getattr(rule, 'crossing_line', None)
        if not line or len(line) < 2:
            continue

        direction = getattr(rule, 'direction', 'any')
        p1 = (int(line[0][0] * w), int(line[0][1] * h))
        p2 = (int(line[1][0] * w), int(line[1][1] * h))
        mx = (p1[0] + p2[0]) // 2
        my = (p1[1] + p2[1]) // 2

        # Dashed amber line
        _draw_dashed_line(frame, p1, p2, LINE_COLOR, thickness=2)

        # Endpoints
        cv2.circle(frame, p1, 5, LINE_COLOR, -1, cv2.LINE_AA)
        cv2.circle(frame, p2, 5, LINE_COLOR, -1, cv2.LINE_AA)

        # Rule name near first endpoint
        _put_text_bg(frame, rule.name, (p1[0] + 8, p1[1] - 8), LINE_COLOR, scale=0.40)

        # Direction arrow at midpoint
        if direction == 'left_to_right':
            cv2.arrowedLine(frame, (mx - arrow_len, my), (mx + arrow_len, my), IN_COLOR, 2, tipLength=0.35, line_type=cv2.LINE_AA)
            _put_text_bg(frame, "IN →", (mx + arrow_len + 4, my + 5), IN_COLOR)
        elif direction == 'right_to_left':
            cv2.arrowedLine(frame, (mx + arrow_len, my), (mx - arrow_len, my), IN_COLOR, 2, tipLength=0.35, line_type=cv2.LINE_AA)
            _put_text_bg(frame, "← IN", (mx - arrow_len - 38, my + 5), IN_COLOR)
        elif direction == 'top_to_bottom':
            cv2.arrowedLine(frame, (mx, my - arrow_len), (mx, my + arrow_len), IN_COLOR, 2, tipLength=0.35, line_type=cv2.LINE_AA)
            _put_text_bg(frame, "IN ↓", (mx + 6, my + arrow_len + 14), IN_COLOR)
        elif direction == 'bottom_to_top':
            cv2.arrowedLine(frame, (mx, my + arrow_len), (mx, my - arrow_len), IN_COLOR, 2, tipLength=0.35, line_type=cv2.LINE_AA)
            _put_text_bg(frame, "IN ↑", (mx + 6, my - arrow_len - 4), IN_COLOR)
        else:  # any — bidirectional
            cv2.arrowedLine(frame, (mx - arrow_len, my), (mx + arrow_len, my), IN_COLOR, 2, tipLength=0.25, line_type=cv2.LINE_AA)
            cv2.arrowedLine(frame, (mx + arrow_len, my), (mx - arrow_len, my), IN_COLOR, 2, tipLength=0.25, line_type=cv2.LINE_AA)

        # Live crossing count below midpoint
        counts   = crossing_counts.get(rule.name, {})
        in_n     = counts.get('in',  0)
        out_n    = counts.get('out', 0)
        count_txt = f"IN:{in_n}  OUT:{out_n}"
        _put_text_bg(frame, count_txt, (mx - 35, my + 22), LINE_COLOR, scale=0.45)


def _annotate(frame: np.ndarray, result: FrameResult, roi=None, rules=None) -> np.ndarray:
    in_roi_count = sum(1 for d in result.detections if d.in_roi)
    any_triggered = any(r.triggered for r in result.rule_results)

    _draw_roi(frame, roi)
    _draw_crossing_lines(frame, rules, result.crossing_counts or {})

    for det in result.detections:
        _draw_detection(frame, det)

    _draw_hud(frame, result, in_roi_count, any_triggered)
    return frame


def _draw_detection(frame: np.ndarray, det: Detection):
    x1, y1, x2, y2 = det.bbox
    color = (0, 255, 0) if det.in_roi else (200, 200, 200)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    label = f"{det.cls_name} {det.confidence:.2f}"
    if det.track_id is not None:
        label = f"#{det.track_id} {label}"
    cv2.putText(frame, label, (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def _draw_hud(frame: np.ndarray, result: FrameResult, in_roi_count: int, triggered: bool):
    h, w = frame.shape[:2]

    # Background bar at top
    cv2.rectangle(frame, (0, 0), (w, 36), (0, 0, 0), -1)

    status_color = (0, 0, 255) if triggered else (0, 255, 0)
    status_text  = "! RULE TRIGGERED" if triggered else "OK"

    cv2.putText(frame, f"job:{result.job_id[:12]}  cam:{result.camera_id}  det:{len(result.detections)}  roi:{in_roi_count}  {status_text}",
                (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_color, 1, cv2.LINE_AA)

    # Aging info at bottom
    if result.aging:
        aging_texts = [f"cls_{k.split('_')[1]}:{v['duration_seconds']:.0f}s" for k, v in result.aging.items()]
        cv2.rectangle(frame, (0, h - 28), (w, h), (0, 0, 0), -1)
        cv2.putText(frame, "  ".join(aging_texts), (8, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA)


def generate_mjpeg(job_id: str):
    buf = get_or_create_buffer(job_id)
    last_jpeg: bytes | None = None

    while True:
        try:
            frame = buf.get_nowait()
            _, arr = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            last_jpeg = arr.tobytes()
        except Empty:
            time.sleep(0.04)  # ~25 FPS hold

        if last_jpeg is not None:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + last_jpeg + b"\r\n")
