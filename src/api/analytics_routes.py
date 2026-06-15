"""Analytics API routes."""

from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import get_current_user
from src.db.mongodb import col_analytics, col_recordings, get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/{recording_id}")
async def get_analytics(
    recording_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not ObjectId.is_valid(recording_id):
        raise HTTPException(status_code=404, detail="Analytics not found")

    rec = await col_recordings(db).find_one(
        {"_id": ObjectId(recording_id), "user_id": current_user["id"]}
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    analytics = await col_analytics(db).find_one({"recording_id": recording_id})
    if not analytics:
        raise HTTPException(status_code=404, detail="Analytics not yet available")

    analytics.pop("_id", None)
    return {
        **analytics,
        "recording": {
            "id": recording_id,
            "file_name": rec.get("file_name"),
            "recording_url": rec.get("recording_url"),
            "user_audio_url": rec.get("user_audio_url"),
            "agent_audio_url": rec.get("agent_audio_url"),
            "original_audio_url": rec.get("original_audio_url"),
            "status": rec.get("status"),
            "duration_seconds": rec.get("duration_seconds"),
        },
    }
