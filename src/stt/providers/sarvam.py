"""Sarvam AI streaming STT adapter (Indian languages)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Optional
from urllib.parse import urlencode

import websockets

from src.stt.base import SttProviderAdapter
from src.stt.language_detection import provider_language
from src.stt.models import TranscriptUpdateType

logger = logging.getLogger(__name__)

SARVAM_WS_URL = "wss://api.sarvam.ai/speech-to-text/ws"


def _resolve_sarvam_language_code(
    language: str,
    *,
    language_mode: str,
) -> str:
    """Pick Sarvam language-code query param.

    Sarvam only returns ``language_probability`` when language-code is ``unknown``
    (auto-detect). Word-level transcription confidence is not exposed in streaming.
    """
    pinned = os.getenv("SARVAM_LANGUAGE_CODE", "unknown").strip()
    if not pinned or pinned.lower() in {"unknown", "auto"}:
        return "unknown"
    if pinned.lower() == "fixed":
        use_auto = language_mode in {"auto", "multilingual"} or language.lower() == "auto"
        return "unknown" if use_auto else provider_language("sarvam", language)
    return provider_language("sarvam", pinned)


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
        self._last_transcript = ""
        self._last_confidence: Optional[float] = None

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
        language_code = _resolve_sarvam_language_code(
            language,
            language_mode=language_mode,
        )

        params = {
            "language-code": language_code,
            "model": os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
            "mode": os.getenv("SARVAM_STT_MODE", "transcribe"),
            "sample_rate": str(sample_rate),
            "input_audio_codec": "pcm_s16le",
            "vad_signals": "false",
        }
        url = f"{SARVAM_WS_URL}?{urlencode(params)}"
        logger.info(
            "Connecting to Sarvam STT (model=%s, language=%s)",
            params["model"],
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
        payload = {
            "audio": {
                "data": base64.b64encode(pcm_bytes).decode("ascii"),
                "sample_rate": str(self._sample_rate),
                "encoding": "audio/wav",
            }
        }
        await self._ws.send(json.dumps(payload))

    async def flush(self) -> None:
        if not self._ws:
            return
        await self._ws.send(json.dumps({"type": "flush"}))
        if self._last_transcript.strip():
            await self._emit_update(
                self._last_transcript.strip(),
                TranscriptUpdateType.FINAL,
                self._last_confidence,
                self._latency_since(self._last_audio_at),
            )

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                start = self._last_audio_at or time.perf_counter()
                data = json.loads(message)
                if data.get("type") != "data":
                    continue
                payload = data.get("data") or {}
                if "error" in payload:
                    raise RuntimeError(payload.get("error") or "Sarvam STT error")

                text = (payload.get("transcript") or "").strip()
                if not text or text == self._last_transcript:
                    continue

                raw_conf = _extract_sarvam_confidence(payload)
                if raw_conf is not None:
                    self._last_confidence = raw_conf
                self._last_transcript = text
                await self._emit_update(
                    text,
                    TranscriptUpdateType.PARTIAL,
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
