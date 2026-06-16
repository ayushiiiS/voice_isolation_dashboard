"""Feed isolated user audio files into the multi-provider STT orchestrator."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Optional

from src.isolation.audio_extractor import AudioExtractor
from src.stt.audio_preprocess import prepare_for_stt
from src.stt.orchestrator import MultiProviderOrchestrator

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float], Awaitable[None]]


async def feed_isolated_user_audio(
    orchestrator: MultiProviderOrchestrator,
    audio_url: str,
    *,
    sample_rate: int = 16000,
    chunk_ms: int = 100,
    realtime_pacing: bool | None = None,
    on_progress: Optional[ProgressCallback] = None,
) -> None:
    """Load user audio and stream PCM16 chunks to all STT providers."""
    if realtime_pacing is None:
        realtime_pacing = os.getenv("STT_FEED_REALTIME", "false").lower() == "true"

    extractor = AudioExtractor()
    loop = asyncio.get_running_loop()

    audio, local_path, is_temp = await loop.run_in_executor(
        None, lambda: extractor.load_audio(audio_url)
    )

    try:
        audio = prepare_for_stt(audio, target_sample_rate=sample_rate)
        await orchestrator.set_audio_duration(len(audio) / 1000.0)
        raw = audio.raw_data
        if not raw:
            logger.warning("User audio is empty: %s", audio_url)
            return

        bytes_per_chunk = int(sample_rate * (chunk_ms / 1000.0)) * 2
        total_chunks = max(1, (len(raw) + bytes_per_chunk - 1) // bytes_per_chunk)

        logger.info(
            "Feeding user audio (%d bytes, %d chunks, realtime=%s) from %s",
            len(raw),
            total_chunks,
            realtime_pacing,
            audio_url,
        )

        for index, offset in enumerate(range(0, len(raw), bytes_per_chunk), start=1):
            chunk = raw[offset : offset + bytes_per_chunk]
            await orchestrator.send_audio(chunk)
            if on_progress:
                await on_progress(index / total_chunks)
            if realtime_pacing and chunk_ms > 0:
                await asyncio.sleep(chunk_ms / 1000.0)

        if on_progress:
            await on_progress(1.0)
    finally:
        if is_temp and local_path.exists():
            local_path.unlink(missing_ok=True)
