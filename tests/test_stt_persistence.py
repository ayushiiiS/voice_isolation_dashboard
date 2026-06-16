"""Tests for user-only STT result persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

from src.stt.models import ProviderState, ProviderStatus, SttSessionSnapshot
from src.stt.persistence import persist_user_stt_results


@pytest.mark.asyncio
async def test_persist_user_stt_results_updates_user_confidence_only():
    recording_id = str(ObjectId())
    db = MagicMock()
    db.recordings = MagicMock()
    db.analytics = MagicMock()
    db.recordings.update_one = AsyncMock()
    db.analytics.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    snapshot = SttSessionSnapshot(
        session_id="sess-1",
        selection_mode="auto",
        selected_provider="deepgram",
        best_provider="deepgram",
        best_confidence=94.0,
        primary_transcript="I need help with my account.",
        providers=[
            ProviderState(
                provider="deepgram",
                display_name="Deepgram",
                status=ProviderStatus.ACTIVE,
                normalized_confidence=94.0,
                final_transcript="I need help with my account.",
            )
        ],
        feed_complete=True,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.stt.persistence.col_recordings", lambda _db: db.recordings)
        mp.setattr("src.stt.persistence.col_analytics", lambda _db: db.analytics)
        await persist_user_stt_results(db, recording_id, snapshot)

    rec_update = db.recordings.update_one.await_args.args[1]["$set"]
    assert rec_update["avg_user_confidence"] == 0.94
    assert rec_update["stt_source"] == "isolated_user_audio"
    assert "avg_agent_confidence" not in rec_update

    analytics_update = db.analytics.update_one.await_args.args[1]["$set"]
    assert analytics_update["avg_user_confidence"] == 0.94
    assert analytics_update["user_stt_transcript"][0]["role"] == "user"
