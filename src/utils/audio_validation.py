"""Validate and detect downloaded audio content."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIO_SIGNATURES: list[tuple[str, bytes]] = [
    ("ogg", b"OggS"),
    ("wav", b"RIFF"),
    ("mp3", b"ID3"),
    ("m4a", b"ftyp"),
    ("flac", b"fLaC"),
]

MIN_AUDIO_BYTES = 512


def sniff_audio_format(data: bytes) -> str | None:
    if len(data) < 4:
        return None
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"ID3"):
        return "mp3"
    if data.startswith(b"\xff\xfb") or data.startswith(b"\xff\xf3") or data.startswith(b"\xff\xf2"):
        return "mp3"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a"
    if data.startswith(b"fLaC"):
        return "flac"
    return None


def looks_like_html_or_json(data: bytes) -> bool:
    head = data[:256].lstrip()
    if not head:
        return True
    if head.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML")):
        return True
    if head.startswith((b"{", b"[")):
        return True
    if head.startswith(b"<?xml") or head.startswith(b"<Error"):
        return True
    return False


def validate_downloaded_audio(path: Path) -> str:
    """
    Ensure a downloaded file is audio, not HTML/JSON/error payload.

    Returns detected format string for pydub/ffmpeg.
    """
    size = path.stat().st_size
    data = path.read_bytes()[:4096]
    if looks_like_html_or_json(data):
        raise ValueError(
            "Downloaded content is not audio (received HTML or JSON). "
            "Use a direct recording URL, gs:// path, or Blue Machines console link "
            "with conversationId and projectId."
        )
    if size < MIN_AUDIO_BYTES:
        raise ValueError(
            f"Downloaded file is too small ({size} bytes) — likely not a valid recording."
        )

    detected = sniff_audio_format(data)
    if not detected:
        raise ValueError(
            "Downloaded file is not a recognized audio format. "
            "Expected OGG, WAV, MP3, or M4A."
        )

    logger.info("Detected audio format %s for %s (%d bytes)", detected, path.name, size)
    return detected


def ensure_extension(path: Path, fmt: str) -> Path:
    """Rename temp file to match detected format when extension was wrong."""
    ext = path.suffix.lower().lstrip(".")
    if ext == fmt or (ext in {"oga", "ogv"} and fmt == "ogg"):
        return path
    corrected = path.with_suffix(f".{fmt}")
    if corrected != path:
        path.rename(corrected)
        logger.info("Renamed download %s -> %s based on content sniffing", path.name, corrected.name)
    return corrected
