"""AWS Transcribe streaming adapter."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from src.stt.language_detection import provider_language
from src.stt.base import SttProviderAdapter
from src.stt.models import TranscriptUpdateType

logger = logging.getLogger(__name__)


class AwsTranscribeProvider(SttProviderAdapter):
    """Amazon Transcribe streaming (no confidence in standard streaming output)."""

    provider_id = "aws"
    display_name = "AWS Transcribe"

    def __init__(self) -> None:
        super().__init__()
        self._stream = None
        self._handler = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(
            os.getenv("AWS_ACCESS_KEY_ID")
            and os.getenv("AWS_SECRET_ACCESS_KEY")
            and os.getenv("AWS_REGION")
        )

    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        try:
            from amazon_transcribe.client import TranscribeStreamingClient
            from amazon_transcribe.handlers import TranscriptResultStreamHandler
            from amazon_transcribe.model import TranscriptEvent
        except ImportError as exc:
            raise RuntimeError(
                "Install amazon-transcribe for AWS Transcribe streaming support"
            ) from exc

        self._sample_rate = sample_rate
        self._language = provider_language(self.provider_id, language)
        self._client = TranscribeStreamingClient(region=os.environ["AWS_REGION"])
        self._last_audio_at = time.perf_counter()
        loop = asyncio.get_running_loop()
        provider = self

        class Handler(TranscriptResultStreamHandler):
            async def handle_transcript_event(self, transcript_event: TranscriptEvent):
                for result in transcript_event.transcript.results:
                    if not result.alternatives:
                        continue
                    alt = result.alternatives[0]
                    text = (alt.transcript or "").strip()
                    if not text:
                        continue
                    update_type = (
                        TranscriptUpdateType.FINAL
                        if not result.is_partial
                        else TranscriptUpdateType.PARTIAL
                    )
                    await provider._emit_update(
                        text,
                        update_type,
                        None,
                        provider._latency_since(provider._last_audio_at),
                    )

        self._handler = Handler(None)
        self._stream = await self._client.start_stream_transcription(
            language_code=provider_language(self.provider_id, language),
            media_sample_rate_hz=sample_rate,
            media_encoding="pcm",
        )
        self._handler = Handler(self._stream.output_stream)
        self._receive_task = asyncio.create_task(self._handler.handle_events())

    async def disconnect(self) -> None:
        if hasattr(self, "_receive_task") and self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._stream:
            await self._stream.input_stream.end_stream()
            self._stream = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._stream:
            self._last_audio_at = time.perf_counter()
            await self._stream.input_stream.send_audio_event(audio_chunk=pcm_bytes)
