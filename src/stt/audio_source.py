"""Choose best audio source for STT: isolated user track vs original recording."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from src.isolation.audio_extractor import AudioExtractor
from src.stt.audio_quality import AudioQualityReport, analyze_audio_segment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioSourceDecision:
    url: str
    source_type: str
    isolated_quality: AudioQualityReport | None
    original_quality: AudioQualityReport | None
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "source_type": self.source_type,
            "isolated_quality": self.isolated_quality.to_dict() if self.isolated_quality else None,
            "original_quality": self.original_quality.to_dict() if self.original_quality else None,
            "warnings": self.warnings,
        }


def resolve_stt_audio_source(
    *,
    user_audio_url: str,
    original_audio_url: str | None,
    preference: str | None = None,
) -> AudioSourceDecision:
    """Pick isolated or original audio based on quality A/B and preference."""
    pref = (preference or os.getenv("STT_AUDIO_SOURCE", "auto")).lower()
    extractor = AudioExtractor()
    warnings: list[str] = []

    isolated_seg, isolated_path, isolated_temp = extractor.load_audio(user_audio_url)
    isolated_q = analyze_audio_segment(isolated_seg, source_label="isolated_user_audio")

    original_q: AudioQualityReport | None = None
    original_path: Path | None = None
    original_temp = False
    if original_audio_url:
        try:
            original_seg, original_path, original_temp = extractor.load_audio(original_audio_url)
            original_q = analyze_audio_segment(original_seg, source_label="original_recording")
        except Exception as exc:
            warnings.append(f"Could not load original audio for A/B: {exc}")

    chosen_url = user_audio_url
    chosen_type = "isolated_user_audio"

    if pref == "isolated":
        chosen_url, chosen_type = user_audio_url, "isolated_user_audio"
    elif pref == "original" and original_audio_url:
        chosen_url, chosen_type = original_audio_url, "original_recording"
    elif pref == "auto" and original_q is not None:
        iso_score = isolated_q.score
        orig_score = original_q.score
        if orig_score > iso_score + 5:
            chosen_url = original_audio_url or user_audio_url
            chosen_type = "original_recording"
            warnings.append(
                f"Falling back to original audio (quality {orig_score:.0f} vs isolated {iso_score:.0f})."
            )
        elif iso_score + 5 < 50 and orig_score > iso_score:
            chosen_url = original_audio_url or user_audio_url
            chosen_type = "original_recording"
            warnings.append("Isolated audio quality is poor; using original recording.")

    extractor.cleanup_temp(isolated_path, isolated_temp)
    if original_path is not None:
        extractor.cleanup_temp(original_path, original_temp)

    return AudioSourceDecision(
        url=chosen_url,
        source_type=chosen_type,
        isolated_quality=isolated_q,
        original_quality=original_q,
        warnings=warnings,
    )
