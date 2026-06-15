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


def test_identify_by_heuristics():
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=1.5),
        SpeakerSegment(speaker="SPEAKER_01", start=1.8, end=5.0),
        SpeakerSegment(speaker="SPEAKER_00", start=5.3, end=6.0),
        SpeakerSegment(speaker="SPEAKER_01", start=6.3, end=10.0),
        SpeakerSegment(speaker="SPEAKER_00", start=10.3, end=11.0),
        SpeakerSegment(speaker="SPEAKER_01", start=11.3, end=15.0),
    ]

    selector = SpeakerSelector()
    result = selector.identify(segments)

    assert result.agent_speaker in {"SPEAKER_00", "SPEAKER_01"}
    assert result.human_speaker != result.agent_speaker
    assert result.strategy == IdentificationStrategy.HEURISTICS
    assert 0.0 < result.confidence <= 1.0


def test_raises_on_single_speaker():
    segments = [SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=5.0)]

    selector = SpeakerSelector()
    with pytest.raises(ValueError, match="Expected 2 speakers"):
        selector.identify(segments)
