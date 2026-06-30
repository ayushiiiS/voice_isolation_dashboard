"""Tests for local recording path resolution."""

from pathlib import Path

import pytest

from src.utils.recording_url_resolver import (
    is_local_recording_path,
    local_recording_path,
    recording_display_name,
    resolve_recording_url,
)


def test_is_local_recording_path(sample_wav: Path):
    assert is_local_recording_path(str(sample_wav)) is True
    assert is_local_recording_path(f"file://{sample_wav}") is True
    assert is_local_recording_path("https://example.com/recording.ogg") is False


def test_resolve_local_recording_path(sample_wav: Path):
    resolved = resolve_recording_url(str(sample_wav))
    assert resolved == str(sample_wav.resolve())


def test_resolve_file_uri(sample_wav: Path):
    resolved = resolve_recording_url(f"file://{sample_wav}")
    assert resolved == str(sample_wav.resolve())


def test_recording_display_name_local(sample_wav: Path):
    assert recording_display_name(str(sample_wav)) == sample_wav.name


def test_local_recording_path_missing_file(temp_dir: Path):
    missing = temp_dir / "missing.ogg"
    with pytest.raises(FileNotFoundError):
        local_recording_path(str(missing))
