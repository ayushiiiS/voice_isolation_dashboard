"""Tests for recording URL resolution and audio validation."""

from __future__ import annotations

import pytest

from src.utils.audio_validation import (
    looks_like_html_or_json,
    sniff_audio_format,
    validate_downloaded_audio,
)
from src.utils.recording_url_resolver import (
    is_bluemachines_console_url,
    is_direct_audio_url,
    resolve_bluemachines_console_url,
    resolve_recording_url,
)


CONSOLE_URL = (
    "https://console.bluemachines.ai/dashboard/interactions"
    "?agentIds=69ca381ab3cb207f1ab618b8"
    "&projectId=69ca371583e48a074837c140"
    "&organizationId=69d9d7b1e4640e713af81b4e"
    "&profile=69ca381ab3cb207f1ab618b9"
    "&page=836"
    "&conversationId=69d330765337f443ba7a1445"
)


def test_is_bluemachines_console_url():
    assert is_bluemachines_console_url(CONSOLE_URL)
    assert not is_bluemachines_console_url("https://storage.googleapis.com/x/recording.ogg")


def test_is_direct_audio_url():
    assert is_direct_audio_url("gs://bluemachines-prod/path/recording.ogg")
    assert is_direct_audio_url(
        "https://storage.googleapis.com/bluemachines-prod/path/recording.ogg"
    )
    assert not is_direct_audio_url(CONSOLE_URL)


def test_resolve_bluemachines_console_url_builds_gcs_path(monkeypatch):
    monkeypatch.setattr(
        "src.utils.recording_url_resolver._find_gcs_object",
        lambda bucket, paths: f"gs://{bucket}/{paths[0]}",
    )
    resolved = resolve_bluemachines_console_url(CONSOLE_URL)
    assert resolved.startswith("gs://bluemachines-prod/")
    assert "69ca371583e48a074837c140" in resolved
    assert "69d330765337f443ba7a1445" in resolved
    assert resolved.endswith("recording.ogg")


def test_resolve_recording_url_passes_through_gs():
    url = "gs://bluemachines-prod/forever/p/recording/r/recording.ogg"
    assert resolve_recording_url(url) == url


def test_resolve_recording_url_console(monkeypatch):
    monkeypatch.setattr(
        "src.utils.recording_url_resolver.resolve_bluemachines_console_url",
        lambda url: "gs://bluemachines-prod/forever/p/recording/c/recording.ogg",
    )
    assert resolve_recording_url(CONSOLE_URL).startswith("gs://")


def test_sniff_ogg():
    assert sniff_audio_format(b"OggS\x00" + b"\x00" * 100) == "ogg"


def test_rejects_html(tmp_path):
    path = tmp_path / "bad.wav"
    path.write_text("<html><body>login</body></html>")
    with pytest.raises(ValueError, match="not audio"):
        validate_downloaded_audio(path)


def test_rejects_html_bytes():
    assert looks_like_html_or_json(b"<!DOCTYPE html>")
