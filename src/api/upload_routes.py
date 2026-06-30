"""Upload API routes."""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, field_validator

from src.auth.dependencies import get_current_user
from src.db.mongodb import col_jobs, col_recordings, get_db
from src.isolation.audio_extractor import SUPPORTED_EXTENSIONS
from src.services.job_processor import JobProcessor, new_recording_id, persist_job_result, recording_filename
from src.utils.audio_validation import validate_downloaded_audio
from src.utils.recording_url_resolver import is_bluemachines_console_url, is_direct_audio_url

router = APIRouter(prefix="/upload", tags=["upload"])

_processor = JobProcessor()

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
UPLOAD_DIR = Path(
    os.getenv(
        "UPLOAD_DIR",
        str(Path(os.getenv("WORK_DIR", "output/.work")) / "uploads"),
    )
)


class UrlUploadRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_recording_url(cls, value: str) -> str:
        value = value.strip()
        if is_bluemachines_console_url(value):
            return value
        parsed = urlparse(value)
        if parsed.scheme in ("http", "https"):
            if not is_direct_audio_url(value) and "storage.googleapis.com" not in parsed.netloc:
                raise ValueError(
                    "HTTPS URL must be a direct audio file (.ogg, .wav, .mp3, .m4a) "
                    "or a Blue Machines console interaction link"
                )
            return value
        if parsed.scheme == "gs":
            if not parsed.netloc or not parsed.path.strip("/"):
                raise ValueError("Invalid gs:// URL — expected gs://bucket/object/path")
            return value
        raise ValueError(
            "URL must use http, https, gs, or a Blue Machines console interaction link"
        )


class UploadResponse(BaseModel):
    job_id: str
    message: str
    total_recordings: int = 1


async def _create_job(
    db,
    user_id: str,
    urls: list[str],
    source: str,
    file_name: str | None = None,
    recording_ids: list[str] | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    job_id = str(ObjectId())

    recording_docs = []
    for index, url in enumerate(urls):
        rec_id = (
            recording_ids[index]
            if recording_ids and index < len(recording_ids)
            else new_recording_id()
        )
        name = file_name or recording_filename(url)
        recording_docs.append(
            {
                "_id": ObjectId(rec_id),
                "job_id": job_id,
                "user_id": user_id,
                "recording_url": url,
                "file_name": name,
                "status": "queued",
                "created_at": now,
                "updated_at": now,
            }
        )

    job_doc = {
        "_id": ObjectId(job_id),
        "user_id": user_id,
        "source": source,
        "file_name": file_name or (f"batch_{len(urls)}_urls" if len(urls) > 1 else recording_filename(urls[0])),
        "status": "queued",
        "progress": 0.0,
        "total_recordings": len(urls),
        "completed_count": 0,
        "failed_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    await col_jobs(db).insert_one(job_doc)
    if recording_docs:
        await col_recordings(db).insert_many(recording_docs)

    return {
        "id": job_id,
        "user_id": user_id,
        "total_recordings": len(urls),
        "recording_docs": recording_docs,
    }


async def _process_job_background(
    db,
    user_id: str,
    job_info: dict,
    background_tasks: BackgroundTasks,
) -> None:
    job_id = job_info["id"]

    await col_jobs(db).update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": "processing", "updated_at": datetime.now(timezone.utc)}},
    )

    use_celery = os.getenv("USE_CELERY", "false").lower() == "true"

    for rec in job_info["recording_docs"]:
        rec_id = str(rec["_id"])
        url = rec["recording_url"]

        if use_celery:
            from src.workers.tasks import process_recording_task

            process_recording_task.delay(job_id, user_id, rec_id, url)
        else:
            background_tasks.add_task(
                _run_job_in_background, job_id, user_id, rec_id, url
            )


async def _run_job_in_background(
    job_id: str, user_id: str, recording_id: str, url: str
) -> None:
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    db = await get_db()
    job = await col_jobs(db).find_one({"_id": ObjectId(job_id)})
    if not job:
        return
    job["id"] = job_id

    try:
        result = await asyncio.to_thread(
            _processor.process_recording, url, job_id, recording_id
        )
        await persist_job_result(db, user_id, job, result)
    except Exception as exc:
        logger.exception("Background job failed for recording %s", recording_id)
        await persist_job_result(
            db,
            user_id,
            job,
            {
                "recording_id": recording_id,
                "job_id": job_id,
                "recording_url": url,
                "status": "failed",
                "error": str(exc),
            },
        )


@router.post("/url", response_model=UploadResponse)
async def upload_url(
    body: UrlUploadRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> UploadResponse:
    url = body.url
    job_info = await _create_job(
        db, current_user["id"], [url], source="url", file_name=recording_filename(url)
    )
    await _process_job_background(db, current_user["id"], job_info, background_tasks)

    return UploadResponse(
        job_id=job_info["id"],
        message="Recording queued for processing",
        total_recordings=1,
    )


@router.post("/csv", response_model=UploadResponse)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a CSV",
        )

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    urls: list[str] = []
    url_columns = {"url", "recording_url", "recordingurl", "recording"}
    for row in reader:
        for key, value in row.items():
            if key and key.strip().lower() in url_columns and value and value.strip():
                urls.append(value.strip())
                break

    if not urls:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV must contain a 'url' column with recording URLs",
        )

    job_info = await _create_job(
        db,
        current_user["id"],
        urls,
        source="csv",
        file_name=file.filename,
    )
    await _process_job_background(db, current_user["id"], job_info, background_tasks)

    return UploadResponse(
        job_id=job_info["id"],
        message=f"Batch upload queued: {len(urls)} recordings",
        total_recordings=len(urls),
    )


def _safe_upload_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name or name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid filename",
        )
    return name


@router.post("/file", response_model=UploadResponse)
async def upload_audio_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing filename",
        )

    safe_name = _safe_upload_filename(file.filename)
    ext = Path(safe_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported audio format '{ext or '(none)'}'. Allowed: {allowed}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum upload size ({MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )

    rec_id = new_recording_id()
    dest_dir = UPLOAD_DIR / rec_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_name

    try:
        dest.write_bytes(content)
        validate_downloaded_audio(dest)
    except ValueError as exc:
        if dest.exists():
            dest.unlink()
        if dest_dir.exists() and not any(dest_dir.iterdir()):
            dest_dir.rmdir()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    local_path = str(dest.resolve())
    job_info = await _create_job(
        db,
        current_user["id"],
        [local_path],
        source="file",
        file_name=safe_name,
        recording_ids=[rec_id],
    )
    await _process_job_background(db, current_user["id"], job_info, background_tasks)

    return UploadResponse(
        job_id=job_info["id"],
        message="Recording queued for processing",
        total_recordings=1,
    )
