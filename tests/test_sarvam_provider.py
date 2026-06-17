"""Tests for Sarvam STT provider helpers."""

from __future__ import annotations

from src.stt.providers.sarvam import (
    SarvamSttProvider,
    _extract_sarvam_confidence,
    _resolve_sarvam_language_code,
)


def test_sarvam_is_configured(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert SarvamSttProvider.is_configured() is False
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    assert SarvamSttProvider.is_configured() is True


def test_resolve_sarvam_language_defaults_to_unknown(monkeypatch):
    monkeypatch.delenv("SARVAM_LANGUAGE_CODE", raising=False)
    assert _resolve_sarvam_language_code("hi-IN", language_mode="fixed") == "unknown"


def test_resolve_sarvam_language_honors_pinned_locale(monkeypatch):
    monkeypatch.setenv("SARVAM_LANGUAGE_CODE", "hi-IN")
    assert _resolve_sarvam_language_code("en-US", language_mode="fixed") == "hi-IN"


def test_extract_sarvam_confidence():
    assert _extract_sarvam_confidence({"language_probability": 0.93}) == 0.93
    assert _extract_sarvam_confidence({"metrics": {"language_probability": 0.88}}) == 0.88
    assert _extract_sarvam_confidence({"transcript": "hello"}) is None
