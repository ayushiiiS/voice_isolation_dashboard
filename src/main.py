"""FastAPI application entry point for Voice Isolation & Call Analytics Platform."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env before any module reads os.environ (e.g. MongoDB URI).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.analytics_routes import router as analytics_router
from src.api.auth_routes import router as auth_router
from src.api.jobs_routes import router as jobs_router
from src.api.media_routes import router as media_router
from src.api.reports_routes import router as reports_router
from src.api.routes import router as isolation_router
from src.api.upload_routes import router as upload_router
from src.db.mongodb import close_db, connect_db
from src.utils.gcs_auth import GcsPermissionError
from src.utils.gcs_storage import get_storage_client, log_gcp_identity_at_startup

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Voice Isolation & Call Analytics Platform starting")
    await connect_db()
    logger.info("MongoDB connected")
    logger.info("HF_TOKEN set: %s", bool(os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")))
    try:
        identity = log_gcp_identity_at_startup()
        gcs = get_storage_client()
        gcs.verify_bucket_access()
    except GcsPermissionError as exc:
        logger.warning(
            "GCS bucket access limited at startup (jobs will use local fallback): %s",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "GCS startup check skipped (%s). Jobs will use local storage if uploads fail.",
            exc,
        )
    yield
    await close_db()
    logger.info("Platform shutting down")


app = FastAPI(
    title="Voice Isolation & Call Analytics Platform",
    description=(
        "Production SaaS platform for speaker diarization, voice isolation, "
        "and Blue Machines-style call analytics."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(jobs_router)
app.include_router(analytics_router)
app.include_router(reports_router)
app.include_router(media_router)
app.include_router(isolation_router)


@app.get("/")
async def root() -> dict:
    return {
        "service": "Voice Isolation & Call Analytics Platform",
        "version": "2.0.0",
        "endpoints": {
            "auth": "/auth/register, /auth/login",
            "upload": "POST /upload/url, POST /upload/csv",
            "jobs": "GET /jobs, GET /jobs/{id}",
            "analytics": "GET /analytics/{id}",
            "reports": "GET /reports/{id}",
            "health": "GET /health",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
