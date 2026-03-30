import os
import yaml
from fastapi import APIRouter

router = APIRouter(tags=["models"])


@router.get("/models/labels/")
def get_model_labels(path: str):
    """
    Return [{id, name}] for a model by reading its .names file or data.yaml sibling.
    Returns [] if no label file is found.
    """
    base = os.path.splitext(path)[0]

    # Try <model_name>.names
    names_path = base + ".names"
    if os.path.exists(names_path):
        with open(names_path) as f:
            names = [line.strip() for line in f if line.strip()]
        return [{"id": i, "name": name} for i, name in enumerate(names)]

    # Try <full_model_path>.yaml (e.g. yolo11n.mlpackage.yaml)
    full_yaml_path = path + ".yaml"
    if os.path.exists(full_yaml_path):
        with open(full_yaml_path) as f:
            data = yaml.safe_load(f) or {}
        names = data.get("names", [])
        if isinstance(names, list):
            return [{"id": i, "name": n} for i, n in enumerate(names)]
        if isinstance(names, dict):
            return [{"id": k, "name": v} for k, v in sorted(names.items())]

    # Try <model_name>.yaml (base name without extension, e.g. yolo11n.yaml)
    model_yaml_path = base + ".yaml"
    if os.path.exists(model_yaml_path):
        with open(model_yaml_path) as f:
            data = yaml.safe_load(f) or {}
        names = data.get("names", [])
        if isinstance(names, list):
            return [{"id": i, "name": n} for i, n in enumerate(names)]
        if isinstance(names, dict):
            return [{"id": k, "name": v} for k, v in sorted(names.items())]

    # Try data.yaml in same directory
    yaml_path = os.path.join(os.path.dirname(path), "data.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        names = data.get("names", [])
        if isinstance(names, list):
            return [{"id": i, "name": n} for i, n in enumerate(names)]
        if isinstance(names, dict):
            return [{"id": k, "name": v} for k, v in sorted(names.items())]

    # Fallback: read class names embedded in the .pt model file via ultralytics
    if os.path.exists(path) and path.endswith('.pt'):
        try:
            from ultralytics import YOLO
            m = YOLO(path)
            if hasattr(m, 'names') and m.names:
                names_dict = m.names if isinstance(m.names, dict) else {i: n for i, n in enumerate(m.names)}
                return [{"id": int(k), "name": v} for k, v in sorted(names_dict.items())]
        except Exception:
            pass

    return []
