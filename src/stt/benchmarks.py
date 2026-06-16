"""Persist STT accuracy benchmark metrics."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId

from src.db.mongodb import col_stt_accuracy_metrics
from src.stt.models import SttSessionSnapshot

logger = logging.getLogger(__name__)


async def persist_stt_accuracy_metrics(
    db,
    *,
    recording_id: str,
    user_id: str,
    session_id: str,
    snapshot: SttSessionSnapshot,
    latency_ms: float | None = None,
) -> None:
    """Store per-provider accuracy metrics for benchmarking."""
    if not recording_id or not ObjectId.is_valid(recording_id):
        return

    now = datetime.now(timezone.utc)
    base = {
        "recording_id": recording_id,
        "user_id": user_id,
        "session_id": session_id,
        "created_at": now,
        "detected_language": snapshot.detected_language,
        "language_mode": snapshot.language_mode.value if hasattr(snapshot.language_mode, "value") else snapshot.language_mode,
        "language_confidence": snapshot.language_confidence,
        "audio_quality_score": snapshot.audio_quality.score if snapshot.audio_quality else None,
        "consensus_transcript": snapshot.consensus_transcript,
        "primary_transcript": snapshot.primary_transcript,
        "warnings": snapshot.warnings,
    }

    docs = []
    for score in snapshot.provider_scores:
        provider_state = next(
            (p for p in snapshot.providers if p.provider == score.provider),
            None,
        )
        docs.append(
            {
                **base,
                "provider": score.provider,
                "confidence": score.confidence,
                "completeness": score.completeness,
                "language_match": score.language_match,
                "composite_score": score.composite,
                "word_count": score.word_count,
                "latency_ms": provider_state.latency_ms if provider_state else latency_ms,
                "raw_transcript": snapshot.provider_raw_transcripts.get(score.provider, ""),
            }
        )

    if docs:
        await col_stt_accuracy_metrics(db).insert_many(docs)
        logger.info("Stored %d STT accuracy metric rows for recording %s", len(docs), recording_id)
