"""Composite provider scoring for STT accuracy ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderScore:
    provider: str
    confidence: float
    completeness: float
    language_match: float
    composite: float
    word_count: int

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "confidence": round(self.confidence, 4),
            "completeness": round(self.completeness, 4),
            "language_match": round(self.language_match, 4),
            "composite": round(self.composite, 4),
            "word_count": self.word_count,
        }


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def score_provider(
    *,
    provider: str,
    transcript: str,
    normalized_confidence: float | None,
    audio_duration_seconds: float,
    detected_language: str | None,
    expected_language: str | None,
    max_word_count: int,
) -> ProviderScore:
    """score = 0.5*confidence + 0.3*completeness + 0.2*language_match"""
    words = _word_count(transcript)
    if normalized_confidence is not None:
        confidence = normalized_confidence / 100.0
    else:
        # Heuristic for providers without confidence API.
        confidence = min(0.75, 0.35 + min(words, 120) / 400.0)

    if audio_duration_seconds > 0:
        expected_wps = 2.0
        expected_words = audio_duration_seconds * expected_wps
        completeness = min(1.0, words / max(expected_words, 1.0))
    else:
        completeness = 1.0 if words > 0 else 0.0

    if max_word_count > 0:
        completeness = max(completeness, words / max_word_count)

    language_match = 1.0
    if detected_language and expected_language:
        det = detected_language.lower().split("-")[0]
        exp = expected_language.lower().split("-")[0]
        language_match = 1.0 if det == exp else 0.4

    composite = 0.5 * confidence + 0.3 * completeness + 0.2 * language_match
    return ProviderScore(
        provider=provider,
        confidence=confidence,
        completeness=completeness,
        language_match=language_match,
        composite=composite,
        word_count=words,
    )


def rank_providers(scores: list[ProviderScore]) -> list[ProviderScore]:
    return sorted(scores, key=lambda s: (s.composite, s.word_count), reverse=True)
