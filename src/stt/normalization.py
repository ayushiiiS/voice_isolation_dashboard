"""Normalize provider-specific confidence scores to a common 0-100 scale.

Each STT provider exposes confidence differently:

- Deepgram: word-level confidence 0.0-1.0; we use utterance average.
- Azure Speech: 0.0-1.0 per word/phrase.
- OpenAI Whisper / Realtime: no native confidence → N/A.
- Google Cloud STT: no utterance-level confidence in streaming v2 → N/A
  (alternatives: use stability or word-level if present).
- Sarvam: ``language_probability`` (0.0-1.0) when ``language-code=unknown`` only;
  this is language-detection confidence, not word-level STT confidence.

Normalization rules:
- 0.0-1.0 float  → multiply by 100
- 0-100 float    → use as-is
- None / missing → return None (display "N/A" in UI)
"""

from __future__ import annotations

from typing import Optional


def normalize_confidence(
    provider: str,
    raw: Optional[float],
) -> Optional[float]:
    """Convert a provider raw confidence value to 0-100 scale."""
    if raw is None:
        return None

    value = float(raw)
    if value < 0:
        return None

    # Already on 0-100 scale (e.g. some REST APIs).
    if value > 1.0:
        return round(min(value, 100.0), 2)

    # Standard 0.0-1.0 probability scale (Deepgram, Azure, etc.).
    return round(value * 100.0, 2)


def provider_supports_confidence(provider: str) -> bool:
    """Whether the provider typically exposes confidence scores."""
    no_confidence = {"openai", "google", "aws"}
    return provider.lower() not in no_confidence
