"""Placeholder STT provider when real API credentials are not configured."""

from __future__ import annotations

import asyncio

from src.stt.base import SttProviderAdapter


class SimulatedSttProvider(SttProviderAdapter):
    """Connects and accepts audio but does not emit fake transcripts."""

    is_simulated = True

    def __init__(
        self,
        provider_id: str,
        display_name: str,
        *,
        base_confidence: float = 0.9,
        base_latency_ms: float = 150.0,
        confidence_jitter: float = 0.05,
        latency_jitter_ms: float = 40.0,
        provides_confidence: bool = True,
        emit_every_n_chunks: int = 4,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        super().__init__()
        # Kept for registry profile compatibility; unused without real STT credentials.
        self._base_confidence = base_confidence
        self._base_latency_ms = base_latency_ms
        self._confidence_jitter = confidence_jitter
        self._latency_jitter_ms = latency_jitter_ms
        self._provides_confidence = provides_confidence

    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        await asyncio.sleep(0.05)

    @classmethod
    def is_configured(cls) -> bool:
        return True

    async def disconnect(self) -> None:
        await asyncio.sleep(0.01)

    async def send_audio(self, pcm_bytes: bytes) -> None:
        return None

    async def flush(self) -> None:
        return None
