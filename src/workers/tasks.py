"""Celery background tasks."""

from __future__ import annotations

import asyncio

from bson import ObjectId

from src.db.mongodb import col_jobs, connect_db, get_db
from src.services.job_processor import JobProcessor, persist_job_result
from src.workers.celery_app import celery_app

_processor = JobProcessor()


@celery_app.task(bind=True, name="process_recording")
def process_recording_task(
    self, job_id: str, user_id: str, recording_id: str, url: str
) -> dict:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run() -> dict:
        await connect_db()
        db = await get_db()
        job = await col_jobs(db).find_one({"_id": ObjectId(job_id)})
        if not job:
            return {"status": "failed", "error": "Job not found"}

        job["id"] = job_id
        result = _processor.process_recording(url, job_id, recording_id)
        await persist_job_result(db, user_id, job, result)
        return result

    return loop.run_until_complete(_run())
