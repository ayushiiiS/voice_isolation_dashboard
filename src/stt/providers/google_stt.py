"""Google Cloud Speech-to-Text streaming adapter."""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time
from typing import Optional

from src.stt.language_detection import provider_language
from src.stt.base import SttProviderAdapter
from src.stt.models import TranscriptUpdateType

logger = logging.getLogger(__name__)


class GoogleSttProvider(SttProviderAdapter):
    """Google Cloud Speech streaming v1 (no utterance-level confidence in streaming)."""

    provider_id = "google"
    display_name = "Google STT"

    def __init__(self) -> None:
        super().__init__()
        self._audio_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or os.getenv("GOOGLE_CLOUD_STT_CREDENTIALS")
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
            from google.cloud import speech_v1p1beta1 as speech
        except ImportError as exc:
            raise RuntimeError("Install google-cloud-speech for Google STT support") from exc

        self._loop = asyncio.get_running_loop()
        self._last_audio_at = time.perf_counter()
        self._speech = speech
        self._sample_rate = sample_rate
        self._language = provider_language(self.provider_id, language)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

    async def disconnect(self) -> None:
        self._stop_event.set()
        self._audio_queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        self._last_audio_at = time.perf_counter()
        self._audio_queue.put(pcm_bytes)

    def _stream_loop(self) -> None:
        client = self._speech.SpeechClient()
        config = self._speech.RecognitionConfig(
            encoding=self._speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self._sample_rate,
            language_code=self._language,
            enable_automatic_punctuation=True,
            model="latest_long",
        )
        streaming_config = self._speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
        )

        def request_generator():
            while not self._stop_event.is_set():
                try:
                    chunk = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                yield self._speech.StreamingRecognizeRequest(audio_content=chunk)

        try:
            responses = client.streaming_recognize(streaming_config, request_generator())
            for response in responses:
                if self._stop_event.is_set():
                    break
                for result in response.results:
                    if not result.alternatives:
                        continue
                    alt = result.alternatives[0]
                    text = (alt.transcript or "").strip()
                    if not text:
                        continue
                    update_type = (
                        TranscriptUpdateType.FINAL
                        if result.is_final
                        else TranscriptUpdateType.PARTIAL
                    )
                    asyncio.run_coroutine_threadsafe(
                        self._emit_update(
                            text,
                            update_type,
                            None,
                            self._latency_since(getattr(self, "_last_audio_at", time.perf_counter())),
                        ),
                        self._loop,
                    )
        except Exception as exc:
            logger.exception("Google STT stream failed")
            from src.stt.models import ProviderStatus

            asyncio.run_coroutine_threadsafe(
                self._emit_status(ProviderStatus.ERROR, str(exc)),
                self._loop,
            )
