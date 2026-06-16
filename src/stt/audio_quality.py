"""Inspect audio quality before STT to catch isolation and format issues."""

from __future__ import annotations

import array
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydub import AudioSegment

logger = logging.getLogger(__name__)

STT_TARGET_SAMPLE_RATE = 16000


@dataclass
class AudioQualityReport:
    score: float
    sample_rate: int
    channels: int
    sample_width_bytes: int
    duration_seconds: float
    clipping_ratio: float
    silence_ratio: float
    snr_db: float
    peak_dbfs: float
    rms_dbfs: float
    warnings: list[str] = field(default_factory=list)
    source_label: str = ""

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_width_bytes": self.sample_width_bytes,
            "duration_seconds": round(self.duration_seconds, 3),
            "clipping_ratio": round(self.clipping_ratio, 4),
            "silence_ratio": round(self.silence_ratio, 4),
            "snr_db": round(self.snr_db, 2),
            "peak_dbfs": round(self.peak_dbfs, 2),
            "rms_dbfs": round(self.rms_dbfs, 2),
            "warnings": self.warnings,
            "source_label": self.source_label,
        }


def _samples(segment: AudioSegment) -> array.array:
    raw = segment.raw_data
    if segment.sample_width == 2:
        return array.array("h")
    return array.array("B")


def _to_mono_pcm16(segment: AudioSegment) -> array.array:
    mono = segment.set_channels(1).set_frame_rate(STT_TARGET_SAMPLE_RATE).set_sample_width(2)
    samples = array.array("h")
    samples.frombytes(mono.raw_data)
    return samples


def _dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return 20.0 * math.log10(value)


def analyze_audio_segment(segment: AudioSegment, *, source_label: str = "") -> AudioQualityReport:
    """Compute an Audio Quality Score (0–100) and diagnostic warnings."""
    warnings: list[str] = []
    duration_seconds = len(segment) / 1000.0

    if duration_seconds < 0.3:
        warnings.append("Audio is extremely short; STT accuracy will be poor.")

    samples = _to_mono_pcm16(segment)
    if not samples:
        return AudioQualityReport(
            score=0.0,
            sample_rate=segment.frame_rate,
            channels=segment.channels,
            sample_width_bytes=segment.sample_width,
            duration_seconds=duration_seconds,
            clipping_ratio=1.0,
            silence_ratio=1.0,
            snr_db=0.0,
            peak_dbfs=-120.0,
            rms_dbfs=-120.0,
            warnings=["Empty audio buffer."],
            source_label=source_label,
        )

    abs_samples = [abs(s) for s in samples]
    peak = max(abs_samples)
    peak_norm = peak / 32768.0
    peak_dbfs = _dbfs(peak_norm)

    squares = [(s / 32768.0) ** 2 for s in samples]
    rms = math.sqrt(sum(squares) / len(squares))
    rms_dbfs = _dbfs(rms)

    clip_threshold = 32000
    clipped = sum(1 for s in samples if abs(s) >= clip_threshold)
    clipping_ratio = clipped / len(samples)

    silence_threshold = 500
    silent = sum(1 for s in samples if abs(s) < silence_threshold)
    silence_ratio = silent / len(samples)

    # Simple SNR: speech RMS vs silence-floor estimate.
    nonsilent = [s for s in samples if abs(s) >= silence_threshold]
    if nonsilent:
        speech_rms = math.sqrt(sum((s / 32768.0) ** 2 for s in nonsilent) / len(nonsilent))
        noise_floor = max(rms * 0.15, 1e-6)
        snr_db = _dbfs(speech_rms) - _dbfs(noise_floor)
    else:
        snr_db = 0.0
        warnings.append("No detectable speech energy.")

    if segment.frame_rate != STT_TARGET_SAMPLE_RATE:
        warnings.append(
            f"Sample rate is {segment.frame_rate} Hz; STT resamples to {STT_TARGET_SAMPLE_RATE} Hz."
        )
    if segment.channels > 1:
        warnings.append("Stereo audio will be downmixed for STT.")
    if clipping_ratio > 0.001:
        warnings.append("Audio clipping detected; transcription may degrade.")
    if silence_ratio > 0.85:
        warnings.append("Excessive silence; check voice isolation removed speech.")
    if snr_db < 10:
        warnings.append("Low SNR estimate; background noise may hurt accuracy.")
    if duration_seconds > 0 and len(nonsilent) / len(samples) < 0.05:
        warnings.append("Very little speech content after isolation.")

    score = 100.0
    score -= min(clipping_ratio * 5000, 30)
    score -= min(max(silence_ratio - 0.5, 0) * 80, 25)
    score -= min(max(10 - snr_db, 0) * 2, 20)
    score -= 10 if segment.frame_rate != STT_TARGET_SAMPLE_RATE else 0
    score -= 15 if duration_seconds < 1.0 else 0
    score = max(0.0, min(100.0, score))

    return AudioQualityReport(
        score=score,
        sample_rate=segment.frame_rate,
        channels=segment.channels,
        sample_width_bytes=segment.sample_width,
        duration_seconds=duration_seconds,
        clipping_ratio=clipping_ratio,
        silence_ratio=silence_ratio,
        snr_db=snr_db,
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        warnings=warnings,
        source_label=source_label,
    )


def analyze_audio_path(path: Path, *, source_label: str = "") -> AudioQualityReport:
    segment = AudioSegment.from_file(str(path))
    return analyze_audio_segment(segment, source_label=source_label)
