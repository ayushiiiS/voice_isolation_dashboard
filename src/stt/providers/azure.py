"""Azure Speech streaming STT adapter."""

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


class AzureSpeechProvider(SttProviderAdapter):
    """Azure Cognitive Services Speech-to-Text (requires azure-cognitiveservices-speech)."""

    provider_id = "azure"
    display_name = "Azure Speech"

    def __init__(self) -> None:
        super().__init__()
        self._recognizer = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("AZURE_SPEECH_KEY") and os.getenv("AZURE_SPEECH_REGION"))

    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as exc:
            raise RuntimeError(
                "Install azure-cognitiveservices-speech for Azure STT support"
            ) from exc

        self._loop = asyncio.get_running_loop()
        self._last_audio_at = time.perf_counter()
        speech_config = speechsdk.SpeechConfig(
            subscription=os.environ["AZURE_SPEECH_KEY"],
            region=os.environ["AZURE_SPEECH_REGION"],
        )
        use_auto = language_mode in {"auto", "multilingual"} or language.lower() == "auto"
        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=sample_rate,
            bits_per_sample=16,
            channels=1,
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        if use_auto and language_hints:
            auto_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=[provider_language(self.provider_id, hint) for hint in language_hints[:4]],
            )
            self._recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                auto_detect_source_language_config=auto_config,
                audio_config=audio_config,
            )
        else:
            speech_config.speech_recognition_language = provider_language(
                self.provider_id, language if not use_auto else (language_hints or ["en-US"])[0]
            )
            self._recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                audio_config=audio_config,
            )
        self._push_stream = push_stream
        self._last_audio_at = time.perf_counter()

        def recognizing_cb(evt):
            self._loop.call_soon_threadsafe(
                asyncio.create_task,
                self._handle_result(evt.result, False),
            )

        def recognized_cb(evt):
            self._loop.call_soon_threadsafe(
                asyncio.create_task,
                self._handle_result(evt.result, True),
            )

        def canceled_cb(evt):
            if evt.reason.name == "Error":
                from src.stt.models import ProviderStatus

                self._loop.call_soon_threadsafe(
                    asyncio.create_task,
                    self._emit_status(ProviderStatus.ERROR, evt.error_details or "Azure canceled"),
                )

        self._recognizer.recognizing.connect(recognizing_cb)
        self._recognizer.recognized.connect(recognized_cb)
        self._recognizer.canceled.connect(canceled_cb)
        self._recognizer.start_continuous_recognition_async()

    async def disconnect(self) -> None:
        if self._recognizer:
            self._recognizer.stop_continuous_recognition_async()
            self._recognizer = None
        if hasattr(self, "_push_stream"):
            self._push_stream.close()

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if hasattr(self, "_push_stream"):
            self._last_audio_at = time.perf_counter()
            self._push_stream.write(pcm_bytes)

    async def _handle_result(self, result, is_final: bool) -> None:
        text = (result.text or "").strip()
        if not text:
            return
        raw_conf = None
        try:
            import json

            details = json.loads(result.properties.get(
                __import__("azure.cognitiveservices.speech", fromlist=["PropertyId"]).PropertyId.SpeechServiceResponse_JsonResult,
                "{}",
            ))
            nbest = details.get("NBest") or []
            if nbest:
                raw_conf = nbest[0].get("Confidence")
        except Exception:
            pass

        update_type = TranscriptUpdateType.FINAL if is_final else TranscriptUpdateType.PARTIAL
        await self._emit_update(
            text,
            update_type,
            raw_conf,
            self._latency_since(self._last_audio_at),
        )
