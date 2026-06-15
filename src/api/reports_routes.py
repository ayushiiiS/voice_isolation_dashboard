"""Reports API routes."""

from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.auth.dependencies import get_current_user
from src.db.mongodb import col_recordings, col_reports, get_db

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{recording_id}")
async def get_reports(
    recording_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not ObjectId.is_valid(recording_id):
        raise HTTPException(status_code=404, detail="Report not found")

    rec = await col_recordings(db).find_one(
        {"_id": ObjectId(recording_id), "user_id": current_user["id"]}
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    report = await col_reports(db).find_one({"recording_id": recording_id})
    if not report:
        raise HTTPException(status_code=404, detail="Report not yet available")

    report.pop("_id", None)
    return report
