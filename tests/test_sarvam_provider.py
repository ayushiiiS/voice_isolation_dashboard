"""Tests for Sarvam STT provider helpers."""

from __future__ import annotations

from src.stt.providers.sarvam import (
    SarvamSttProvider,
    _extract_sarvam_confidence,
    _pcm_to_wav,
    _resolve_sarvam_language_code,
    _resolve_sarvam_mode,
)


def test_sarvam_is_configured(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert SarvamSttProvider.is_configured() is False
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    assert SarvamSttProvider.is_configured() is True


def test_resolve_sarvam_language_defaults_to_unknown(monkeypatch):
    monkeypatch.delenv("SARVAM_LANGUAGE_CODE", raising=False)
    assert (
        _resolve_sarvam_language_code("hi-IN", language_mode="fixed", stt_mode="transcribe")
        == "hi-IN"
    )


def test_resolve_sarvam_language_honors_pinned_locale(monkeypatch):
    monkeypatch.setenv("SARVAM_LANGUAGE_CODE", "hi-IN")
    assert (
        _resolve_sarvam_language_code("en-US", language_mode="fixed", stt_mode="transcribe")
        == "hi-IN"
    )


def test_resolve_sarvam_language_codemix_uses_detected_locale(monkeypatch):
    monkeypatch.delenv("SARVAM_LANGUAGE_CODE", raising=False)
    assert (
        _resolve_sarvam_language_code("hi-IN", language_mode="fixed", stt_mode="codemix")
        == "hi-IN"
    )


def test_resolve_sarvam_mode_auto_codemix_for_hindi(monkeypatch):
    monkeypatch.setenv("SARVAM_STT_MODE", "transcribe")
    monkeypatch.setenv("SARVAM_AUTO_CODEMIX", "true")
    assert _resolve_sarvam_mode("hi-IN", language_mode="fixed") == "codemix"


def test_resolve_sarvam_mode_respects_explicit_mode(monkeypatch):
    monkeypatch.setenv("SARVAM_STT_MODE", "verbatim")
    assert _resolve_sarvam_mode("hi-IN", language_mode="fixed") == "verbatim"


def test_pcm_to_wav_wraps_header():
    pcm = b"\x00\x01" * 100
    wav = _pcm_to_wav(pcm, 16000)
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav[:12]
    assert len(wav) == 44 + len(pcm)


def test_extract_sarvam_confidence():
    assert _extract_sarvam_confidence({"language_probability": 0.93}) == 0.93
    assert _extract_sarvam_confidence({"metrics": {"language_probability": 0.88}}) == 0.88
    assert _extract_sarvam_confidence({"transcript": "hello"}) is None
