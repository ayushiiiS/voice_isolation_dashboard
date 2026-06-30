"""Build public URLs for processed outputs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def processed_dir() -> Path:
    path = Path(os.getenv("PROCESSED_DIR", "output/processed"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def api_base_url() -> str:
    return os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")


def persist_processed_outputs(work_path: Path, recording_id: str) -> Path:
    """Copy pipeline outputs to durable local storage."""
    dest = processed_dir() / recording_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for name in (
        "original.wav",
        "user_only.wav",
        "agent_only.wav",
        "diarization.json",
        "diarization.rttm",
    ):
        src = work_path / name
        if src.is_file():
            shutil.copy2(src, dest / name)

    return dest


def local_media_url(recording_id: str, filename: str) -> str:
    return f"{api_base_url()}/media/{recording_id}/{filename}"
