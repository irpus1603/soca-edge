import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Security, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse

import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["models"])
_bearer = HTTPBearer()

ALLOWED_EXTENSIONS = {".pt", ".onnx", ".yml", ".yaml"}


def _require_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    if not config.ENGINE_API_KEY:
        raise HTTPException(status_code=503, detail="ENGINE_API_KEY not configured on this engine")
    if creds.credentials != config.ENGINE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid ENGINE_API_KEY")


def _models_dir() -> Path:
    d = Path(config.MODELS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("", dependencies=[Security(_require_auth)])
def list_models():
    """List all model files in MODELS_DIR."""
    d = _models_dir()
    files = []
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "ext": f.suffix.lower(),
            })
    return {"models": files}


@router.post("/upload", dependencies=[Security(_require_auth)])
async def upload_model(file: UploadFile = File(...)):
    """Upload a YOLO model (.pt, .onnx) or label file (.yml/.yaml) to MODELS_DIR."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    safe_name = Path(file.filename).name
    dest = _models_dir() / safe_name
    try:
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        await file.close()
    logger.info("Model uploaded: %s (%d bytes)", dest, dest.stat().st_size)
    return {"status": "ok", "name": safe_name, "size": dest.stat().st_size}


@router.delete("/{filename}", dependencies=[Security(_require_auth)])
def delete_model(filename: str):
    """Delete a model file from MODELS_DIR."""
    safe_name = Path(filename).name          # strip any path traversal
    if not safe_name or safe_name != filename:
        raise HTTPException(status_code=422, detail="Invalid filename")
    target = _models_dir() / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found")
    target.unlink()
    logger.info("Model deleted: %s", target)
    return {"status": "ok", "name": safe_name}
