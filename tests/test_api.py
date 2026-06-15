"""Tests for FastAPI endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.diarization.models import (
    IdentificationStrategy,
    IsolateResponse,
    IsolationMetadata,
)
from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_isolate_response():
    return IsolateResponse(
        isolated_audio_path="/app/output/user_only.wav",
        diarization_json_path="/app/output/diarization.json",
        diarization_rttm_path="/app/output/diarization.rttm",
        human_speaker="SPEAKER_01",
        agent_speaker="SPEAKER_00",
        confidence=0.94,
        strategy=IdentificationStrategy.TRANSCRIPT_MATCH,
        duration_original=312.4,
        duration_user_only=148.7,
        metadata=IsolationMetadata(
            human_speaker="SPEAKER_01",
            agent_speaker="SPEAKER_00",
            confidence=0.94,
            strategy=IdentificationStrategy.TRANSCRIPT_MATCH,
            duration_original=312.4,
            duration_user_only=148.7,
            segment_count_human=12,
            segment_count_agent=14,
        ),
    )


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Voice Isolation" in response.json()["service"]


def test_health(client):
    with patch("src.api.routes.get_pipeline") as mock_pipeline:
        mock_svc = MagicMock()
        mock_svc.diarization_service.device = "cpu"
        mock_pipeline.return_value = mock_svc

        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


def test_isolate_endpoint(client, mock_isolate_response):
    with patch("src.api.routes._run_isolation", return_value=mock_isolate_response):
        response = client.post(
            "/isolate",
            json={
                "audio_path": "/recordings/call_001.wav",
                "agent_transcript": [
                    {"text": "Hello!", "start": 0.0, "end": 2.0},
                ],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["human_speaker"] == "SPEAKER_01"
    assert data["agent_speaker"] == "SPEAKER_00"
    assert data["confidence"] == 0.94
    assert data["isolated_audio_path"].endswith("user_only.wav")


def test_isolate_not_found(client):
    with patch("src.api.routes._run_isolation", side_effect=FileNotFoundError("missing")):
        response = client.post(
            "/isolate",
            json={"audio_path": "/missing.wav"},
        )

    assert response.status_code == 404


def test_batch_isolate(client, mock_isolate_response):
    with patch("src.api.routes._run_isolation", return_value=mock_isolate_response):
        response = client.post(
            "/isolate/batch",
            json={
                "items": [
                    {"audio_path": "/call_001.wav"},
                    {"audio_path": "/call_002.wav"},
                ]
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    assert len(data["results"]) == 2
