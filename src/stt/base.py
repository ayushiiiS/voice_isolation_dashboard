"""Provider-agnostic STT adapter interface."""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from src.stt.metrics import MetricsTracker
from src.stt.models import ProviderStatus, TranscriptUpdate, TranscriptUpdateType
from src.stt.normalization import normalize_confidence

logger = logging.getLogger(__name__)

UpdateCallback = Callable[[TranscriptUpdate], Awaitable[None]]
StatusCallback = Callable[[ProviderStatus, Optional[str]], Awaitable[None]]


class SttProviderAdapter(abc.ABC):
    """Contract implemented by all STT providers."""

    provider_id: str
    display_name: str
    is_simulated: bool = False

    def __init__(self) -> None:
        self._on_update: Optional[UpdateCallback] = None
        self._on_status: Optional[StatusCallback] = None
        self._metrics = MetricsTracker(self.provider_id)
        self._connected = False
        self._retry_attempts = 3
        self._retry_delay = 1.0

    def set_callbacks(
        self,
        on_update: UpdateCallback,
        on_status: StatusCallback,
    ) -> None:
        self._on_update = on_update
        self._on_status = on_status

    @classmethod
    @abc.abstractmethod
    def is_configured(cls) -> bool:
        """Return True when API credentials/env are present."""

    @abc.abstractmethod
    async def connect(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        """Establish streaming connection to the provider."""

    @abc.abstractmethod
    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Send PCM16 mono audio chunk."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close provider connection."""

    async def start(
        self,
        sample_rate: int,
        language: str,
        *,
        language_mode: str = "fixed",
        language_hints: list[str] | None = None,
    ) -> None:
        """Connect with retries."""
        self._language_mode = language_mode
        self._language_hints = language_hints or []
        await self._emit_status(ProviderStatus.CONNECTING, None)
        for attempt in range(1, self._retry_attempts + 1):
            try:
                await self.connect(sample_rate, language, language_mode=language_mode, language_hints=language_hints)
                self._connected = True
                self._metrics.mark_connected()
                await self._emit_status(ProviderStatus.ACTIVE, None)
                return
            except Exception as exc:
                logger.warning(
                    "%s connect attempt %d/%d failed: %s",
                    self.provider_id,
                    attempt,
                    self._retry_attempts,
                    exc,
                )
                self._metrics.record_error(str(exc))
                if attempt < self._retry_attempts:
                    await asyncio.sleep(self._retry_delay * attempt)
                else:
                    await self._emit_status(ProviderStatus.ERROR, str(exc))

    async def flush(self) -> None:
        """Optional end-of-stream flush for providers that buffer audio."""
        return None

    async def stop(self) -> None:
        if self._connected:
            try:
                await self.disconnect()
            except Exception as exc:
                logger.warning("%s disconnect error: %s", self.provider_id, exc)
            self._connected = False
            self._metrics.mark_disconnected()
            await self._emit_status(ProviderStatus.DISCONNECTED, None)

    def get_metrics(self):
        return self._metrics.snapshot()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _emit_update(
        self,
        text: str,
        update_type: TranscriptUpdateType,
        raw_confidence: Optional[float],
        latency_ms: float,
    ) -> None:
        normalized = normalize_confidence(self.provider_id, raw_confidence)
        update = TranscriptUpdate(
            provider=self.provider_id,
            update_type=update_type,
            text=text,
            raw_confidence=raw_confidence,
            normalized_confidence=normalized,
            latency_ms=latency_ms,
            is_final=update_type == TranscriptUpdateType.FINAL,
        )
        self._metrics.record_update(update)
        if self._on_update:
            await self._on_update(update)

    async def _emit_status(self, status: ProviderStatus, error: Optional[str]) -> None:
        if error:
            self._metrics.record_error(error)
        if self._on_status:
            await self._on_status(status, error)

    @staticmethod
    def _latency_since(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)
