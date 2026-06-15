"""Tests for Pydantic data models."""

import pytest
from pydantic import ValidationError

from src.diarization.models import (
    AgentTranscriptEntry,
    IsolateRequest,
    SpeakerSegment,
)


def test_speaker_segment_valid():
    seg = SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=3.2)
    assert seg.duration == pytest.approx(3.2)


def test_speaker_segment_invalid_end():
    with pytest.raises(ValidationError):
        SpeakerSegment(speaker="SPEAKER_00", start=5.0, end=3.0)


def test_isolate_request_defaults():
    req = IsolateRequest(audio_path="/tmp/test.wav")
    assert req.num_speakers == 2
    assert req.agent_transcript is None


def test_agent_transcript_entry_optional_timestamps():
    entry = AgentTranscriptEntry(text="Hello, how can I help?")
    assert entry.start is None
    assert entry.end is None
