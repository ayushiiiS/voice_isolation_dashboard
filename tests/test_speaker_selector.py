"""Tests for speaker identification strategies."""

import pytest

from src.diarization.models import AgentTranscriptEntry, IdentificationStrategy, SpeakerSegment
from src.isolation.speaker_selector import SpeakerSelector


def test_identify_by_transcript_timestamps():
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=3.0),
        SpeakerSegment(speaker="SPEAKER_01", start=3.2, end=6.0),
        SpeakerSegment(speaker="SPEAKER_00", start=6.2, end=9.0),
        SpeakerSegment(speaker="SPEAKER_01", start=9.2, end=12.0),
    ]
    transcript = [
        AgentTranscriptEntry(text="Agent greeting", start=0.0, end=3.0),
        AgentTranscriptEntry(text="Agent response", start=6.2, end=9.0),
    ]

    selector = SpeakerSelector()
    result = selector.identify(segments, agent_transcript=transcript)

    assert result.agent_speaker == "SPEAKER_00"
    assert result.human_speaker == "SPEAKER_01"
    assert result.strategy == IdentificationStrategy.TRANSCRIPT_MATCH
    assert result.confidence >= 0.6


def test_agent_monologue_user_backchannels():
    """Agent long replies + user short acks (common Blue Machines call pattern)."""
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=1.0, end=1.2),
        SpeakerSegment(speaker="SPEAKER_01", start=1.2, end=4.6),
        SpeakerSegment(speaker="SPEAKER_00", start=5.8, end=6.4),
        SpeakerSegment(speaker="SPEAKER_00", start=6.9, end=7.9),
        SpeakerSegment(speaker="SPEAKER_01", start=13.9, end=18.6),
        SpeakerSegment(speaker="SPEAKER_01", start=22.6, end=24.8),
        SpeakerSegment(speaker="SPEAKER_00", start=27.1, end=27.4),
        SpeakerSegment(speaker="SPEAKER_01", start=29.7, end=31.9),
        SpeakerSegment(speaker="SPEAKER_00", start=35.3, end=35.8),
        SpeakerSegment(speaker="SPEAKER_01", start=40.7, end=43.6),
    ]

    selector = SpeakerSelector()
    result = selector.identify(segments)

    assert result.human_speaker == "SPEAKER_00"
    assert result.agent_speaker == "SPEAKER_01"
    assert result.strategy == IdentificationStrategy.HEURISTICS


def test_user_speaks_first_longer_utterances_not_swapped():
    """User-led inbound call: user speaks first with longer turns."""
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=8.0),
        SpeakerSegment(speaker="SPEAKER_01", start=8.3, end=10.0),
        SpeakerSegment(speaker="SPEAKER_00", start=10.5, end=18.0),
        SpeakerSegment(speaker="SPEAKER_01", start=18.3, end=20.0),
        SpeakerSegment(speaker="SPEAKER_00", start=20.5, end=26.0),
        SpeakerSegment(speaker="SPEAKER_01", start=26.3, end=28.0),
    ]

    selector = SpeakerSelector()
    result = selector.identify(segments)

    assert result.human_speaker == "SPEAKER_00"
    assert result.agent_speaker == "SPEAKER_01"


def test_identify_from_real_diarization_fixture():
    """Regression test using stats from a real misclassified recording."""
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=1.077, end=1.246),
        SpeakerSegment(speaker="SPEAKER_01", start=1.246, end=4.621),
        SpeakerSegment(speaker="SPEAKER_00", start=5.802, end=6.393),
        SpeakerSegment(speaker="SPEAKER_00", start=6.916, end=7.928),
        SpeakerSegment(speaker="SPEAKER_00", start=9.008, end=11.202),
        SpeakerSegment(speaker="SPEAKER_01", start=13.953, end=14.594),
        SpeakerSegment(speaker="SPEAKER_01", start=14.830, end=18.661),
        SpeakerSegment(speaker="SPEAKER_01", start=18.965, end=20.534),
        SpeakerSegment(speaker="SPEAKER_01", start=22.643, end=24.888),
        SpeakerSegment(speaker="SPEAKER_00", start=27.149, end=27.453),
        SpeakerSegment(speaker="SPEAKER_01", start=29.782, end=31.975),
        SpeakerSegment(speaker="SPEAKER_01", start=40.784, end=43.619),
        SpeakerSegment(speaker="SPEAKER_01", start=48.547, end=52.462),
        SpeakerSegment(speaker="SPEAKER_01", start=61.000, end=63.481),
        SpeakerSegment(speaker="SPEAKER_01", start=74.838, end=76.272),
        SpeakerSegment(speaker="SPEAKER_01", start=88.507, end=89.992),
        SpeakerSegment(speaker="SPEAKER_01", start=101.669, end=104.572),
    ]

    selector = SpeakerSelector()
    result = selector.identify(segments)

    assert result.human_speaker == "SPEAKER_00"
    assert result.agent_speaker == "SPEAKER_01"


def test_raises_on_single_speaker():
    segments = [SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=5.0)]

    selector = SpeakerSelector()
    with pytest.raises(ValueError, match="Expected 2 speakers"):
        selector.identify(segments)
