"""Detect spoken language from isolated user audio for multi-provider STT."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.isolation.audio_extractor import AudioExtractor

logger = logging.getLogger(__name__)

# ISO 639-1 → default BCP-47 locale used by Azure / Google / AWS.
ISO639_TO_BCP47: dict[str, str] = {
    "en": "en-US",
    "hi": "hi-IN",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "pt": "pt-BR",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "zh-CN",
    "ar": "ar-SA",
    "ru": "ru-RU",
    "nl": "nl-NL",
    "tr": "tr-TR",
    "pl": "pl-PL",
    "vi": "vi-VN",
    "th": "th-TH",
    "id": "id-ID",
    "ta": "ta-IN",
    "te": "te-IN",
    "bn": "bn-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "pa": "pa-IN",
    "ur": "ur-PK",
}

SUPPORTED_LANGUAGES: list[dict[str, str]] = [
    {"code": code, "label": label}
    for code, label in [
        ("en-US", "English (US)"),
        ("hi-IN", "Hindi"),
        ("es-ES", "Spanish"),
        ("fr-FR", "French"),
        ("de-DE", "German"),
        ("pt-BR", "Portuguese (Brazil)"),
        ("it-IT", "Italian"),
        ("ja-JP", "Japanese"),
        ("ko-KR", "Korean"),
        ("zh-CN", "Chinese (Mandarin)"),
        ("ar-SA", "Arabic"),
        ("ru-RU", "Russian"),
        ("ta-IN", "Tamil"),
        ("te-IN", "Telugu"),
        ("bn-IN", "Bengali"),
        ("mr-IN", "Marathi"),
        ("gu-IN", "Gujarati"),
        ("kn-IN", "Kannada"),
        ("ml-IN", "Malayalam"),
        ("pa-IN", "Punjabi"),
        ("ur-PK", "Urdu"),
    ]
]

_whisper_model = None


@dataclass(frozen=True)
class LanguageCandidate:
    language: str
    language_code: str
    confidence: float


@dataclass(frozen=True)
class LanguageDetectionResult:
    language: Optional[str]
    language_code: Optional[str]
    confidence: float
    method: str
    language_mode: str = "fixed"
    candidates: list[LanguageCandidate] = field(default_factory=list)
    language_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "language_code": self.language_code,
            "confidence": self.confidence,
            "method": self.method,
            "language_mode": self.language_mode,
            "candidates": [
                {
                    "language": c.language,
                    "language_code": c.language_code,
                    "confidence": c.confidence,
                }
                for c in self.candidates
            ],
            "language_hints": self.language_hints,
        }


def iso639_to_bcp47(code: str) -> str:
    """Map ISO 639-1 code to a default BCP-47 locale."""
    normalized = code.lower().split("-")[0]
    return ISO639_TO_BCP47.get(normalized, f"{normalized}-{normalized.upper()}")


# Sarvam AI Indian-language locales (BCP-47).
SARVAM_LOCALES: dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "pa": "pa-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "as": "as-IN",
    "ur": "ur-IN",
    "ne": "ne-IN",
    "od": "od-IN",
    "or": "od-IN",
}


def provider_language(provider_id: str, bcp47: str) -> str:
    """Normalize BCP-47 locale for a specific STT provider API."""
    if not bcp47 or bcp47.lower() == "auto":
        return "auto"
    if provider_id == "sarvam":
        if bcp47.lower() == "unknown":
            return "unknown"
        if bcp47 in set(SARVAM_LOCALES.values()):
            return bcp47
        code = bcp47.split("-")[0].lower()
        return SARVAM_LOCALES.get(code, "unknown")
    if "-" in bcp47 and provider_id in {"azure", "google", "aws"}:
        return bcp47
    code = bcp47.split("-")[0].lower()
    if provider_id in {"deepgram", "openai"}:
        return code
    return iso639_to_bcp47(code)


def _confidence_threshold() -> float:
    return float(os.getenv("STT_LANGUAGE_CONFIDENCE_THRESHOLD", "0.80"))


def _default_language() -> LanguageDetectionResult:
    fallback = os.getenv("STT_DEFAULT_LANGUAGE", "en-US")
    code = fallback.split("-")[0].lower()
    return LanguageDetectionResult(
        language=fallback,
        language_code=code,
        confidence=0.0,
        method="fallback",
        language_mode="fixed",
        candidates=[
            LanguageCandidate(language=fallback, language_code=code, confidence=0.0),
        ],
        language_hints=[fallback],
    )


def _load_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    import whisper

    model_name = os.getenv("WHISPER_LID_MODEL", "small")
    logger.info("Loading Whisper model for language ID: %s", model_name)
    _whisper_model = whisper.load_model(model_name)
    return _whisper_model


def preload_whisper_model() -> None:
    """Load Whisper LID model at startup so the first STT session is not blocked."""
    if os.getenv("STT_LANGUAGE_DETECT", "true").lower() == "false":
        return
    if os.getenv("WHISPER_PRELOAD", "true").lower() == "false":
        return
    try:
        _load_whisper_model()
        logger.info("Whisper LID model preloaded")
    except ImportError:
        logger.warning("openai-whisper not installed; skipping LID preload")
    except Exception as exc:
        logger.warning("Whisper LID preload failed: %s", exc)


def _build_result_from_probs(probs: dict[str, float]) -> LanguageDetectionResult:
    threshold = _confidence_threshold()
    sorted_probs = sorted(probs.items(), key=lambda item: item[1], reverse=True)
    top_k = int(os.getenv("STT_LANGUAGE_TOP_K", "3"))
    candidates = [
        LanguageCandidate(
            language=iso639_to_bcp47(code),
            language_code=code,
            confidence=round(float(conf), 4),
        )
        for code, conf in sorted_probs[:top_k]
    ]

    if not candidates:
        return _default_language()

    top = candidates[0]
    hints = [c.language for c in candidates if c.confidence >= 0.15]

    if top.confidence > threshold:
        return LanguageDetectionResult(
            language=top.language,
            language_code=top.language_code,
            confidence=top.confidence,
            method="whisper",
            language_mode="fixed",
            candidates=candidates,
            language_hints=hints or [top.language],
        )

    return LanguageDetectionResult(
        language=None,
        language_code=None,
        confidence=top.confidence,
        method="whisper",
        language_mode="multilingual",
        candidates=candidates,
        language_hints=hints or [top.language],
    )


def _detect_with_whisper(local_path: Path) -> Optional[LanguageDetectionResult]:
    if os.getenv("STT_LANGUAGE_DETECT", "true").lower() == "false":
        return None
    try:
        import whisper
    except ImportError:
        logger.warning("openai-whisper not installed; language detection uses fallback")
        return None

    try:
        model = _load_whisper_model()
        audio = whisper.load_audio(str(local_path))
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio, n_mels=model.dims.n_mels).to(model.device)
        _, probs = model.detect_language(mel)
        if not probs:
            return None
        return _build_result_from_probs(probs)
    except Exception as exc:
        logger.warning("Whisper language detection failed: %s", exc)
        return None


def detect_language_from_audio_path(local_path: Path) -> LanguageDetectionResult:
    """Detect language from a local audio file path."""
    result = _detect_with_whisper(local_path)
    if result:
        logger.info(
            "Detected language mode=%s language=%s confidence=%.2f candidates=%s",
            result.language_mode,
            result.language,
            result.confidence,
            [(c.language_code, c.confidence) for c in result.candidates],
        )
        return result

    fallback = _default_language()
    logger.info("Using fallback STT language: %s", fallback.language)
    return fallback


def detect_language_from_audio_url(audio_url: str, *, max_seconds: int = 45) -> LanguageDetectionResult:
    """Download/load user audio and detect spoken language."""
    extractor = AudioExtractor()
    audio, local_path, is_temp = extractor.load_audio(audio_url)
    clip_path: Optional[Path] = None
    try:
        if max_seconds > 0 and len(audio) > max_seconds * 1000:
            clip = audio[: max_seconds * 1000]
            clip_path = Path(tempfile.mkstemp(suffix=".wav")[1])
            clip.export(str(clip_path), format="wav")
            detect_path = clip_path
        else:
            detect_path = local_path

        return detect_language_from_audio_path(detect_path)
    finally:
        if clip_path and clip_path.exists():
            clip_path.unlink(missing_ok=True)
        if is_temp and local_path.exists():
            local_path.unlink(missing_ok=True)


def effective_stt_language(detection: LanguageDetectionResult, override: Optional[str] = None) -> str:
    """Resolve the language string passed to STT providers."""
    if override:
        return override
    if detection.language_mode == "multilingual":
        return "auto"
    return detection.language or os.getenv("STT_DEFAULT_LANGUAGE", "en-US")
