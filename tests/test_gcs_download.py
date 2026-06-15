"""Tests for GCS download fallback behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.gcs_download import parse_gcs_location, try_download_gcs_source


def test_parse_gcs_https_url():
    url = "https://storage.googleapis.com/bluemachines-prod/path/recording.ogg"
    assert parse_gcs_location(url) == ("bluemachines-prod", "path/recording.ogg")


def test_signed_url_skips_gcs_api(tmp_path: Path):
    signed = (
        "https://storage.googleapis.com/bucket/obj.ogg"
        "?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Signature=abc"
    )
    dest = tmp_path / "out.ogg"
    with patch("src.utils.gcs_download.download_gcs_object") as mock_download:
        result = try_download_gcs_source(signed, dest)
    assert result is None
    mock_download.assert_not_called()


def test_unsigned_https_falls_back_to_http_on_api_403(tmp_path: Path):
    url = "https://storage.googleapis.com/bluemachines-prod/path/recording.ogg"
    dest = tmp_path / "out.ogg"
    with patch(
        "src.utils.gcs_download.download_gcs_object",
        side_effect=Exception("403 GET denied"),
    ) as mock_download:
        result = try_download_gcs_source(url, dest)
    assert result is None
    mock_download.assert_called_once()
