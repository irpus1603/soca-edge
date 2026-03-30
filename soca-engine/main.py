import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models.db import init_db, get_session, DBJob
from api.jobs import router as jobs_router
from api.health import router as health_router
from api.labels import router as labels_router
from api.config import router as config_router
from api.setup import router as setup_router
from api.models import router as models_router
from core import gcs_sync
import config

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _recover_orphaned_jobs()
    gcs_sync.start()
    yield
    gcs_sync.stop()


def _recover_orphaned_jobs():
    session = get_session()
    try:
        orphaned = session.query(DBJob).filter_by(status="running").all()
        for job in orphaned:
            job.status = "error"
            job.error_msg = "Orphaned: service restarted"
            job.stopped_at = datetime.now(timezone.utc)
        if orphaned:
            session.commit()
            logger.warning(f"Marked {len(orphaned)} orphaned job(s) as error on startup")
    finally:
        session.close()


app = FastAPI(title="SOCA Engine", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(health_router)
app.include_router(labels_router)
app.include_router(config_router)
app.include_router(setup_router)
app.include_router(models_router)
