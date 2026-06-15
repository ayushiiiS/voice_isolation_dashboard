"""Shared pytest fixtures."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from src.diarization.models import SpeakerSegment


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_wav(temp_dir: Path) -> Path:
    """Create a short synthetic WAV file for testing."""
    audio = Sine(440).to_audio_segment(duration=2000)
    audio += Sine(330).to_audio_segment(duration=1500)
    path = temp_dir / "sample.wav"
    audio.export(str(path), format="wav")
    return path


@pytest.fixture
def two_speaker_segments() -> list[SpeakerSegment]:
    """Simulated diarization for a human + agent conversation."""
    return [
        SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=2.0),
        SpeakerSegment(speaker="SPEAKER_01", start=2.2, end=4.5),
        SpeakerSegment(speaker="SPEAKER_00", start=4.8, end=7.0),
        SpeakerSegment(speaker="SPEAKER_01", start=7.3, end=9.0),
        SpeakerSegment(speaker="SPEAKER_00", start=9.2, end=11.5),
    ]
