"""Per-provider metrics tracking during a streaming session."""

from __future__ import annotations

import time
from typing import Optional

from src.stt.models import ProviderMetrics, TranscriptUpdate


class MetricsTracker:
    """Track confidence, latency, errors, and uptime per provider."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self._confidence_samples: list[float] = []
        self._latency_samples: list[float] = []
        self._error_count = 0
        self._reconnect_count = 0
        self._transcript_count = 0
        self._last_error: Optional[str] = None
        self._connected_at: Optional[float] = None
        self._disconnected_at: Optional[float] = None
        self._total_uptime = 0.0
        self._current_confidence: Optional[float] = None
        self._current_latency = 0.0

    def mark_connected(self) -> None:
        if self._connected_at is None:
            self._connected_at = time.monotonic()

    def mark_disconnected(self) -> None:
        if self._connected_at is not None:
            self._total_uptime += time.monotonic() - self._connected_at
            self._connected_at = None
        self._disconnected_at = time.monotonic()

    def mark_reconnect(self) -> None:
        self._reconnect_count += 1
        self.mark_connected()

    def record_error(self, message: str) -> None:
        self._error_count += 1
        self._last_error = message

    def record_update(self, update: TranscriptUpdate) -> None:
        self._transcript_count += 1
        self._current_latency = update.latency_ms
        self._latency_samples.append(update.latency_ms)
        if update.normalized_confidence is not None:
            self._current_confidence = update.normalized_confidence
            self._confidence_samples.append(update.normalized_confidence)

    def snapshot(self) -> ProviderMetrics:
        uptime = self._total_uptime
        if self._connected_at is not None:
            uptime += time.monotonic() - self._connected_at

        avg_conf = (
            sum(self._confidence_samples) / len(self._confidence_samples)
            if self._confidence_samples
            else None
        )
        avg_lat = (
            sum(self._latency_samples) / len(self._latency_samples)
            if self._latency_samples
            else 0.0
        )
        return ProviderMetrics(
            provider=self.provider,
            current_confidence=self._current_confidence,
            average_confidence=round(avg_conf, 2) if avg_conf is not None else None,
            current_latency_ms=round(self._current_latency, 2),
            average_latency_ms=round(avg_lat, 2),
            error_count=self._error_count,
            reconnect_count=self._reconnect_count,
            uptime_seconds=round(uptime, 2),
            transcript_count=self._transcript_count,
            last_error=self._last_error,
        )
