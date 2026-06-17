"""Tests for STT language detection helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from src.stt.language_detection import (
    LanguageCandidate,
    LanguageDetectionResult,
    detect_language_from_audio_path,
    iso639_to_bcp47,
    provider_language,
)


def test_iso639_to_bcp47():
    assert iso639_to_bcp47("en") == "en-US"
    assert iso639_to_bcp47("hi") == "hi-IN"
    assert iso639_to_bcp47("es") == "es-ES"


def test_provider_language_normalization():
    assert provider_language("deepgram", "hi-IN") == "hi"
    assert provider_language("openai", "hi-IN") == "hi"
    assert provider_language("azure", "hi-IN") == "hi-IN"
    assert provider_language("google", "en") == "en-US"
    assert provider_language("sarvam", "hi-IN") == "hi-IN"
    assert provider_language("sarvam", "en") == "en-IN"
    assert provider_language("sarvam", "auto") == "auto"


def test_detect_language_fallback_without_whisper(temp_dir, monkeypatch):
    monkeypatch.setenv("STT_LANGUAGE_DETECT", "false")
    wav = temp_dir / "sample.wav"
    Sine(440).to_audio_segment(duration=1000).export(str(wav), format="wav")

    result = detect_language_from_audio_path(wav)
    assert result.method == "fallback"
    assert result.language == "en-US"


def test_detect_language_whisper_mock(temp_dir, monkeypatch):
    wav = temp_dir / "sample.wav"
    Sine(440).to_audio_segment(duration=1000).export(str(wav), format="wav")

    def fake_whisper(_path: Path):
        return LanguageDetectionResult(
            language="hi-IN",
            language_code="hi",
            confidence=0.91,
            method="whisper",
            language_mode="fixed",
            candidates=[
                LanguageCandidate(language="hi-IN", language_code="hi", confidence=0.91),
            ],
            language_hints=["hi-IN"],
        )

    monkeypatch.setattr(
        "src.stt.language_detection._detect_with_whisper",
        fake_whisper,
    )
    result = detect_language_from_audio_path(wav)
    assert result.language == "hi-IN"
    assert result.method == "whisper"
