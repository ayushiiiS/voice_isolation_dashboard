"""Audio loading, segment extraction, and human-only concatenation."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from pydub import AudioSegment

from src.diarization.models import SpeakerSegment
from src.utils.audio_validation import ensure_extension, validate_downloaded_audio
from src.utils.recording_url_resolver import resolve_recording_url

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}
# pyannote chunks audio at 48 kHz; OGG call recordings are often 44.1 kHz.
DIARIZATION_SAMPLE_RATE = 48000


class AudioExtractor:
    """Load audio and extract human-only segments."""

    def __init__(self, temp_dir: Optional[str] = None) -> None:
        self.temp_dir = Path(temp_dir or os.getenv("TEMP_DIR", tempfile.gettempdir()))
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def load_audio(self, audio_path: str) -> tuple[AudioSegment, Path, bool]:
        """
        Load audio from a local path or URL.

        Returns:
            Tuple of (AudioSegment, resolved local path, is_temporary_file).
        """
        resolved_source = resolve_recording_url(audio_path) if self._is_url(audio_path) else audio_path

        if self._is_url(resolved_source):
            local_path = self._download_audio(resolved_source)
            is_temp = True
        else:
            local_path = Path(resolved_source).resolve()
            if not local_path.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_path}")
            is_temp = False

        audio = self._decode_audio_file(local_path)
        return audio, local_path, is_temp

    def _decode_audio_file(self, local_path: Path) -> AudioSegment:
        """Decode audio with format detection and ffmpeg fallback."""
        fmt = validate_downloaded_audio(local_path)
        local_path = ensure_extension(local_path, fmt)

        logger.info("Loading audio from %s (format=%s)", local_path, fmt)
        try:
            return AudioSegment.from_file(str(local_path), format=fmt)
        except Exception as pydub_exc:
            logger.warning(
                "pydub decode failed for %s (%s); trying ffmpeg transcode",
                local_path,
                pydub_exc,
            )
            return self._transcode_via_ffmpeg(local_path, fmt)

    @staticmethod
    def _transcode_via_ffmpeg(source: Path, fmt: str) -> AudioSegment:
        """Transcode problematic sources to PCM WAV via ffmpeg."""
        dest = source.with_suffix(".normalized.wav")
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
        ]
        if fmt:
            cmd[4:4] = ["-f", fmt]  # insert after -loglevel error — fix command building

        # Rebuild command cleanly
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if fmt in {"ogg", "mp3", "m4a", "wav", "flac", "aac"}:
            cmd.extend(["-f", fmt])
        cmd.extend(["-i", str(source), "-ac", "1", "-ar", "44100", str(dest)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "ffmpeg is not installed. Install ffmpeg to decode call recordings."
            ) from exc

        if result.returncode != 0 or not dest.exists():
            stderr = (result.stderr or "").strip()
            raise ValueError(
                "Could not decode recording audio. "
                f"ffmpeg failed ({result.returncode}): {stderr or 'unknown error'}. "
                "Ensure the URL points to a valid OGG/WAV/MP3 recording."
            ) from None

        return AudioSegment.from_wav(str(dest))

    def prepare_for_diarization(self, audio: AudioSegment) -> tuple[Path, bool]:
        """
        Export mono PCM WAV at the sample rate expected by pyannote.

        OGG/WebRTC recordings often use 44.1 kHz, which causes pyannote chunk
        alignment errors when decoded directly from the source file.
        """
        normalized = audio.set_channels(1).set_frame_rate(DIARIZATION_SAMPLE_RATE)
        dest = self.temp_dir / f"normalized_{uuid.uuid4().hex}.wav"
        normalized.export(str(dest), format="wav")
        logger.info(
            "Prepared audio for diarization: %s (%d Hz mono)",
            dest,
            DIARIZATION_SAMPLE_RATE,
        )
        return dest, True

    def extract_speaker_segments(
        self,
        audio: AudioSegment,
        segments: list[SpeakerSegment],
        speaker_id: str,
    ) -> tuple[AudioSegment, list[SpeakerSegment]]:
        """Concatenate all segments for a single speaker in chronological order."""
        speaker_segments = sorted(
            [s for s in segments if s.speaker == speaker_id],
            key=lambda s: s.start,
        )

        if not speaker_segments:
            logger.warning("No segments found for speaker %s", speaker_id)
            return AudioSegment.silent(duration=0), speaker_segments

        combined = AudioSegment.empty()
        for seg in speaker_segments:
            start_ms = int(seg.start * 1000)
            end_ms = int(seg.end * 1000)
            combined += audio[start_ms:end_ms]

        logger.info(
            "Extracted %d segments for %s (%.1fs)",
            len(speaker_segments),
            speaker_id,
            len(combined) / 1000.0,
        )
        return combined, speaker_segments

    def extract_human_segments(
        self,
        audio: AudioSegment,
        segments: list[SpeakerSegment],
        human_speaker: str,
        agent_speaker: str,
    ) -> tuple[AudioSegment, list[SpeakerSegment], list[SpeakerSegment]]:
        """
        Filter segments and concatenate human speech in chronological order.

        Returns:
            Tuple of (concatenated human audio, human segments, agent segments).
        """
        human_segments = [s for s in segments if s.speaker == human_speaker]
        agent_segments = [s for s in segments if s.speaker == agent_speaker]
        human_segments.sort(key=lambda s: s.start)

        human_audio, _ = self.extract_speaker_segments(
            audio, human_segments, human_speaker
        )

        logger.info(
            "Extracted %d human segments (%.1fs), %d agent segments",
            len(human_segments),
            len(human_audio) / 1000.0,
            len(agent_segments),
        )

        return human_audio, human_segments, agent_segments

    def export_wav(self, audio: AudioSegment, output_path: Path) -> Path:
        """Export audio segment to WAV format."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        audio.export(str(output_path), format="wav")
        logger.info("Exported user-only audio to %s", output_path)
        return output_path

    @staticmethod
    def duration_seconds(audio: AudioSegment) -> float:
        return len(audio) / 1000.0

    @staticmethod
    def _is_url(path: str) -> bool:
        parsed = urlparse(path)
        return parsed.scheme in ("http", "https", "gs")

    def _download_audio(self, url: str) -> Path:
        logger.info("Downloading audio from URL: %s", url)

        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            ext = ".ogg"

        filename = f"download_{uuid.uuid4().hex}{ext}"
        dest = self.temp_dir / filename

        from src.utils.gcs_download import try_download_gcs_source

        gcs_path = try_download_gcs_source(url, dest)
        if gcs_path is not None:
            logger.info("Downloaded audio via GCS API to %s", gcs_path)
            fmt = validate_downloaded_audio(gcs_path)
            return ensure_extension(gcs_path, fmt)

        if parsed.scheme == "gs":
            raise FileNotFoundError(
                f"Could not download {url} via GCS. "
                "Ensure your account has storage.objects.get on the source bucket."
            )

        response = requests.get(url, stream=True, timeout=120, allow_redirects=True)
        response.raise_for_status()

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" in content_type or "application/json" in content_type:
            raise ValueError(
                "URL returned HTML/JSON instead of audio. "
                "Paste a direct recording link, gs:// path, or Blue Machines console URL "
                "with conversationId and projectId."
            )

        with dest.open("wb") as f:
            first_chunk = True
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                if first_chunk:
                    if looks_like_non_audio(chunk):
                        raise ValueError(
                            "Could not download recording: URL is not a direct audio file. "
                            "Use a Blue Machines console interaction link, gs:// path, or "
                            "storage.googleapis.com URL ending in .ogg/.wav."
                        )
                    first_chunk = False
                f.write(chunk)

        fmt = validate_downloaded_audio(dest)
        return ensure_extension(dest, fmt)

    def cleanup_temp(self, path: Path, is_temp: bool) -> None:
        if is_temp and path.exists():
            try:
                path.unlink()
                logger.debug("Removed temporary file: %s", path)
            except OSError as exc:
                logger.warning("Failed to remove temp file %s: %s", path, exc)


def looks_like_non_audio(chunk: bytes) -> bool:
    from src.utils.audio_validation import looks_like_html_or_json

    return looks_like_html_or_json(chunk)
