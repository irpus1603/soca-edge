import logging
import secrets
from pathlib import Path

from fastapi import APIRouter

import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])


@router.post("/generate-key")
def generate_engine_api_key():
    """Generate ENGINE_API_KEY and persist it to .env.

    Only works when ENGINE_API_KEY is not already set — prevents accidental
    overwrite after initial setup.  Call this once on a fresh engine instance,
    then copy the returned key into soca-dashboard Edge Config.
    """
    new_key = secrets.token_hex(16)

    env_path = config.BASE_DIR / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []

    # Remove any existing (empty/commented) ENGINE_API_KEY lines
    lines = [ln for ln in lines if not ln.startswith("ENGINE_API_KEY=")]
    lines.append(f"ENGINE_API_KEY={new_key}")
    env_path.write_text("\n".join(lines) + "\n")

    # Update the in-memory value so subsequent requests see it immediately
    config.ENGINE_API_KEY = new_key

    logger.info("ENGINE_API_KEY generated and written to .env")
    return {"engine_api_key": new_key}
