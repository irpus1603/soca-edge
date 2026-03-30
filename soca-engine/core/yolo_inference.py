import os
import threading
import logging
import numpy as np
import torch
from ultralytics import YOLO
from models.schemas import Detection
import config

logger = logging.getLogger(__name__)

os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

_cache: dict[str, YOLO] = {}
_lock = threading.Lock()


def _resolve_device() -> str:
    device = config.INFER_DEVICE
    if device == "auto":
        if torch.cuda.is_available():
            return "cuda:0"
        return "cpu"
    if device == "mps":
        logger.warning("MPS is disabled; falling back to CPU")
        return "cpu"
    if device.startswith("cuda") and not torch.cuda.is_available():
        logger.warning("CUDA not available, falling back to CPU")
        return "cpu"
    return device


def _is_onnx(model_path: str) -> bool:
    return model_path.lower().endswith(".onnx")


def _load_model(model_path: str) -> YOLO:
    with _lock:
        if model_path not in _cache:
            if len(_cache) >= config.MAX_LOADED_MODELS:
                raise RuntimeError(f"Model capacity reached ({config.MAX_LOADED_MODELS})")
            device = _resolve_device()
            logger.info(f"Loading model: {model_path} on device={device}")
            model = YOLO(model_path, task="detect")
            if not _is_onnx(model_path):
                model.to(device)
            _cache[model_path] = model
    return _cache[model_path]


def unload_model(model_path: str) -> None:
    with _lock:
        if model_path in _cache:
            del _cache[model_path]
            logger.info(f"Unloaded model: {model_path}")


def infer(frame: np.ndarray, model_path: str, cls_ids: list[int], conf: float = 0.5,
          iou_threshold: float = 0.45, imgsz: int | None = None) -> list[Detection]:
    model = _load_model(model_path)
    results = model.track(
        source=frame,
        persist=True,
        conf=conf,
        iou=iou_threshold,
        classes=cls_ids,
        verbose=False,
        device=_resolve_device(),
        imgsz=imgsz if imgsz is not None else config.INFER_IMGSZ,
        half=config.INFER_HALF,
    )

    if not results or not results[0].boxes:
        return []

    detections = []
    label_map = model.names

    for box in results[0].boxes:
        cls_id = int(box.cls.item())
        if cls_id not in cls_ids:
            continue

        x1, y1, x2, y2 = map(int, box.xyxy[0])
        track_id = int(box.id.item()) if box.id is not None else None

        detections.append(Detection(
            cls_id=cls_id,
            cls_name=label_map.get(cls_id, f"class_{cls_id}"),
            confidence=float(box.conf.item()),
            bbox=(x1, y1, x2, y2),
            track_id=track_id,
        ))

    return detections
