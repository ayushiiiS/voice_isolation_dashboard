"""Tests for audio loading and segment extraction."""

from pathlib import Path

import pytest

from pydub import AudioSegment

from src.diarization.models import SpeakerSegment
from src.isolation.audio_extractor import AudioExtractor, SUPPORTED_EXTENSIONS


def test_load_local_audio(sample_wav: Path):
    extractor = AudioExtractor()
    audio, path, is_temp = extractor.load_audio(str(sample_wav))

    assert isinstance(audio, AudioSegment)
    assert path == sample_wav.resolve()
    assert is_temp is False
    assert extractor.duration_seconds(audio) > 0


def test_extract_human_segments(sample_wav: Path, two_speaker_segments: list[SpeakerSegment]):
    extractor = AudioExtractor()
    audio, _, _ = extractor.load_audio(str(sample_wav))

    human_audio, human_segs, agent_segs = extractor.extract_human_segments(
        audio=audio,
        segments=two_speaker_segments,
        human_speaker="SPEAKER_01",
        agent_speaker="SPEAKER_00",
    )

    assert len(human_segs) == 2
    assert len(agent_segs) == 3
    assert extractor.duration_seconds(human_audio) > 0


def test_export_wav(temp_dir: Path, sample_wav: Path):
    extractor = AudioExtractor()
    audio, _, _ = extractor.load_audio(str(sample_wav))

    out_path = temp_dir / "user_only.wav"
    result = extractor.export_wav(audio, out_path)

    assert result.exists()
    assert result.suffix == ".wav"


def test_unsupported_extension_raises(temp_dir: Path):
    bad_file = temp_dir / "audio.xyz"
    bad_file.write_text("not audio")

    extractor = AudioExtractor()
    with pytest.raises(ValueError, match="Unsupported audio format"):
        extractor.load_audio(str(bad_file))


def test_supported_extensions():
    assert ".wav" in SUPPORTED_EXTENSIONS
    assert ".mp3" in SUPPORTED_EXTENSIONS
    assert ".m4a" in SUPPORTED_EXTENSIONS
