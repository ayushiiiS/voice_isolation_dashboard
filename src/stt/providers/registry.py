"""STT provider registry and factory."""

from __future__ import annotations

import logging
import os
from typing import Type

from src.stt.base import SttProviderAdapter
from src.stt.providers.aws_transcribe import AwsTranscribeProvider
from src.stt.providers.azure import AzureSpeechProvider
from src.stt.providers.deepgram import DeepgramProvider
from src.stt.providers.google_stt import GoogleSttProvider
from src.stt.providers.openai import OpenAiSttProvider
from src.stt.providers.simulated import SimulatedSttProvider

logger = logging.getLogger(__name__)

SIMULATED_PROFILES = {
    "deepgram": dict(base_confidence=0.94, base_latency_ms=120.0, provides_confidence=True),
    "azure": dict(base_confidence=0.91, base_latency_ms=150.0, provides_confidence=True),
    "openai": dict(base_confidence=0.89, base_latency_ms=210.0, provides_confidence=False),
    "google": dict(base_confidence=0.86, base_latency_ms=180.0, provides_confidence=False),
    "aws": dict(base_confidence=0.88, base_latency_ms=195.0, provides_confidence=False),
}

REAL_PROVIDERS: dict[str, Type[SttProviderAdapter]] = {
    "deepgram": DeepgramProvider,
    "azure": AzureSpeechProvider,
    "openai": OpenAiSttProvider,
    "google": GoogleSttProvider,
    "aws": AwsTranscribeProvider,
}

DISPLAY_NAMES = {
    "deepgram": "Deepgram",
    "azure": "Azure Speech",
    "openai": "OpenAI",
    "google": "Google STT",
    "aws": "AWS Transcribe",
}


class ProviderRegistry:
    """Resolve enabled providers to real or simulated adapters."""

    @staticmethod
    def available_provider_ids() -> list[str]:
        return list(REAL_PROVIDERS.keys())

    @staticmethod
    def create(provider_id: str) -> SttProviderAdapter:
        provider_id = provider_id.lower()
        if provider_id not in REAL_PROVIDERS:
            raise ValueError(f"Unknown STT provider: {provider_id}")

        real_cls = REAL_PROVIDERS[provider_id]
        allow_simulated = os.getenv("STT_ALLOW_SIMULATED", "true").lower() == "true"

        if real_cls.is_configured():
            logger.info("Using real STT provider: %s", provider_id)
            return real_cls()

        if allow_simulated:
            profile = SIMULATED_PROFILES.get(provider_id, {})
            logger.info("Using simulated STT provider: %s", provider_id)
            return SimulatedSttProvider(
                provider_id=provider_id,
                display_name=DISPLAY_NAMES[provider_id],
                **profile,
            )

        unavailable = _UnavailableProvider(provider_id, DISPLAY_NAMES[provider_id])
        return unavailable

    @staticmethod
    def create_enabled(enabled: list[str]) -> list[SttProviderAdapter]:
        return [ProviderRegistry.create(pid) for pid in enabled]


class _UnavailableProvider(SttProviderAdapter):
    """Placeholder when provider is not configured and simulation is disabled."""

    is_simulated = False

    def __init__(self, provider_id: str, display_name: str) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        super().__init__()

    @classmethod
    def is_configured(cls) -> bool:
        return False

    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        from src.stt.models import ProviderStatus

        raise RuntimeError(f"{self.display_name} is not configured")

    async def send_audio(self, pcm_bytes: bytes) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def start(self, sample_rate: int, language: str) -> None:
        from src.stt.models import ProviderStatus

        await self._emit_status(
            ProviderStatus.UNAVAILABLE,
            f"{self.display_name} requires API credentials",
        )
