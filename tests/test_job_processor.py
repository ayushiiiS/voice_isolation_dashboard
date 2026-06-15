"""Tests for job processor helpers."""

from __future__ import annotations

import json
from pathlib import Path

from src.services.job_processor import JobProcessor, recording_filename


def test_recording_filename_from_gs_url():
    assert recording_filename("gs://my-bucket/path/to/recording.ogg") == "recording.ogg"


def test_recording_filename_from_https_url():
    assert recording_filename("https://storage.googleapis.com/b/recording.wav") == "recording.wav"


def test_load_diarization_static_method(tmp_path: Path):
    data = {
        "segments": [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.5}],
        "speakers": ["SPEAKER_00"],
        "duration": 1.5,
        "exclusive": False,
    }
    path = tmp_path / "diarization.json"
    path.write_text(json.dumps(data))

    result = JobProcessor._load_diarization(path)
    assert result.duration == 1.5
    assert result.speakers == ["SPEAKER_00"]
