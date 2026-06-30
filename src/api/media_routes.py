"""Serve processed audio files from local storage."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/media", tags=["media"])

PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", "output/processed"))


@router.get("/{recording_id}/{filename}")
async def get_processed_file(recording_id: str, filename: str) -> FileResponse:
    allowed = {
        "original.wav",
        "user_only.wav",
        "agent_only.wav",
        "diarization.json",
        "diarization.rttm",
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="File not found")

    path = (PROCESSED_DIR / recording_id / filename).resolve()
    if not path.is_file() or PROCESSED_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "application/json" if filename.endswith(".json") else "audio/wav"
    return FileResponse(path, media_type=media_type, filename=filename)
