import inspect
from core import yolo_inference


def test_infer_accepts_iou_threshold():
    sig = inspect.signature(yolo_inference.infer)
    assert 'iou_threshold' in sig.parameters


def test_infer_iou_default():
    sig = inspect.signature(yolo_inference.infer)
    assert sig.parameters['iou_threshold'].default == 0.45
