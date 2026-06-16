"""Tests for STT accuracy modules."""

from __future__ import annotations

from pydub import AudioSegment
from pydub.generators import Sine

from src.stt.audio_quality import analyze_audio_segment
from src.stt.consensus import build_consensus
from src.stt.language_detection import LanguageCandidate, LanguageDetectionResult, _build_result_from_probs
from src.stt.postprocess import postprocess_transcript
from src.stt.provider_scoring import score_provider


def test_build_result_high_confidence_fixed():
    probs = {"hi": 0.85, "en": 0.10}
    result = _build_result_from_probs(probs)
    assert result.language_mode == "fixed"
    assert result.language == "hi-IN"
    assert result.confidence == 0.85


def test_build_result_low_confidence_multilingual():
    probs = {"hi": 0.55, "en": 0.40}
    result = _build_result_from_probs(probs)
    assert result.language_mode == "multilingual"
    assert result.language is None
    assert len(result.candidates) >= 2


def test_consensus_majority():
    texts = {
        "deepgram": "deploy the backend tomorrow",
        "azure": "deploy backend tomorrow",
        "google": "deploy the backend tomorrow",
    }
    result = build_consensus(texts)
    assert "deploy" in result.text
    assert "backend" in result.text
    assert result.agreement_ratio > 0.5


def test_postprocess_transcript():
    raw = "hello everyone today we discuss api version 2"
    out = postprocess_transcript(raw)
    assert out.startswith("Hello")
    assert "API" in out
    assert out.endswith(".")


def test_provider_composite_score():
    scored = score_provider(
        provider="deepgram",
        transcript="hello world this is a test transcript",
        normalized_confidence=88.0,
        audio_duration_seconds=10.0,
        detected_language="en-US",
        expected_language="en-US",
        max_word_count=20,
    )
    assert 0.0 < scored.composite <= 1.0
    assert scored.word_count == 7


def test_audio_quality_score(temp_dir):
    wav = temp_dir / "tone.wav"
    Sine(440).to_audio_segment(duration=2000).export(str(wav), format="wav")
    segment = AudioSegment.from_wav(str(wav))
    report = analyze_audio_segment(segment, source_label="test")
    assert 0 <= report.score <= 100
    assert report.duration_seconds > 0
