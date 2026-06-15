"""Upload API routes."""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, field_validator

from src.auth.dependencies import get_current_user
from src.db.mongodb import col_jobs, col_recordings, get_db
from src.services.job_processor import JobProcessor, new_recording_id, persist_job_result, recording_filename
from src.utils.recording_url_resolver import is_bluemachines_console_url, is_direct_audio_url

router = APIRouter(prefix="/upload", tags=["upload"])

_processor = JobProcessor()


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
) -> dict:
    now = datetime.now(timezone.utc)
    job_id = str(ObjectId())

    recording_docs = []
    for url in urls:
        rec_id = new_recording_id()
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

    db = await get_db()
    job = await col_jobs(db).find_one({"_id": ObjectId(job_id)})
    if not job:
        return
    job["id"] = job_id

    result = await asyncio.to_thread(
        _processor.process_recording, url, job_id, recording_id
    )
    await persist_job_result(db, user_id, job, result)


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
