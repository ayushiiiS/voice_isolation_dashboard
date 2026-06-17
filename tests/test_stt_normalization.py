"""Tests for STT confidence normalization."""

from __future__ import annotations

import pytest

from src.stt.normalization import normalize_confidence, provider_supports_confidence


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.94, 94.0),
        (1.0, 100.0),
        (0.0, 0.0),
        (95.0, 95.0),
        (100.0, 100.0),
        (None, None),
    ],
)
def test_normalize_confidence(raw, expected):
    assert normalize_confidence("deepgram", raw) == expected


def test_normalize_negative_returns_none():
    assert normalize_confidence("azure", -0.1) is None


def test_provider_supports_confidence():
    assert provider_supports_confidence("deepgram") is True
    assert provider_supports_confidence("azure") is True
    assert provider_supports_confidence("openai") is False
    assert provider_supports_confidence("google") is False
    assert provider_supports_confidence("sarvam") is True
