"""Resolve Blue Machines console links and other aliases to direct recording URLs."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

BLUEMACHINES_CONSOLE_HOSTS = frozenset(
    {"console.bluemachines.ai", "www.console.bluemachines.ai"}
)
DEFAULT_RECORDINGS_BUCKET = os.getenv("BLUEMACHINES_RECORDINGS_BUCKET", "bluemachines-prod")
DEFAULT_STORAGE_TIERS = tuple(
    tier.strip()
    for tier in os.getenv(
        "BLUEMACHINES_STORAGE_TIERS", "forever,one-month"
    ).split(",")
    if tier.strip()
)
RECORDING_BASENAMES = ("recording.ogg", "recording.wav", "recording.m4a", "recording.mp3")


def is_bluemachines_console_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.netloc.lower() in BLUEMACHINES_CONSOLE_HOSTS


def is_local_recording_path(path: str) -> bool:
    """Return True for server-local uploaded recordings (absolute path or file:// URI)."""
    cleaned = path.strip()
    if cleaned.startswith("file://"):
        return True
    candidate = Path(cleaned)
    if not candidate.is_absolute():
        return False
    ext = candidate.suffix.lower()
    return ext in (".ogg", ".wav", ".mp3", ".m4a", ".flac", ".aac", ".oga")


def local_recording_path(path: str) -> Path:
    """Resolve a local recording reference to an absolute filesystem path."""
    cleaned = path.strip()
    if cleaned.startswith("file://"):
        from urllib.request import url2pathname

        parsed = urlparse(cleaned)
        local = Path(url2pathname(parsed.path))
        if not local.is_absolute() and parsed.netloc:
            local = Path(f"/{parsed.netloc}{parsed.path}")
        local = local.resolve()
    else:
        local = Path(cleaned).resolve()

    if not local.exists():
        raise FileNotFoundError(f"Local recording not found: {path}")
    if local.suffix.lower() not in (
        ".ogg",
        ".wav",
        ".mp3",
        ".m4a",
        ".flac",
        ".aac",
        ".oga",
    ):
        raise ValueError(
            f"Unsupported local audio format: {local.suffix or '(none)'}. "
            "Use OGG, WAV, MP3, M4A, FLAC, or AAC."
        )
    return local


def is_direct_audio_url(url: str) -> bool:
    """Return True when URL already points at a downloadable audio object."""
    parsed = urlparse(url.strip())
    if parsed.scheme == "gs":
        path = parsed.path.lower()
        return any(path.endswith(ext) for ext in (".ogg", ".wav", ".mp3", ".m4a", ".flac", ".aac"))

    if parsed.scheme in ("http", "https"):
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if host in ("storage.googleapis.com", "storage.cloud.google.com"):
            return any(path.endswith(ext) for ext in (".ogg", ".wav", ".mp3", ".m4a", ".flac", ".aac"))
        return any(path.endswith(ext) for ext in (".ogg", ".wav", ".mp3", ".m4a", ".flac", ".aac"))

    return False


def _parse_console_params(url: str) -> tuple[str | None, str | None]:
    parsed = urlparse(url.strip())
    params = parse_qs(parsed.query)
    project_id = (params.get("projectId") or params.get("project_id") or [None])[0]
    conversation_id = (
        params.get("conversationId")
        or params.get("conversation_id")
        or params.get("interactionId")
        or params.get("interaction_id")
        or [None]
    )[0]
    return project_id, conversation_id


def _gcs_candidates(project_id: str, recording_id: str) -> list[str]:
    candidates: list[str] = []
    for tier in DEFAULT_STORAGE_TIERS:
        for basename in RECORDING_BASENAMES:
            candidates.append(f"{tier}/{project_id}/recording/{recording_id}/{basename}")
    return candidates


def _find_gcs_object(bucket: str, object_paths: list[str]) -> str | None:
    try:
        from google.cloud import storage

        from src.utils.gcs_auth import configure_adc_credentials, load_gcp_credentials

        configure_adc_credentials()
        credentials, project, _, _ = load_gcp_credentials()
        client = storage.Client(credentials=credentials, project=project)
        bucket_ref = client.bucket(bucket)
        for object_path in object_paths:
            blob = bucket_ref.blob(object_path)
            if blob.exists():
                logger.info("Resolved recording to gs://%s/%s", bucket, object_path)
                return f"gs://{bucket}/{object_path}"
    except Exception as exc:
        logger.warning("Could not probe GCS for recording paths: %s", exc)
    return None


def resolve_bluemachines_console_url(url: str) -> str:
    """
    Map a Blue Machines console interaction URL to a gs:// recording path.

    Example console URL:
      https://console.bluemachines.ai/dashboard/interactions?projectId=...&conversationId=...
    """
    project_id, conversation_id = _parse_console_params(url)
    if not conversation_id:
        raise ValueError(
            "Blue Machines console URL must include conversationId (or interactionId) "
            "in the query string."
        )
    if not project_id:
        project_id = os.getenv("BLUEMACHINES_DEFAULT_PROJECT_ID")
    if not project_id:
        raise ValueError(
            "Blue Machines console URL is missing projectId. "
            "Add projectId=... to the URL or set BLUEMACHINES_DEFAULT_PROJECT_ID in .env."
        )

    bucket = DEFAULT_RECORDINGS_BUCKET
    candidates = _gcs_candidates(project_id, conversation_id)
    resolved = _find_gcs_object(bucket, candidates)
    if resolved:
        return resolved

    # Fallback: most common path (caller may still fail if object missing / no access)
    fallback = candidates[0]
    logger.warning(
        "Could not verify GCS object exists; using best-guess path gs://%s/%s",
        bucket,
        fallback,
    )
    return f"gs://{bucket}/{fallback}"


def resolve_recording_url(url: str) -> str:
    """
    Normalize any supported recording reference to a direct gs://, https://, or local path.
    """
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Recording URL is empty")

    if is_bluemachines_console_url(cleaned):
        return resolve_bluemachines_console_url(cleaned)

    if is_local_recording_path(cleaned):
        return str(local_recording_path(cleaned))

    if is_direct_audio_url(cleaned):
        return cleaned

    parsed = urlparse(cleaned)
    if parsed.scheme in ("http", "https", "gs"):
        return cleaned

    raise ValueError(
        "Unsupported recording URL. Use a direct audio link (https://, gs://), "
        "an uploaded audio file, or a Blue Machines console interaction URL."
    )


def recording_display_name(url: str) -> str:
    """Human-readable name from URL."""
    if is_local_recording_path(url):
        try:
            return local_recording_path(url).name
        except (FileNotFoundError, ValueError):
            return Path(url).name or "recording.ogg"

    if is_bluemachines_console_url(url):
        _, conversation_id = _parse_console_params(url)
        if conversation_id:
            return f"recording_{conversation_id[-8]}.ogg"
    parsed = urlparse(url)
    name = parsed.path.rstrip("/").split("/")[-1]
    if name and name != "recording":
        return name
    match = re.search(r"/recording/([^/]+)/", parsed.path)
    if match:
        return f"recording_{match.group(1)[-8]}.ogg"
    return "recording.ogg"
