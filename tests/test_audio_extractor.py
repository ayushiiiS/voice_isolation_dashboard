"""Tests for audio loading and segment extraction."""

from pathlib import Path

import numpy as np
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


def test_merge_adjacent_segments(two_speaker_segments):
    from src.isolation.audio_extractor import merge_adjacent_segments

    segments = [
        two_speaker_segments[1],
        SpeakerSegment(speaker="SPEAKER_01", start=4.6, end=5.0),
    ]
    merged = merge_adjacent_segments(segments, max_gap_seconds=0.5)
    assert len(merged) == 1
    assert merged[0].start == 2.2
    assert merged[0].end == 5.0


def test_supported_extensions():
    assert ".wav" in SUPPORTED_EXTENSIONS
    assert ".mp3" in SUPPORTED_EXTENSIONS
    assert ".m4a" in SUPPORTED_EXTENSIONS
    assert ".ogg" in SUPPORTED_EXTENSIONS


def test_timeline_tracks_match_original_duration():
    from pydub.generators import Sine

    audio = Sine(440).to_audio_segment(duration=10000)
    segments = [
        SpeakerSegment(speaker="SPEAKER_01", start=1.0, end=3.0),
        SpeakerSegment(speaker="SPEAKER_00", start=5.0, end=7.0),
    ]
    extractor = AudioExtractor()
    user_audio, agent_audio, _, _ = extractor.extract_timeline_tracks(
        audio,
        segments,
        human_speaker="SPEAKER_01",
        agent_speaker="SPEAKER_00",
    )

    assert len(user_audio) == len(audio)
    assert len(agent_audio) == len(audio)


def test_timeline_user_silent_during_agent_speech():
    from pydub.generators import Sine

    audio = Sine(220).to_audio_segment(duration=5000)
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=1.0, end=2.0),
    ]
    extractor = AudioExtractor()
    user_audio, agent_audio, _, _ = extractor.extract_timeline_tracks(
        audio,
        segments,
        human_speaker="SPEAKER_01",
        agent_speaker="SPEAKER_00",
        padding_ms=0,
    )

    user = np.array(user_audio.get_array_of_samples(), dtype=np.int16)
    agent = np.array(agent_audio.get_array_of_samples(), dtype=np.int16)
    frame_rate = user_audio.frame_rate
    agent_start = int(1.0 * frame_rate)
    agent_end = int(2.0 * frame_rate)

    assert np.all(user[agent_start:agent_end] == 0)
    assert np.any(agent[agent_start:agent_end] != 0)
    assert np.all(agent[:agent_start] == 0)


def test_timeline_silence_stays_on_user_track():
    from pydub.generators import Sine

    audio = Sine(330).to_audio_segment(duration=4000)
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=2.0, end=3.0),
    ]
    extractor = AudioExtractor()
    user_audio, agent_audio, _, _ = extractor.extract_timeline_tracks(
        audio,
        segments,
        human_speaker="SPEAKER_01",
        agent_speaker="SPEAKER_00",
        padding_ms=0,
    )

    user = np.array(user_audio.get_array_of_samples(), dtype=np.int16)
    agent = np.array(agent_audio.get_array_of_samples(), dtype=np.int16)
    assert np.any(user[:500] != 0)
    assert np.all(agent[:500] == 0)


def test_partition_durations_sum_to_original():
    from pydub.generators import Sine

    audio = Sine(440).to_audio_segment(duration=10000)
    segments = [
        SpeakerSegment(speaker="SPEAKER_01", start=1.0, end=3.0),
        SpeakerSegment(speaker="SPEAKER_00", start=5.0, end=7.0),
    ]
    extractor = AudioExtractor()
    user_audio, agent_audio, _, _ = extractor.extract_partition_tracks(
        audio,
        segments,
        human_speaker="SPEAKER_01",
        agent_speaker="SPEAKER_00",
    )

    assert len(user_audio) + len(agent_audio) == len(audio)


def test_partition_silence_goes_to_user():
    from pydub.generators import Sine

    audio = Sine(220).to_audio_segment(duration=5000)
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=1.0, end=2.0),
    ]
    extractor = AudioExtractor()
    user_audio, agent_audio, _, _ = extractor.extract_partition_tracks(
        audio,
        segments,
        human_speaker="SPEAKER_01",
        agent_speaker="SPEAKER_00",
    )

    # 1s agent speech + 4s silence/user regions on user track
    assert len(agent_audio) == 1000
    assert len(user_audio) == 4000
    assert len(user_audio) + len(agent_audio) == len(audio)
