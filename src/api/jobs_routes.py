"""Jobs API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.auth.dependencies import get_current_user
from src.db.mongodb import col_analytics, col_jobs, col_recordings, get_db
from src.services.job_processor import JobProcessor, persist_job_result

router = APIRouter(prefix="/jobs", tags=["jobs"])

_processor = JobProcessor()


def _serialize_job(job: dict) -> dict:
    return {
        "id": str(job["_id"]),
        "file_name": job.get("file_name"),
        "source": job.get("source"),
        "status": job.get("status"),
        "progress": job.get("progress", 0.0),
        "total_recordings": job.get("total_recordings", 0),
        "completed_count": job.get("completed_count", 0),
        "failed_count": job.get("failed_count", 0),
        "duration_seconds": job.get("duration_seconds"),
        "created_at": job.get("created_at").isoformat()
        if job.get("created_at")
        else None,
        "updated_at": job.get("updated_at").isoformat()
        if job.get("updated_at")
        else None,
    }


@router.get("")
async def list_jobs(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    limit: int = 50,
    skip: int = 0,
) -> dict:
    cursor = (
        col_jobs(db)
        .find({"user_id": current_user["id"]})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    jobs = [_serialize_job(j) async for j in cursor]
    total = await col_jobs(db).count_documents({"user_id": current_user["id"]})
    return {"jobs": jobs, "total": total}


@router.get("/dashboard")
async def dashboard_stats(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    user_id = current_user["id"]
    total_calls = await col_recordings(db).count_documents(
        {"user_id": user_id, "status": "completed"}
    )

    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": None,
                "total_duration": {"$sum": "$call_duration_seconds"},
                "avg_latency": {"$avg": "$avg_agent_latency_ms"},
                "avg_confidence": {"$avg": "$avg_user_confidence"},
            }
        },
    ]
    agg = await col_analytics(db).aggregate(pipeline).to_list(1)
    stats = agg[0] if agg else {}

    completed = await col_recordings(db).count_documents(
        {"user_id": user_id, "status": "completed"}
    )
    failed = await col_recordings(db).count_documents(
        {"user_id": user_id, "status": "failed"}
    )
    queued_recordings = await col_recordings(db).count_documents(
        {"user_id": user_id, "status": "queued"}
    )
    processing_recordings = await col_recordings(db).count_documents(
        {"user_id": user_id, "status": "processing"}
    )
    queued_jobs = await col_jobs(db).count_documents(
        {"user_id": user_id, "status": "queued"}
    )
    processing_jobs = await col_jobs(db).count_documents(
        {"user_id": user_id, "status": "processing"}
    )
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    calls_today = await col_recordings(db).count_documents(
        {
            "user_id": user_id,
            "status": "completed",
            "updated_at": {"$gte": today_start},
        }
    )
    total_processed = completed + failed
    success_rate = (completed / total_processed * 100) if total_processed else 0.0

    recent_cursor = (
        col_jobs(db)
        .find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(10)
    )
    recent_jobs = [_serialize_job(j) async for j in recent_cursor]

    recordings_cursor = (
        col_recordings(db)
        .find({"user_id": user_id})
        .sort("updated_at", -1)
        .limit(20)
    )
    recent_recordings = []
    async for rec in recordings_cursor:
        recent_recordings.append(
            {
                "id": str(rec["_id"]),
                "job_id": rec.get("job_id"),
                "file_name": rec.get("file_name"),
                "status": rec.get("status"),
                "duration_seconds": rec.get("duration_seconds"),
                "user_talk_time_seconds": rec.get("user_talk_time_seconds"),
                "agent_talk_time_seconds": rec.get("agent_talk_time_seconds"),
                "avg_agent_latency_ms": rec.get("avg_agent_latency_ms"),
                "avg_user_confidence": rec.get("avg_user_confidence"),
                "user_audio_url": rec.get("user_audio_url"),
                "agent_audio_url": rec.get("agent_audio_url"),
                "storage_type": rec.get("storage_type"),
                "storage_uri": rec.get("storage_uri"),
                "upload_status": rec.get("upload_status"),
                "gcs_error": rec.get("gcs_error"),
                "error": rec.get("error"),
                "created_at": rec.get("created_at").isoformat()
                if rec.get("created_at")
                else None,
                "updated_at": rec.get("updated_at").isoformat()
                if rec.get("updated_at")
                else None,
            }
        )

    return {
        "total_calls_processed": total_calls,
        "calls_today": calls_today,
        "total_duration_seconds": round(stats.get("total_duration", 0) or 0, 2),
        "avg_agent_latency_ms": round(stats.get("avg_latency", 0) or 0, 2),
        "avg_user_confidence": round(stats.get("avg_confidence", 0) or 0, 3),
        "success_rate": round(success_rate, 1),
        "failed_recordings": failed,
        "queued_recordings": queued_recordings,
        "processing_recordings": processing_recordings,
        "queued_jobs": queued_jobs,
        "processing_jobs": processing_jobs,
        "recent_jobs": recent_jobs,
        "recent_recordings": recent_recordings,
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not ObjectId.is_valid(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    job = await col_jobs(db).find_one(
        {"_id": ObjectId(job_id), "user_id": current_user["id"]}
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    recordings_cursor = col_recordings(db).find({"job_id": job_id})
    recordings = []
    async for rec in recordings_cursor:
        recordings.append(
            {
                "id": str(rec["_id"]),
                "file_name": rec.get("file_name"),
                "recording_url": rec.get("recording_url"),
                "user_audio_url": rec.get("user_audio_url"),
                "agent_audio_url": rec.get("agent_audio_url"),
                "storage_type": rec.get("storage_type"),
                "storage_uri": rec.get("storage_uri"),
                "upload_status": rec.get("upload_status"),
                "status": rec.get("status"),
                "duration_seconds": rec.get("duration_seconds"),
                "error": rec.get("error"),
                "created_at": rec.get("created_at").isoformat()
                if rec.get("created_at")
                else None,
            }
        )

    return {**_serialize_job(job), "recordings": recordings}


@router.post("/{job_id}/retry")
async def retry_failed(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not ObjectId.is_valid(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    job = await col_jobs(db).find_one(
        {"_id": ObjectId(job_id), "user_id": current_user["id"]}
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    failed_recs = col_recordings(db).find({"job_id": job_id, "status": "failed"})
    retried = 0
    async for rec in failed_recs:
        rec_id = str(rec["_id"])
        url = rec["recording_url"]
        await col_recordings(db).update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "queued", "error": None, "updated_at": datetime.now(timezone.utc)}},
        )
        background_tasks.add_task(
            _retry_recording, job_id, current_user["id"], rec_id, url
        )
        retried += 1

    if retried:
        await col_jobs(db).update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": "processing", "updated_at": datetime.now(timezone.utc)}},
        )

    return {"job_id": job_id, "retried": retried}


async def _retry_recording(
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
