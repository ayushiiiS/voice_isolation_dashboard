"""Tests for isolated user audio STT feeding."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from src.stt.audio_feeder import feed_isolated_user_audio
from src.stt.models import SttSessionConfig
from src.stt.orchestrator import MultiProviderOrchestrator
from src.stt.providers.simulated import SimulatedSttProvider


@pytest.fixture
def pcm_wav_url(temp_dir):
    audio = Sine(440).to_audio_segment(duration=2000)
    audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
    path = temp_dir / "user_only.wav"
    audio.export(str(path), format="wav")
    return str(path)


@pytest.mark.asyncio
async def test_feed_isolated_user_audio(pcm_wav_url):
    orchestrator = MultiProviderOrchestrator(
        config=SttSessionConfig(enabled_providers=["deepgram", "azure"])
    )

    def fake_create_enabled(enabled):
        return [
            SimulatedSttProvider("deepgram", "Deepgram", base_confidence=0.94),
            SimulatedSttProvider("azure", "Azure Speech", base_confidence=0.91),
        ]

    with patch("src.stt.orchestrator.ProviderRegistry.create_enabled", fake_create_enabled):
        await orchestrator.start()
        await asyncio.sleep(0.2)

    progress_values: list[float] = []

    async def on_progress(value: float) -> None:
        progress_values.append(value)

    with patch("src.stt.audio_feeder.AudioExtractor") as mock_extractor_cls:
        mock_extractor = MagicMock()
        mock_extractor.load_audio.return_value = (
            AudioSegment.from_wav(pcm_wav_url),
            __import__("pathlib").Path(pcm_wav_url),
            False,
        )
        mock_extractor_cls.return_value = mock_extractor

        await feed_isolated_user_audio(
            orchestrator,
            pcm_wav_url,
            realtime_pacing=False,
            on_progress=on_progress,
        )

    await asyncio.sleep(0.5)
    snapshot = orchestrator.current_snapshot()
    assert progress_values
    assert progress_values[-1] == 1.0
    assert len(snapshot.providers) == 2
    await orchestrator.stop()
