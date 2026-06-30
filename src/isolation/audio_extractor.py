"""Audio loading, segment extraction, and human-only concatenation."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

import numpy as np
import requests
from pydub import AudioSegment

from src.diarization.models import SpeakerSegment
from src.utils.audio_validation import ensure_extension, validate_downloaded_audio
from src.utils.recording_url_resolver import resolve_recording_url

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}
# pyannote chunks audio at 48 kHz; OGG call recordings are often 44.1 kHz.
DIARIZATION_SAMPLE_RATE = 48000
# Compressed formats decode faster and more reliably via ffmpeg than pydub.
FFMPEG_DECODE_FORMATS = {"ogg", "mp3", "m4a", "aac", "flac", "opus"}

IsolationMode = Literal["timeline", "partition", "compressed"]


def isolation_mode() -> IsolationMode:
    """
    timeline = full-length tracks; silence where the other speaker talks;
               timestamps align with the original recording.
    partition = chronological split; user duration + agent duration == original.
    compressed = speech-only clips with gaps removed (legacy).
    """
    mode = os.getenv("ISOLATION_MODE", "timeline").strip().lower()
    if mode in {"timeline", "partition", "compressed"}:
        return mode  # type: ignore[return-value]
    logger.warning("Unknown ISOLATION_MODE=%s; using timeline", mode)
    return "timeline"


def _segment_padding_ms() -> int:
    return int(os.getenv("ISOLATION_SEGMENT_PADDING_MS", "120"))


def _segment_merge_gap_ms() -> int:
    return int(os.getenv("ISOLATION_MERGE_GAP_MS", "250"))


def _segment_crossfade_ms() -> int:
    return int(os.getenv("ISOLATION_CROSSFADE_MS", "10"))


def _min_segment_ms() -> int:
    return int(os.getenv("ISOLATION_MIN_SEGMENT_MS", "120"))


def filter_micro_segments(
    segments: list[SpeakerSegment],
    *,
    min_duration_ms: int | None = None,
) -> list[SpeakerSegment]:
    """Drop diarization fragments too short to be real speech."""
    threshold = (min_duration_ms if min_duration_ms is not None else _min_segment_ms()) / 1000.0
    kept = [s for s in segments if s.duration >= threshold]
    dropped = len(segments) - len(kept)
    if dropped:
        logger.info("Filtered %d micro-segments (< %.0f ms)", dropped, threshold * 1000)
    return kept


def merge_adjacent_segments(
    segments: list[SpeakerSegment],
    *,
    max_gap_seconds: float | None = None,
) -> list[SpeakerSegment]:
    """Merge same-speaker segments separated by brief pauses."""
    if not segments:
        return []

    gap = (
        max_gap_seconds
        if max_gap_seconds is not None
        else _segment_merge_gap_ms() / 1000.0
    )
    ordered = sorted(segments, key=lambda s: (s.start, s.end))
    merged: list[SpeakerSegment] = [ordered[0]]

    for segment in ordered[1:]:
        previous = merged[-1]
        if segment.speaker == previous.speaker and segment.start - previous.end <= gap:
            merged[-1] = SpeakerSegment(
                speaker=previous.speaker,
                start=previous.start,
                end=max(previous.end, segment.end),
            )
        else:
            merged.append(segment)

    return merged


def _concat_parts(parts: list[AudioSegment]) -> AudioSegment:
    combined = AudioSegment.empty()
    for part in parts:
        if len(part) > 0:
            combined += part
    return combined


def _ms_to_sample(ms: int, frame_rate: int) -> int:
    return int(ms * frame_rate / 1000)


def _mono_int16_samples(audio: AudioSegment) -> tuple[np.ndarray, int]:
    mono = audio.set_channels(1).set_sample_width(2)
    return np.array(mono.get_array_of_samples(), dtype=np.int16), mono.frame_rate


def _samples_to_audio(samples: np.ndarray, frame_rate: int) -> AudioSegment:
    clipped = np.clip(samples, -32768, 32767).astype(np.int16)
    return AudioSegment(
        data=clipped.tobytes(),
        sample_width=2,
        frame_rate=frame_rate,
        channels=1,
    )


def _segment_sample_range(
    seg: SpeakerSegment,
    *,
    frame_rate: int,
    audio_duration_ms: int,
    padding_ms: int,
) -> tuple[int, int]:
    start_ms = max(0, int(seg.start * 1000) - padding_ms)
    end_ms = min(audio_duration_ms, int(seg.end * 1000) + padding_ms)
    return _ms_to_sample(start_ms, frame_rate), _ms_to_sample(end_ms, frame_rate)


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
        if fmt in FFMPEG_DECODE_FORMATS:
            return self._transcode_via_ffmpeg(
                local_path,
                fmt,
                sample_rate=None,
                channels=None,
            )
        try:
            return AudioSegment.from_file(str(local_path), format=fmt)
        except Exception as pydub_exc:
            logger.warning(
                "pydub decode failed for %s (%s); trying ffmpeg transcode",
                local_path,
                pydub_exc,
            )
            return self._transcode_via_ffmpeg(local_path, fmt)

    def _transcode_via_ffmpeg(
        self,
        source: Path,
        fmt: str,
        *,
        sample_rate: int | None = 44100,
        channels: int | None = 1,
    ) -> AudioSegment:
        """Transcode sources to PCM WAV via ffmpeg."""
        dest = self.temp_dir / f"decoded_{uuid.uuid4().hex}.wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if fmt in FFMPEG_DECODE_FORMATS or fmt == "wav":
            cmd.extend(["-f", fmt])
        cmd.extend(["-i", str(source)])
        if sample_rate is not None:
            cmd.extend(["-ar", str(sample_rate)])
        if channels is not None:
            cmd.extend(["-ac", str(channels)])
        cmd.append(str(dest))

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
        if (
            audio.frame_rate == DIARIZATION_SAMPLE_RATE
            and audio.channels == 1
        ):
            dest = self.temp_dir / f"normalized_{uuid.uuid4().hex}.wav"
            audio.export(str(dest), format="wav")
            logger.info(
                "Prepared audio for diarization (already %d Hz mono): %s",
                DIARIZATION_SAMPLE_RATE,
                dest,
            )
            return dest, True

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
        *,
        padding_ms: int | None = None,
    ) -> tuple[AudioSegment, list[SpeakerSegment]]:
        """Concatenate all segments for a single speaker in chronological order."""
        pad = _segment_padding_ms() if padding_ms is None else padding_ms
        speaker_segments = merge_adjacent_segments(
            [s for s in segments if s.speaker == speaker_id]
        )
        speaker_segments.sort(key=lambda s: s.start)

        if not speaker_segments:
            logger.warning("No segments found for speaker %s", speaker_id)
            return AudioSegment.silent(duration=0), speaker_segments

        audio_duration_ms = len(audio)
        crossfade = _segment_crossfade_ms()
        combined = AudioSegment.empty()
        for seg in speaker_segments:
            start_ms = max(0, int(seg.start * 1000) - pad)
            end_ms = min(audio_duration_ms, int(seg.end * 1000) + pad)
            if end_ms <= start_ms:
                continue
            chunk = audio[start_ms:end_ms]
            if len(combined) == 0:
                combined = chunk
                continue
            fade = min(crossfade, len(combined) // 2, len(chunk) // 2)
            combined = combined.append(chunk, crossfade=fade) if fade > 0 else combined + chunk

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
        human_audio, human_segments = self.extract_speaker_segments(
            audio,
            segments,
            human_speaker,
        )
        agent_segments = merge_adjacent_segments(
            [s for s in segments if s.speaker == agent_speaker]
        )

        logger.info(
            "Extracted %d human segments (%.1fs), %d agent segments",
            len(human_segments),
            len(human_audio) / 1000.0,
            len(agent_segments),
        )

        return human_audio, human_segments, agent_segments

    def extract_partition_tracks(
        self,
        audio: AudioSegment,
        segments: list[SpeakerSegment],
        human_speaker: str,
        agent_speaker: str,
    ) -> tuple[AudioSegment, AudioSegment, list[SpeakerSegment], list[SpeakerSegment]]:
        """
        Partition the original recording into user and agent streams.

        Walks the call chronologically: silence and user speech go to the user
        track; agent speech goes to the agent track. No audio is dropped, so
        len(user) + len(agent) == len(original).
        """
        audio_duration_ms = len(audio)
        human_segments = merge_adjacent_segments(
            [s for s in segments if s.speaker == human_speaker]
        )
        agent_segments = merge_adjacent_segments(
            [s for s in segments if s.speaker == agent_speaker]
        )

        labeled = sorted(
            [s for s in segments if s.speaker in {human_speaker, agent_speaker}],
            key=lambda s: (s.start, s.end),
        )

        user_parts: list[AudioSegment] = []
        agent_parts: list[AudioSegment] = []
        cursor_ms = 0

        for seg in labeled:
            start_ms = max(0, int(seg.start * 1000))
            end_ms = min(audio_duration_ms, int(seg.end * 1000))
            if end_ms <= start_ms:
                continue
            if end_ms <= cursor_ms:
                continue
            start_ms = max(start_ms, cursor_ms)

            if start_ms > cursor_ms:
                user_parts.append(audio[cursor_ms:start_ms])

            chunk = audio[start_ms:end_ms]
            if seg.speaker == human_speaker:
                user_parts.append(chunk)
            else:
                agent_parts.append(chunk)

            cursor_ms = max(cursor_ms, end_ms)

        if cursor_ms < audio_duration_ms:
            user_parts.append(audio[cursor_ms:audio_duration_ms])

        user_audio = _concat_parts(user_parts)
        agent_audio = _concat_parts(agent_parts)

        total_ms = len(user_audio) + len(agent_audio)
        if abs(total_ms - audio_duration_ms) > 1:
            logger.warning(
                "Partition duration mismatch: user=%dms + agent=%dms != original=%dms",
                len(user_audio),
                len(agent_audio),
                audio_duration_ms,
            )
        else:
            logger.info(
                "Partition tracks: user=%.1fs + agent=%.1fs = original=%.1fs",
                len(user_audio) / 1000.0,
                len(agent_audio) / 1000.0,
                audio_duration_ms / 1000.0,
            )

        return user_audio, agent_audio, human_segments, agent_segments

    def extract_timeline_tracks(
        self,
        audio: AudioSegment,
        segments: list[SpeakerSegment],
        human_speaker: str,
        agent_speaker: str,
        *,
        padding_ms: int | None = None,
    ) -> tuple[AudioSegment, AudioSegment, list[SpeakerSegment], list[SpeakerSegment]]:
        """
        Build full-length user/agent tracks aligned to the original timeline.

        - Same duration as the original (word timestamps stay valid).
        - User track: user speech + silence/unlabeled; silent during agent speech.
        - Agent track: agent speech only; silent elsewhere.
        """
        pad = _segment_padding_ms() if padding_ms is None else padding_ms
        human_segments = merge_adjacent_segments(
            [s for s in segments if s.speaker == human_speaker]
        )
        agent_segments = merge_adjacent_segments(
            [s for s in segments if s.speaker == agent_speaker]
        )

        mono, frame_rate = _mono_int16_samples(audio)
        n_samples = len(mono)
        audio_duration_ms = len(audio)

        # Default: silence and unlabeled regions belong on the user track.
        user_samples = mono.copy()
        agent_samples = np.zeros(n_samples, dtype=np.int16)

        for seg in segments:
            if seg.speaker not in {human_speaker, agent_speaker}:
                continue
            start_idx, end_idx = _segment_sample_range(
                seg,
                frame_rate=frame_rate,
                audio_duration_ms=audio_duration_ms,
                padding_ms=pad,
            )
            if end_idx <= start_idx:
                continue
            if seg.speaker == human_speaker:
                user_samples[start_idx:end_idx] = mono[start_idx:end_idx]
                agent_samples[start_idx:end_idx] = 0
            else:
                user_samples[start_idx:end_idx] = 0
                agent_samples[start_idx:end_idx] = mono[start_idx:end_idx]

        user_audio = _samples_to_audio(user_samples, frame_rate)
        agent_audio = _samples_to_audio(agent_samples, frame_rate)

        if abs(len(user_audio) - audio_duration_ms) > 2:
            logger.warning(
                "Timeline user track length %dms != original %dms",
                len(user_audio),
                audio_duration_ms,
            )

        logger.info(
            "Timeline tracks: user=%.1fs agent=%.1fs original=%.1fs (aligned)",
            len(user_audio) / 1000.0,
            len(agent_audio) / 1000.0,
            audio_duration_ms / 1000.0,
        )

        return user_audio, agent_audio, human_segments, agent_segments

    def extract_isolated_tracks(
        self,
        audio: AudioSegment,
        segments: list[SpeakerSegment],
        human_speaker: str,
        agent_speaker: str,
    ) -> tuple[AudioSegment, AudioSegment, list[SpeakerSegment], list[SpeakerSegment]]:
        """Extract user/agent audio using the configured isolation mode."""
        mode = isolation_mode()
        if mode == "timeline":
            return self.extract_timeline_tracks(
                audio,
                segments,
                human_speaker,
                agent_speaker,
            )
        if mode == "partition":
            return self.extract_partition_tracks(
                audio,
                segments,
                human_speaker,
                agent_speaker,
            )

        human_audio, human_segments, agent_segments = self.extract_human_segments(
            audio,
            segments,
            human_speaker,
            agent_speaker,
        )
        agent_audio, _ = self.extract_speaker_segments(
            audio,
            segments,
            agent_speaker,
        )
        return human_audio, agent_audio, human_segments, agent_segments

    def export_wav(self, audio: AudioSegment, output_path: Path) -> Path:
        """Export audio segment to high-quality mono WAV for playback."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        playback = audio.set_channels(1).set_sample_width(2)
        playback.export(str(output_path), format="wav")
        logger.info("Exported audio to %s (%d Hz mono)", output_path, playback.frame_rate)
        return output_path

    def export_playback_wav(self, audio: AudioSegment, output_path: Path) -> Path:
        """Export mixed audio preserving native sample rate and channel layout."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        playback = audio.set_sample_width(2)
        playback.export(str(output_path), format="wav")
        logger.info(
            "Exported playback audio to %s (%d Hz, %d ch)",
            output_path,
            playback.frame_rate,
            playback.channels,
        )
        return output_path

    def export_user_stt_wav(self, audio: AudioSegment, output_path: Path) -> Path:
        """Export STT-optimized user audio (16 kHz mono PCM16)."""
        from src.stt.audio_preprocess import export_stt_ready_wav

        return export_stt_ready_wav(audio, output_path)

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

        from src.utils.gcs_download import is_signed_gcs_http_url, try_download_gcs_source

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
        if response.status_code >= 400 and is_signed_gcs_http_url(url):
            from src.utils.gcs_download import try_download_expired_signed_url

            gcs_path = try_download_expired_signed_url(url, dest)
            if gcs_path is not None:
                logger.info("Downloaded audio via GCS API fallback to %s", gcs_path)
                fmt = validate_downloaded_audio(gcs_path)
                return ensure_extension(gcs_path, fmt)
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
