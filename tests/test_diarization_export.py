"""Tests for diarization export utilities."""

import json
from pathlib import Path

from src.diarization.models import DiarizationResult, SpeakerSegment
from src.diarization.pyannote_service import PyannoteDiarizationService


def test_export_json_and_rttm(temp_dir: Path):
    segments = [
        SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=3.2),
        SpeakerSegment(speaker="SPEAKER_01", start=3.5, end=7.0),
    ]
    result = DiarizationResult(
        segments=segments,
        speakers=["SPEAKER_00", "SPEAKER_01"],
        duration=7.0,
        exclusive=True,
    )

    service = PyannoteDiarizationService(device="cpu")

    json_path = temp_dir / "diarization.json"
    rttm_path = temp_dir / "diarization.rttm"

    service.export_json(result, json_path)
    service.export_rttm(segments, rttm_path)

    assert json_path.exists()
    assert rttm_path.exists()

    with json_path.open() as f:
        data = json.load(f)

    assert len(data["segments"]) == 2
    assert data["segments"][0]["speaker"] == "SPEAKER_00"

    rttm_content = rttm_path.read_text()
    assert "SPEAKER_00" in rttm_content
    assert "SPEAKER_01" in rttm_content


def test_resolve_device_cpu():
    service = PyannoteDiarizationService(device="cpu")
    assert service.device == "cpu"


def test_annotation_to_segments_itertracks():
    class FakeTurn:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class FakeAnnotation:
        def itertracks(self, yield_label=True):
            yield FakeTurn(0.0, 2.0), None, "SPEAKER_00"
            yield FakeTurn(2.5, 5.0), None, "SPEAKER_01"

    segments = PyannoteDiarizationService._annotation_to_segments(FakeAnnotation())
    assert len(segments) == 2
    assert segments[0].speaker == "SPEAKER_00"
