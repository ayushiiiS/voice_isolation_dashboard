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


def test_agent_led_dominant_talk_time():
    """Agent speaks more with longer segments; user has more short acks."""
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=1.0, end=1.3),
        SpeakerSegment(speaker="SPEAKER_01", start=1.3, end=6.0),
        SpeakerSegment(speaker="SPEAKER_00", start=7.0, end=7.4),
        SpeakerSegment(speaker="SPEAKER_01", start=8.0, end=14.0),
        SpeakerSegment(speaker="SPEAKER_00", start=15.0, end=15.5),
        SpeakerSegment(speaker="SPEAKER_01", start=16.0, end=22.0),
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


def test_short_agent_led_no_backchannel_not_swapped():
    """Short outbound call: agent dominates talk time without clear backchannels."""
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=0.5, end=3.2),
        SpeakerSegment(speaker="SPEAKER_00", start=4.0, end=6.5),
        SpeakerSegment(speaker="SPEAKER_00", start=7.0, end=9.8),
        SpeakerSegment(speaker="SPEAKER_00", start=10.5, end=13.0),
        SpeakerSegment(speaker="SPEAKER_00", start=14.0, end=16.5),
        SpeakerSegment(speaker="SPEAKER_00", start=17.0, end=19.5),
        SpeakerSegment(speaker="SPEAKER_00", start=20.0, end=22.5),
        SpeakerSegment(speaker="SPEAKER_00", start=23.0, end=25.0),
        SpeakerSegment(speaker="SPEAKER_00", start=26.0, end=28.5),
        SpeakerSegment(speaker="SPEAKER_00", start=29.0, end=31.5),
        SpeakerSegment(speaker="SPEAKER_00", start=32.0, end=34.0),
        SpeakerSegment(speaker="SPEAKER_00", start=35.0, end=37.5),
        SpeakerSegment(speaker="SPEAKER_00", start=38.0, end=40.0),
        SpeakerSegment(speaker="SPEAKER_00", start=41.0, end=43.0),
        SpeakerSegment(speaker="SPEAKER_00", start=44.0, end=46.5),
        SpeakerSegment(speaker="SPEAKER_01", start=48.0, end=49.2),
        SpeakerSegment(speaker="SPEAKER_01", start=50.0, end=51.0),
        SpeakerSegment(speaker="SPEAKER_01", start=52.0, end=53.5),
        SpeakerSegment(speaker="SPEAKER_01", start=54.5, end=55.5),
        SpeakerSegment(speaker="SPEAKER_01", start=56.5, end=58.0),
        SpeakerSegment(speaker="SPEAKER_01", start=59.0, end=60.0),
        SpeakerSegment(speaker="SPEAKER_01", start=61.0, end=62.5),
        SpeakerSegment(speaker="SPEAKER_01", start=63.5, end=64.5),
        SpeakerSegment(speaker="SPEAKER_01", start=65.5, end=67.0),
        SpeakerSegment(speaker="SPEAKER_01", start=68.0, end=69.0),
    ]

    selector = SpeakerSelector()
    result = selector.identify(segments)

    assert result.human_speaker == "SPEAKER_01"
    assert result.agent_speaker == "SPEAKER_00"
