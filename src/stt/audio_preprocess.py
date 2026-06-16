"""Prepare audio for maximum STT accuracy."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

logger = logging.getLogger(__name__)

STT_SAMPLE_RATE = 16000


def prepare_for_stt(
    audio: AudioSegment,
    *,
    target_sample_rate: int = STT_SAMPLE_RATE,
    peak_normalize: bool | None = None,
) -> AudioSegment:
    """Convert to mono PCM16 at STT sample rate with optional peak normalization."""
    if peak_normalize is None:
        peak_normalize = os.getenv("STT_PEAK_NORMALIZE", "true").lower() == "true"

    processed = audio.set_channels(1).set_frame_rate(target_sample_rate).set_sample_width(2)
    if peak_normalize and len(processed) > 0:
        processed = pydub_normalize(processed)
    return processed


def export_stt_ready_wav(audio: AudioSegment, output_path: Path) -> Path:
    """Export STT-optimized WAV (16 kHz mono PCM16)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ready = prepare_for_stt(audio)
    ready.export(str(output_path), format="wav")
    logger.info(
        "Exported STT-ready audio: %s (%d Hz mono PCM16, %.1fs)",
        output_path,
        STT_SAMPLE_RATE,
        len(ready) / 1000.0,
    )
    return output_path
