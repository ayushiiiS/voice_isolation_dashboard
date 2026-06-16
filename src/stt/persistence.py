"""Persist user-only STT comparison results to recording analytics."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from src.analytics.models import TranscriptEntry
from src.db.mongodb import col_analytics, col_recordings
from src.stt.models import SttSessionSnapshot

logger = logging.getLogger(__name__)


def _user_confidence(snapshot: SttSessionSnapshot) -> Optional[float]:
    """Return selected/best user STT confidence on 0–1 scale for analytics storage."""
    provider_id = snapshot.selected_provider or snapshot.best_provider
    if provider_id:
        for provider in snapshot.providers:
            if provider.provider == provider_id and provider.normalized_confidence is not None:
                return round(provider.normalized_confidence / 100.0, 3)

    if snapshot.best_confidence is not None:
        return round(snapshot.best_confidence / 100.0, 3)
    return None


def _user_transcript_entries(snapshot: SttSessionSnapshot) -> list[dict]:
    """Build user-only transcript entries from consensus or selected provider."""
    text = (
        snapshot.consensus_transcript
        or snapshot.processed_transcript
        or snapshot.primary_transcript
        or ""
    ).strip()
    if not text:
        return []

    provider_id = snapshot.selected_provider or snapshot.best_provider or "stt_consensus"
    confidence = _user_confidence(snapshot) or 0.0
    return [
        TranscriptEntry(
            speaker="USER",
            role="user",
            text=text,
            start=0.0,
            end=0.0,
            confidence=confidence,
        ).model_dump()
    ]


async def persist_user_stt_results(
    db,
    recording_id: str,
    snapshot: SttSessionSnapshot,
) -> None:
    """Save user-audio STT confidence and transcript; never writes agent STT data."""
    if not recording_id or not ObjectId.is_valid(recording_id):
        return

    user_conf = _user_confidence(snapshot)
    user_transcript = _user_transcript_entries(snapshot)
    now = datetime.now(timezone.utc)

    transcript_text = (
        snapshot.consensus_transcript
        or snapshot.processed_transcript
        or snapshot.primary_transcript
        or ""
    ).strip()

    update_fields: dict = {
        "updated_at": now,
        "stt_source": "isolated_user_audio",
        "stt_selected_provider": snapshot.selected_provider,
        "stt_best_provider": snapshot.best_provider,
        "stt_transcript_mode": snapshot.transcript_mode.value if hasattr(snapshot.transcript_mode, "value") else snapshot.transcript_mode,
    }
    if user_conf is not None:
        update_fields["avg_user_confidence"] = user_conf
    if snapshot.detected_language:
        update_fields["stt_detected_language"] = snapshot.detected_language
    if snapshot.language_code:
        update_fields["stt_language_code"] = snapshot.language_code
    if snapshot.language_confidence is not None:
        update_fields["stt_language_confidence"] = snapshot.language_confidence
    if snapshot.audio_quality:
        update_fields["stt_audio_quality_score"] = snapshot.audio_quality.score
    if transcript_text:
        update_fields["stt_user_transcript"] = transcript_text
    if snapshot.consensus_transcript:
        update_fields["stt_consensus_transcript"] = snapshot.consensus_transcript
    if snapshot.provider_raw_transcripts:
        update_fields["stt_provider_raw_transcripts"] = snapshot.provider_raw_transcripts

    await col_recordings(db).update_one(
        {"_id": ObjectId(recording_id)},
        {"$set": update_fields},
    )

    analytics_update: dict = {
        "stt_source": "isolated_user_audio",
        "stt_selected_provider": snapshot.selected_provider,
        "stt_best_provider": snapshot.best_provider,
    }
    if user_conf is not None:
        analytics_update["avg_user_confidence"] = user_conf
    if snapshot.detected_language:
        analytics_update["stt_detected_language"] = snapshot.detected_language
    if snapshot.language_code:
        analytics_update["stt_language_code"] = snapshot.language_code
    if user_transcript:
        analytics_update["user_stt_transcript"] = user_transcript

    result = await col_analytics(db).update_one(
        {"recording_id": recording_id},
        {"$set": analytics_update},
    )
    if result.matched_count == 0:
        logger.warning("No analytics document to update for recording %s", recording_id)

    logger.info(
        "Persisted user-only STT results for recording %s (confidence=%s, provider=%s)",
        recording_id,
        user_conf,
        snapshot.selected_provider,
    )
