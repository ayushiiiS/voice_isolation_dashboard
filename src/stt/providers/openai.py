"""OpenAI Realtime / Whisper streaming adapter."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Optional

import websockets

from src.stt.language_detection import provider_language
from src.stt.base import SttProviderAdapter
from src.stt.models import TranscriptUpdateType

logger = logging.getLogger(__name__)


class OpenAiSttProvider(SttProviderAdapter):
    """OpenAI Realtime API transcription (no native confidence scores)."""

    provider_id = "openai"
    display_name = "OpenAI"

    def __init__(self) -> None:
        super().__init__()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._last_audio_at = 0.0

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-mini-transcribe")
        url = "wss://api.openai.com/v1/realtime?intent=transcription"
        self._ws = await websockets.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "OpenAI-Beta": "realtime=v1",
            },
            open_timeout=10,
        )
        session_update = {
            "type": "transcription_session.update",
            "session": {
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": model,
                    "language": provider_language(self.provider_id, language),
                },
                "turn_detection": {"type": "server_vad"},
            },
        }
        await self._ws.send(json.dumps(session_update))
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def disconnect(self) -> None:
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not self._ws:
            return
        self._last_audio_at = time.perf_counter()
        payload = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm_bytes).decode("ascii"),
        }
        await self._ws.send(json.dumps(payload))

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                start = self._last_audio_at or time.perf_counter()
                data = json.loads(message)
                msg_type = data.get("type", "")
                if msg_type == "conversation.item.input_audio_transcription.completed":
                    text = (data.get("transcript") or "").strip()
                    if text:
                        await self._emit_update(
                            text,
                            TranscriptUpdateType.FINAL,
                            None,
                            self._latency_since(start),
                        )
                elif msg_type == "conversation.item.input_audio_transcription.delta":
                    text = (data.get("delta") or "").strip()
                    if text:
                        await self._emit_update(
                            text,
                            TranscriptUpdateType.PARTIAL,
                            None,
                            self._latency_since(start),
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("OpenAI STT receive loop failed")
            from src.stt.models import ProviderStatus

            await self._emit_status(ProviderStatus.ERROR, str(exc))
