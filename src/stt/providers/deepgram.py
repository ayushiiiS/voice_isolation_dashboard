"""Deepgram streaming STT adapter."""

from __future__ import annotations

import asyncio
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


def _deepgram_model() -> str:
    return os.getenv("DEEPGRAM_MODEL", "nova-2-general")


class DeepgramProvider(SttProviderAdapter):
    """Real-time transcription via Deepgram WebSocket API."""

    provider_id = "deepgram"
    display_name = "Deepgram"

    def __init__(self) -> None:
        super().__init__()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._last_audio_at = 0.0

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("DEEPGRAM_API_KEY", "").strip())

    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        api_key = os.getenv("DEEPGRAM_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")

        use_multilingual = language_mode in {"auto", "multilingual"} or language.lower() == "auto"
        params: dict[str, str | int] = {
            "model": _deepgram_model(),
            "encoding": "linear16",
            "sample_rate": sample_rate,
            "channels": 1,
            "interim_results": "true",
            "punctuate": "true",
        }
        # detect_language is NOT supported on streaming — use language=multi instead.
        if use_multilingual:
            params["language"] = "multi"
            params["endpointing"] = int(os.getenv("DEEPGRAM_ENDPOINTING_MS", "100"))
        else:
            params["language"] = provider_language(self.provider_id, language)

        url = f"wss://api.deepgram.com/v1/listen?{urlencode(params)}"
        logger.info(
            "Connecting to Deepgram (model=%s, language=%s)",
            params["model"],
            params["language"],
        )
        try:
            self._ws = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Token {api_key}"},
                open_timeout=15,
            )
        except websockets.exceptions.InvalidStatus as exc:
            body = getattr(exc, "body", b"") or b""
            detail = body.decode("utf-8", errors="replace") if body else str(exc)
            raise RuntimeError(
                f"Deepgram rejected the stream (HTTP {exc.response.status_code}): {detail}. "
                "Check DEEPGRAM_API_KEY and DEEPGRAM_MODEL (try nova-2-general)."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Deepgram connection failed: {exc}") from exc

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
        if not self._ws:
            return
        self._last_audio_at = time.perf_counter()
        await self._ws.send(pcm_bytes)

    async def flush(self) -> None:
        if self._ws:
            await self._ws.send(json.dumps({"type": "CloseStream"}))

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                start = self._last_audio_at or time.perf_counter()
                data = json.loads(message)
                channel = data.get("channel") or {}
                alternatives = channel.get("alternatives") or []
                if not alternatives:
                    continue
                alt = alternatives[0]
                text = (alt.get("transcript") or "").strip()
                if not text:
                    continue
                confidences = [
                    w.get("confidence")
                    for w in alt.get("words") or []
                    if w.get("confidence") is not None
                ]
                raw_conf = sum(confidences) / len(confidences) if confidences else alt.get("confidence")
                is_final = bool(data.get("is_final"))
                update_type = (
                    TranscriptUpdateType.FINAL if is_final else TranscriptUpdateType.PARTIAL
                )
                await self._emit_update(
                    text,
                    update_type,
                    raw_conf,
                    self._latency_since(start),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Deepgram receive loop failed")
            await self._emit_status(self._status_from_error(exc), str(exc))

    @staticmethod
    def _status_from_error(exc: Exception):
        from src.stt.models import ProviderStatus

        return ProviderStatus.ERROR
