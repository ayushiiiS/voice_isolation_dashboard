"""Tests for direct audio file upload endpoint."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.auth.dependencies import get_current_user
from src.auth.jwt import create_access_token
from src.db.mongodb import get_db
from src.main import app


@pytest.fixture
def mock_user():
    return {"id": "507f1f77bcf86cd799439011", "email": "test@example.com"}


@pytest.fixture
def mock_db():
    db = MagicMock()

    async def insert_one(_doc):
        return MagicMock(inserted_id="abc")

    jobs = MagicMock()
    jobs.insert_one = AsyncMock(side_effect=insert_one)
    recordings = MagicMock()
    recordings.insert_many = AsyncMock(return_value=MagicMock(inserted_ids=["abc"]))
    db.jobs = jobs
    db.recordings = recordings
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
def sample_ogg(temp_dir: Path, sample_wav: Path) -> Path:
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(str(sample_wav))
    ogg_path = temp_dir / "697dfeca4213052ebb6750c4.ogg"
    audio.export(str(ogg_path), format="ogg")
    return ogg_path


def test_upload_ogg_file(client, auth_headers, sample_ogg: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    async def noop_process(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.api.upload_routes._process_job_background", noop_process)

    with sample_ogg.open("rb") as handle:
        response = client.post(
            "/upload/file",
            headers=auth_headers,
            files={"file": (sample_ogg.name, handle, "audio/ogg")},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["job_id"]
    assert data["total_recordings"] == 1


def test_upload_rejects_non_audio(client, auth_headers):
    response = client.post(
        "/upload/file",
        headers=auth_headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 422
