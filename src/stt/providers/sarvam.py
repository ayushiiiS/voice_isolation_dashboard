"""Sarvam AI streaming STT adapter (Indian languages)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import struct
import time
from typing import Optional
from urllib.parse import urlencode

import websockets

from src.stt.base import SttProviderAdapter
from src.stt.language_detection import provider_language
from src.stt.models import TranscriptUpdateType

logger = logging.getLogger(__name__)

SARVAM_WS_URL = "wss://api.sarvam.ai/speech-to-text/ws"
# Sarvam closes the stream on raw pcm_s16le chunks; wrap each chunk as a mini WAV.
SARVAM_FLUSH_EVERY_CHUNKS = int(os.getenv("SARVAM_FLUSH_EVERY_CHUNKS", "50"))


def _pcm_to_wav(pcm: bytes, sample_rate: int, *, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM16 mono bytes in a minimal RIFF/WAV header for Sarvam streaming."""
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        channels * sample_width,
        b"data",
        data_size,
    )
    return header + pcm


def _resolve_sarvam_mode(language: str, *, language_mode: str) -> str:
    """Pick Saaras output mode; auto-select codemix for Hindi/Hinglish call audio."""
    configured = os.getenv("SARVAM_STT_MODE", "transcribe").strip() or "transcribe"
    if configured != "transcribe":
        return configured
    if os.getenv("SARVAM_AUTO_CODEMIX", "true").lower() != "true":
        return configured
    lang = (language or "").lower()
    lang_prefix = lang.split("-")[0]
    if language_mode in {"auto", "multilingual"} or lang_prefix == "hi" or lang in {"hi-in", "auto"}:
        return "codemix"
    return configured


def _resolve_sarvam_language_code(
    language: str,
    *,
    language_mode: str,
    stt_mode: str,
) -> str:
    """Pick Sarvam language-code query param.

    Sarvam only returns ``language_probability`` when language-code is ``unknown``
    (auto-detect). Codemix mode works best with an explicit Indian locale (e.g. hi-IN).
    """
    pinned = os.getenv("SARVAM_LANGUAGE_CODE", "unknown").strip()
    if pinned and pinned.lower() not in {"unknown", "auto", "fixed"}:
        return provider_language("sarvam", pinned)
    if pinned.lower() == "fixed":
        use_auto = language_mode in {"auto", "multilingual"} or language.lower() == "auto"
        return "unknown" if use_auto else provider_language("sarvam", language)
    if stt_mode == "codemix" and language and language.lower() != "auto":
        return provider_language("sarvam", language)
    if language_mode in {"auto", "multilingual"} or language.lower() == "auto":
        return "unknown"
    if language and language.lower() != "auto":
        return provider_language("sarvam", language)
    return "unknown"


def _extract_sarvam_confidence(payload: dict) -> Optional[float]:
    """Extract the best available confidence signal from a Sarvam payload."""
    for key in ("language_probability", "confidence", "transcription_confidence"):
        value = payload.get(key)
        if value is not None:
            return float(value)

    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        for key in ("language_probability", "confidence"):
            value = metrics.get(key)
            if value is not None:
                return float(value)
    return None


class SarvamSttProvider(SttProviderAdapter):
    """Real-time transcription via Sarvam AI WebSocket API."""

    provider_id = "sarvam"
    display_name = "Sarvam AI"

    def __init__(self) -> None:
        super().__init__()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._last_audio_at = 0.0
        self._sample_rate = 16000
        self._last_confidence: Optional[float] = None
        self._chunks_sent = 0

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("SARVAM_API_KEY", "").strip())

    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        api_key = os.getenv("SARVAM_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SARVAM_API_KEY is not set")

        self._sample_rate = sample_rate
        stt_mode = _resolve_sarvam_mode(language, language_mode=language_mode)
        language_code = _resolve_sarvam_language_code(
            language,
            language_mode=language_mode,
            stt_mode=stt_mode,
        )

        params = {
            "language-code": language_code,
            "model": os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
            "mode": stt_mode,
            "sample_rate": str(sample_rate),
            "input_audio_codec": "wav",
            "flush_signal": os.getenv("SARVAM_FLUSH_SIGNAL", "true"),
            "high_vad_sensitivity": os.getenv("SARVAM_HIGH_VAD", "true"),
            "vad_signals": "false",
        }
        url = f"{SARVAM_WS_URL}?{urlencode(params)}"
        logger.info(
            "Connecting to Sarvam STT (model=%s, mode=%s, language=%s)",
            params["model"],
            stt_mode,
            language_code,
        )
        try:
            self._ws = await websockets.connect(
                url,
                additional_headers={"Api-Subscription-Key": api_key},
                open_timeout=15,
            )
        except websockets.exceptions.InvalidStatus as exc:
            body = getattr(exc, "body", b"") or b""
            detail = body.decode("utf-8", errors="replace") if body else str(exc)
            raise RuntimeError(
                f"Sarvam rejected the stream (HTTP {exc.response.status_code}): {detail}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Sarvam connection failed: {exc}") from exc

        self._receive_task = asyncio.create_task(self._receive_loop())

    async def disconnect(self) -> None:
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not self._ws or not pcm_bytes:
            return
        self._last_audio_at = time.perf_counter()
        wav_bytes = _pcm_to_wav(pcm_bytes, self._sample_rate)
        payload = {
            "audio": {
                "data": base64.b64encode(wav_bytes).decode("ascii"),
                "sample_rate": str(self._sample_rate),
                "encoding": "audio/wav",
            }
        }
        await self._ws.send(json.dumps(payload))
        self._chunks_sent += 1
        if (
            SARVAM_FLUSH_EVERY_CHUNKS > 0
            and self._chunks_sent % SARVAM_FLUSH_EVERY_CHUNKS == 0
        ):
            await self.flush(wait=False)

    async def flush(self, *, wait: bool = True) -> None:
        if not self._ws:
            return
        await self._ws.send(json.dumps({"type": "flush"}))
        if wait:
            await asyncio.sleep(0.5)

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                start = self._last_audio_at or time.perf_counter()
                data = json.loads(message)
                msg_type = data.get("type")
                if msg_type == "events":
                    continue

                if msg_type != "data":
                    continue

                payload = data.get("data") or {}
                if payload.get("signal_type"):
                    continue
                if "error" in payload:
                    raise RuntimeError(payload.get("error") or "Sarvam STT error")

                text = (payload.get("transcript") or "").strip()
                if not text:
                    continue

                raw_conf = _extract_sarvam_confidence(payload)
                if raw_conf is not None:
                    self._last_confidence = raw_conf
                # Each data message is a finalized utterance segment — emit FINAL so the
                # orchestrator accumulates segments (same as Deepgram is_final handling).
                await self._emit_update(
                    text,
                    TranscriptUpdateType.FINAL,
                    raw_conf,
                    self._latency_since(start),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Sarvam receive loop failed")
            await self._emit_status(self._status_from_error(exc), str(exc))

    @staticmethod
    def _status_from_error(exc: Exception):
        from src.stt.models import ProviderStatus

        return ProviderStatus.ERROR
