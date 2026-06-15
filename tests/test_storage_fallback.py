"""Tests for GCS upload fallback behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.gcs_auth import GcsPermissionError


@pytest.fixture
def audio_files(tmp_path: Path):
    user = tmp_path / "user_only.wav"
    agent = tmp_path / "agent_only.wav"
    diarization = tmp_path / "diarization.json"
    user.write_bytes(b"user")
    agent.write_bytes(b"agent")
    diarization.write_text("{}")
    return user, agent, diarization


def test_gcs_403_falls_back_to_local_and_keeps_completed_job_data(audio_files, tmp_path, monkeypatch):
    """403 upload must not fail processing; local URLs and storage metadata are returned."""
    user, agent, diarization = audio_files
    recording_id = "665544332211aabbccddeeff"
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))

    permission_error = GcsPermissionError(
        principal="ayushi.s.ext@bluemachines.ai",
        bucket="cadence-audio",
        object_path=f"user_audio/{recording_id}/user_only.wav",
        permission="storage.objects.create",
        credential_source="gcloud_cli_user",
        original=Exception("403 forbidden"),
    )

    mock_gcs = MagicMock()
    mock_gcs.identity.principal_email = "ayushi.s.ext@bluemachines.ai"
    mock_gcs.identity.bucket_name = "cadence-audio"
    mock_gcs.identity.credential_source = "gcloud_cli_user"
    mock_gcs.upload_object.side_effect = permission_error

    with patch("src.services.storage_handler.GcsStorageClient.from_adc", return_value=mock_gcs):
        from src.services.storage_handler import upload_outputs_with_fallback

        result = upload_outputs_with_fallback(
            recording_id=recording_id,
            user_path=user,
            agent_path=agent,
            diarization_path=diarization,
        )

    assert result.upload_status == "failed"
    assert result.storage_type == "local"
    assert result.storage_uri.endswith(recording_id)
    assert result.user_audio_url == f"http://localhost:8000/media/{recording_id}/user_only.wav"
    assert result.agent_audio_url == f"http://localhost:8000/media/{recording_id}/agent_only.wav"
    assert "storage.objects.create" in (result.gcs_error or "")
    assert result.gcs_principal == "ayushi.s.ext@bluemachines.ai"
    assert result.gcs_bucket == "cadence-audio"

    payload = result.to_dict()
    assert payload["upload_status"] == "failed"
    assert payload["storage_type"] == "local"


def test_gcs_upload_success_without_signing_uses_local_playback_urls(audio_files, tmp_path, monkeypatch):
    """When upload succeeds but user creds cannot sign URLs, job still completes as gcs + local playback."""
    user, agent, diarization = audio_files
    recording_id = "665544332211aabbccddeeff"
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))

    mock_gcs = MagicMock()
    mock_gcs.identity.principal_email = "ayushi.s.ext@bluemachines.ai"
    mock_gcs.identity.bucket_name = "cadence-audio"
    mock_gcs.identity.credential_source = "gcloud_cli_user"
    mock_gcs.upload_object.side_effect = [
        "gs://cadence-audio/user_audio/x/user_only.wav",
        "gs://cadence-audio/agent_audio/x/agent_only.wav",
        "gs://cadence-audio/reports/x/diarization.json",
    ]
    mock_gcs.try_generate_signed_url.return_value = None
    mock_gcs.resolve_access_url.side_effect = lambda object_path, gs_uri, **kwargs: kwargs.get(
        "local_fallback", gs_uri
    )

    with patch("src.services.storage_handler.GcsStorageClient.from_adc", return_value=mock_gcs):
        from src.services.storage_handler import upload_outputs_with_fallback

        result = upload_outputs_with_fallback(
            recording_id=recording_id,
            user_path=user,
            agent_path=agent,
            diarization_path=diarization,
        )

    assert result.upload_status == "success"
    assert result.storage_type == "gcs"
    assert result.user_audio_url.startswith("http://localhost:8000/media/")
    assert result.storage_uri.startswith("gs://cadence-audio/")
