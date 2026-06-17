"""Integration tests for STT REST and WebSocket endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.auth.dependencies import get_current_user
from src.auth.jwt import create_access_token
from src.db.mongodb import get_db
from src.main import app


@pytest.fixture(autouse=True)
def mock_lifecycle_db(monkeypatch):
    mock_db = MagicMock()

    async def fake_connect():
        return mock_db

    async def fake_close():
        return None

    async def fake_get_db():
        return mock_db

    monkeypatch.setattr("src.main.connect_db", fake_connect)
    monkeypatch.setattr("src.main.close_db", fake_close)
    monkeypatch.setattr("src.db.mongodb.connect_db", fake_connect)
    monkeypatch.setattr("src.db.mongodb.close_db", fake_close)
    monkeypatch.setattr("src.db.mongodb.get_db", fake_get_db)
    monkeypatch.setattr("src.db.mongodb._db", mock_db)


@pytest.fixture
def mock_user():
    return {"id": "507f1f77bcf86cd799439011", "email": "test@example.com"}


@pytest.fixture
def mock_db():
    db = MagicMock()

    async def insert_one(doc):
        return MagicMock(inserted_id="abc")

    col = MagicMock()
    col.insert_one = AsyncMock(side_effect=insert_one)
    col.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
    db.stt_sessions = col
    db.recordings = MagicMock()
    return db


@pytest.fixture
def client(mock_user, mock_db):
    async def override_user():
        return mock_user

    async def override_db():
        return mock_db

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    token = create_access_token("507f1f77bcf86cd799439011")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def recording_id():
    from bson import ObjectId

    return str(ObjectId())


@pytest.fixture
def mock_recording(mock_user, recording_id):
    from bson import ObjectId

    return {
        "_id": ObjectId(recording_id),
        "user_id": mock_user["id"],
        "status": "completed",
        "user_audio_url": "http://localhost:8000/media/test/user_only.wav",
        "file_name": "call_001.wav",
    }


def _patch_recording_lookup(mock_db, recording):
    mock_db.recordings.find_one = AsyncMock(return_value=recording)
    return patch("src.api.stt_routes.col_recordings", return_value=mock_db.recordings)


def test_list_providers_requires_auth(mock_lifecycle_db):
    app.dependency_overrides.clear()
    with TestClient(app) as unauth_client:
        response = unauth_client.get("/stt/providers")
    assert response.status_code == 401


def test_list_providers(client, auth_headers):
    response = client.get("/stt/providers", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["providers"]) == 3
    ids = {p["id"] for p in data["providers"]}
    assert ids == {"deepgram", "azure", "sarvam"}


def test_create_session_requires_recording_id(client, auth_headers):
    response = client.post("/stt/sessions", headers=auth_headers, json={})
    assert response.status_code == 422


def test_create_session_with_recording(client, auth_headers, mock_db, mock_recording, recording_id):
    with _patch_recording_lookup(mock_db, mock_recording):
        response = client.post(
            "/stt/sessions",
            headers=auth_headers,
            json={"recording_id": recording_id},
        )

    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body


def test_create_session_recording_missing_audio(client, auth_headers, mock_user, recording_id):
    from bson import ObjectId

    async def find_one(query):
        return {
            "_id": ObjectId(recording_id),
            "user_id": mock_user["id"],
            "status": "completed",
            "user_audio_url": None,
        }

    with patch("src.api.stt_routes.col_recordings") as col_mock:
        col_mock.return_value.find_one = find_one
        response = client.post(
            "/stt/sessions",
            headers=auth_headers,
            json={"recording_id": recording_id},
        )

    assert response.status_code == 400
    assert "Isolated user audio" in response.json()["detail"]


def test_websocket_streaming(client, auth_headers, mock_db, mock_recording, recording_id):
    from src.stt.audio_quality import AudioQualityReport
    from src.stt.audio_source import AudioSourceDecision
    from src.stt.language_detection import LanguageCandidate, LanguageDetectionResult

    token = create_access_token("507f1f77bcf86cd799439011")
    with _patch_recording_lookup(mock_db, mock_recording):
        create = client.post(
            "/stt/sessions",
            headers=auth_headers,
            json={"recording_id": recording_id},
        )
    session_id = create.json()["session_id"]

    quality = AudioQualityReport(
        score=82.0,
        sample_rate=16000,
        channels=1,
        sample_width_bytes=2,
        duration_seconds=12.0,
        clipping_ratio=0.0,
        silence_ratio=0.2,
        snr_db=18.0,
        peak_dbfs=-6.0,
        rms_dbfs=-24.0,
        source_label="isolated_user_audio",
    )
    source_decision = AudioSourceDecision(
        url=mock_recording["user_audio_url"],
        source_type="isolated_user_audio",
        isolated_quality=quality,
        original_quality=None,
        warnings=[],
    )
    detection = LanguageDetectionResult(
        language="hi-IN",
        language_code="hi",
        confidence=0.9,
        method="whisper",
        language_mode="fixed",
        candidates=[LanguageCandidate(language="hi-IN", language_code="hi", confidence=0.9)],
        language_hints=["hi-IN"],
    )

    mock_db.stt_accuracy_metrics = MagicMock()
    mock_db.stt_accuracy_metrics.insert_many = AsyncMock()

    with patch("src.api.stt_routes.feed_isolated_user_audio", new=AsyncMock()):
        with patch("src.api.stt_routes.resolve_stt_audio_source", return_value=source_decision):
            with patch("src.api.stt_routes.detect_language_from_audio_url", return_value=detection):
                with client.websocket_connect(f"/stt/ws/{session_id}?token={token}") as ws:
                    seen_snapshot = False
                    for _ in range(8):
                        msg = ws.receive_json()
                        if msg["type"] == "language_detected":
                            assert msg["data"]["language"] == "hi-IN"
                        if msg["type"] == "snapshot":
                            seen_snapshot = True
                            assert msg["data"]["language"] == "hi-IN"
                            break
                    assert seen_snapshot
                    ws.send_json({"type": "stop"})


def test_update_selection_rest(client, auth_headers, mock_db, mock_recording, recording_id):
    with _patch_recording_lookup(mock_db, mock_recording):
        create = client.post(
            "/stt/sessions",
            headers=auth_headers,
            json={"recording_id": recording_id},
        )
    session_id = create.json()["session_id"]

    response = client.patch(
        f"/stt/sessions/{session_id}/selection",
        headers=auth_headers,
        json={"selection_mode": "manual", "manual_provider": "deepgram"},
    )
    assert response.status_code == 200
    assert response.json()["selection_mode"] == "manual"
