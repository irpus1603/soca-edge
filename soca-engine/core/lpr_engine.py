"""
License Plate Recognition engine.

Pipeline (single-stage direct plate detection):
  1. Run YOLO plate detection model on the full frame → plate bboxes
  2. Crop each plate bbox, run EasyOCR → plate text + confidence
  3. Filter: skip if confidence < MIN_CONFIDENCE or text length < MIN_TEXT_LEN
  4. Associate plate with nearest Detection (by bbox containment/overlap) if detections provided

Module-level cache follows the same pattern as yolo_inference._cache.
"""

import logging
import re
import threading
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from models.schemas import Detection

logger = logging.getLogger(__name__)

YOLO_CONFIDENCE = 0.35   # min YOLO plate detection confidence
OCR_CONFIDENCE  = 0.20   # min EasyOCR character confidence (permissive — plates vary in quality)
MIN_TEXT_LEN    = 3
PLATE_EXPAND    = 4      # pixels to expand plate crop before OCR

# Allowed plate characters for OCR
_OCR_ALLOWLIST = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -.'

_lock = threading.Lock()
_cache: dict[str, "_LPREngine"] = {}


def _parse_plate(raw: str) -> tuple[str, str]:
    """
    Split Indonesian plate OCR text into (plate_number, plate_expiry).

    Indonesian plates have two rows:
      Row 1: plate number  — e.g. "B 1213 PNV"  or "BG 1213 PXP"
             format: [1-2 alpha] [1-4 digits] [1-3 alpha]
      Row 2: expiry (MMYY) — e.g. "07.22"  or "09-27"

    OCR often merges both rows into one string, e.g. "B1213 PNV07-22".

    Returns:
        plate_number: normalised as "B 1213 PNV"
        plate_expiry: "MM/YY"  or ""  if not found
    """
    text = re.sub(r'\s+', ' ', raw.upper().strip())

    # Step 1: extract MMYY from end — either "MM-YY" / "MM.YY" or bare "MMYY"
    m = re.search(r'(\d{2})[\-\./](\d{2})$', text)
    if m:
        expiry = f"{m.group(1)}/{m.group(2)}"
        plate_part = text[:m.start()].strip()
    else:
        # Bare 4-digit at end — only accept if plausible month (01-12)
        m2 = re.search(r'(0[1-9]|1[0-2])(\d{2})$', text)
        if m2:
            expiry = f"{m2.group(1)}/{m2.group(2)}"
            plate_part = text[:m2.start()].strip()
        else:
            expiry = ''
            plate_part = text

    # Step 2: normalise plate number — strip trailing noise, format with spaces
    plate_part = re.sub(r'[\s\-\.]+$', '', plate_part).strip()
    compact = plate_part.replace(' ', '')

    # Try [1-2 alpha][1-4 digit][1-3 alpha]  (exact)
    pm = re.match(r'^([A-Z]{1,2})(\d{1,4})([A-Z]{1,3})$', compact)
    if pm:
        plate = f"{pm.group(1)} {pm.group(2)} {pm.group(3)}"
    else:
        # Suffix may have OCR noise making it 4 letters — truncate to 3
        pm2 = re.match(r'^([A-Z]{1,2})(\d{1,4})([A-Z]{2,4})$', compact)
        if pm2:
            plate = f"{pm2.group(1)} {pm2.group(2)} {pm2.group(3)[:3]}"
        else:
            plate = plate_part   # best-effort: return as-is

    return plate, expiry


def _iou(a: tuple, b: tuple) -> float:
    """Intersection-over-union of two (x1,y1,x2,y2) boxes."""
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-6)


def _plate_inside_det(plate: tuple, det_bbox: tuple) -> bool:
    """Return True if center of plate bbox is inside det_bbox."""
    px = (plate[0] + plate[2]) / 2
    py = (plate[1] + plate[3]) / 2
    return det_bbox[0] <= px <= det_bbox[2] and det_bbox[1] <= py <= det_bbox[3]


class _LPREngine:
    def __init__(self, plate_model_path: str):
        from ultralytics import YOLO
        import easyocr

        logger.info(f"Loading LPR plate model: {plate_model_path}")
        self._plate_model = YOLO(plate_model_path, task="detect")
        logger.info("Loading EasyOCR reader (en)")
        self._ocr = easyocr.Reader(['en'], gpu=False, verbose=False)

    def process(self, frame: np.ndarray, detections: list = None) -> list[dict]:
        """
        Run YOLO plate detector on full frame, OCR each plate, and optionally
        associate plates with Detection objects by bbox overlap.

        Args:
            frame:      full BGR frame
            detections: optional list of Detection objects (for track_id association)
        Returns:
            list of dicts: [{track_id, plate_number, plate_confidence, plate_bbox}]
        """
        h, w = frame.shape[:2]
        results = []

        # Run YOLO plate detector on full frame
        plate_preds = self._plate_model.predict(source=frame, conf=YOLO_CONFIDENCE, verbose=False)
        if not plate_preds or plate_preds[0].boxes is None:
            return results

        boxes = plate_preds[0].boxes
        if len(boxes) == 0:
            return results

        for i in range(len(boxes)):
            det_conf = float(boxes.conf[i])
            if det_conf < YOLO_CONFIDENCE:
                continue

            px1, py1, px2, py2 = map(int, boxes.xyxy[i].tolist())
            # Expand plate crop slightly for better OCR
            px1e = max(0, px1 - PLATE_EXPAND)
            py1e = max(0, py1 - PLATE_EXPAND)
            px2e = min(w, px2 + PLATE_EXPAND)
            py2e = min(h, py2 + PLATE_EXPAND)

            plate_crop = frame[py1e:py2e, px1e:px2e]
            if plate_crop.size == 0:
                continue

            # OCR on plate crop — restrict to plate-valid characters
            ocr_results = self._ocr.readtext(plate_crop, detail=1, allowlist=_OCR_ALLOWLIST)
            if not ocr_results:
                continue

            raw_text  = "".join(r[1] for r in ocr_results).upper().strip()
            plate_conf = float(max(r[2] for r in ocr_results))

            if len(raw_text) < MIN_TEXT_LEN or plate_conf < OCR_CONFIDENCE:
                continue

            plate_number, plate_expiry = _parse_plate(raw_text)

            # Associate plate with a detection by containment, then overlap
            track_id = None
            if detections:
                plate_box = (px1, py1, px2, py2)
                # First: plate center inside detection bbox
                for det in detections:
                    if _plate_inside_det(plate_box, det.bbox):
                        track_id = det.track_id
                        break
                # Fallback: highest IoU
                if track_id is None:
                    best_iou = 0.0
                    for det in detections:
                        score = _iou(plate_box, det.bbox)
                        if score > best_iou:
                            best_iou = score
                            track_id = det.track_id

            results.append({
                "track_id":         track_id,
                "plate_number":     plate_number,
                "plate_expiry":     plate_expiry,
                "plate_confidence": round(plate_conf, 3),
                "plate_bbox":       [px1, py1, px2, py2],
            })
            logger.debug(f"LPR: {plate_number} exp={plate_expiry} ({plate_conf:.2f}) track={track_id}")

        return results


def get_lpr_engine(plate_model_path: str) -> _LPREngine:
    with _lock:
        if plate_model_path not in _cache:
            _cache[plate_model_path] = _LPREngine(plate_model_path)
    return _cache[plate_model_path]


def unload_lpr_engine(plate_model_path: str) -> None:
    with _lock:
        if plate_model_path in _cache:
            del _cache[plate_model_path]
            logger.info(f"Unloaded LPR engine: {plate_model_path}")
