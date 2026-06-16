"""Debug endpoints for inspecting the STT pipeline."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import get_current_user
from src.db.mongodb import col_recordings, get_db
from src.stt.audio_source import resolve_stt_audio_source
from src.stt.language_detection import detect_language_from_audio_url, effective_stt_language

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt/debug", tags=["stt-debug"])


@router.get("/{recording_id}/pipeline")
async def inspect_stt_pipeline(
    recording_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """Inspect audio, language detection, and provider mapping for a recording."""
    if not ObjectId.is_valid(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    rec = await col_recordings(db).find_one(
        {"_id": ObjectId(recording_id), "user_id": user["id"]}
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    user_audio_url = rec.get("user_audio_url")
    original_audio_url = rec.get("original_audio_url") or rec.get("recording_url")
    if not user_audio_url:
        raise HTTPException(status_code=400, detail="Isolated user audio not available")

    source_decision = await asyncio.to_thread(
        resolve_stt_audio_source,
        user_audio_url=user_audio_url,
        original_audio_url=original_audio_url,
    )
    detection = await asyncio.to_thread(detect_language_from_audio_url, source_decision.url)
    stt_language = effective_stt_language(detection)

    chosen_quality = (
        source_decision.isolated_quality
        if source_decision.source_type == "isolated_user_audio"
        else source_decision.original_quality
    )

    return {
        "recording_id": recording_id,
        "file_name": rec.get("file_name"),
        "original_audio_url": original_audio_url,
        "user_audio_url": user_audio_url,
        "selected_audio_url": source_decision.url,
        "audio_source_type": source_decision.source_type,
        "audio_quality": chosen_quality.to_dict() if chosen_quality else None,
        "isolated_quality": (
            source_decision.isolated_quality.to_dict()
            if source_decision.isolated_quality
            else None
        ),
        "original_quality": (
            source_decision.original_quality.to_dict()
            if source_decision.original_quality
            else None
        ),
        "language_detection": detection.to_dict(),
        "stt_language": stt_language,
        "provider_language_mapping": {
            provider: stt_language if stt_language != "auto" else "auto-detect"
            for provider in ["deepgram", "azure", "openai", "google", "aws"]
        },
        "config": {
            "whisper_lid_model": os.getenv("WHISPER_LID_MODEL", "small"),
            "language_confidence_threshold": os.getenv("STT_LANGUAGE_CONFIDENCE_THRESHOLD", "0.80"),
            "transcript_mode": os.getenv("STT_TRANSCRIPT_MODE", "consensus"),
            "audio_source_preference": os.getenv("STT_AUDIO_SOURCE", "auto"),
            "feed_realtime": os.getenv("STT_FEED_REALTIME", "false"),
        },
        "warnings": source_decision.warnings,
    }
