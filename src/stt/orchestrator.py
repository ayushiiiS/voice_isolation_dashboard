"""Multi-provider STT orchestrator — fans out audio and aggregates results."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Awaitable, Callable, Optional

from src.stt.base import SttProviderAdapter
from src.stt.consensus import build_consensus
from src.stt.models import (
    AudioQualityInfo,
    LanguageCandidateInfo,
    LanguageMode,
    ProviderScoreInfo,
    ProviderState,
    ProviderStatus,
    SttAudioSource,
    SttSessionConfig,
    SttSessionSnapshot,
    TranscriptMode,
    TranscriptUpdate,
    TranscriptUpdateType,
)
from src.stt.postprocess import postprocess_transcript
from src.stt.provider_scoring import rank_providers, score_provider
from src.stt.providers.registry import ProviderRegistry
from src.stt.selection import ProviderSelector

logger = logging.getLogger(__name__)

SnapshotCallback = Callable[[SttSessionSnapshot], Awaitable[None]]


def _effective_transcript(state: ProviderState) -> str:
    """Prefer final transcript; fall back to partial for live scoring."""
    return (state.final_transcript or state.partial_transcript or "").strip()


class MultiProviderOrchestrator:
    """Stream audio to all enabled providers and manage selection."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        config: Optional[SttSessionConfig] = None,
        on_snapshot: Optional[SnapshotCallback] = None,
    ) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.config = config or SttSessionConfig()
        self._on_snapshot = on_snapshot
        self._selector = ProviderSelector(self.config)
        self._providers: dict[str, SttProviderAdapter] = {}
        self._states: dict[str, ProviderState] = {}
        self._lock = asyncio.Lock()
        self._started = False
        self._feed_progress = 0.0
        self._feed_complete = False
        self._audio_duration_seconds = 0.0
        self._warnings: list[str] = []

    async def set_feed_progress(self, progress: float) -> None:
        async with self._lock:
            self._feed_progress = round(min(max(progress, 0.0), 1.0), 3)
        await self._publish_snapshot()

    async def mark_feed_complete(self) -> None:
        async with self._lock:
            self._feed_progress = 1.0
            self._feed_complete = True
        await self._flush_providers()
        await self._publish_snapshot()

    async def set_audio_duration(self, seconds: float) -> None:
        async with self._lock:
            self._audio_duration_seconds = seconds

    def add_warnings(self, warnings: list[str]) -> None:
        for warning in warnings:
            if warning not in self._warnings:
                self._warnings.append(warning)

    async def start(self) -> None:
        if self._started:
            return

        adapters = ProviderRegistry.create_enabled(self.config.enabled_providers)
        language_mode = (
            self.config.language_mode.value
            if hasattr(self.config.language_mode, "value")
            else str(self.config.language_mode)
        )
        connect_tasks: list[asyncio.Task] = []
        for adapter in adapters:
            pid = adapter.provider_id
            self._providers[pid] = adapter
            self._states[pid] = ProviderState(
                provider=pid,
                display_name=adapter.display_name,
                status=ProviderStatus.CONNECTING,
                is_simulated=adapter.is_simulated,
                metrics=adapter.get_metrics(),
            )
            adapter.set_callbacks(
                lambda update, p=pid: self._handle_update(p, update),
                lambda status, error, p=pid: self._handle_status(p, status, error),
            )
            connect_tasks.append(
                asyncio.create_task(
                    adapter.start(
                        self.config.sample_rate,
                        self.config.language,
                        language_mode=language_mode,
                        language_hints=self.config.language_hints,
                    )
                )
            )

        self._started = True
        if connect_tasks:
            await asyncio.gather(*connect_tasks, return_exceptions=True)
        await self._publish_snapshot()

    def ready_provider_count(self) -> int:
        return sum(1 for provider in self._providers.values() if provider.is_connected)

    async def stop(self) -> None:
        await self._flush_providers()
        tasks = [provider.stop() for provider in self._providers.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._started = False

    async def update_config(self, config: SttSessionConfig) -> None:
        async with self._lock:
            self.config = config
            self._selector.update_config(config)
        await self._publish_snapshot()

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not self._started:
            return
        tasks = [
            provider.send_audio(pcm_bytes)
            for provider in self._providers.values()
            if provider.is_connected
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _flush_providers(self) -> None:
        tasks = [provider.flush() for provider in self._providers.values() if provider.is_connected]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.5)

    async def _handle_update(self, provider_id: str, update: TranscriptUpdate) -> None:
        async with self._lock:
            state = self._states.get(provider_id)
            if not state:
                return
            adapter = self._providers[provider_id]
            if update.update_type == TranscriptUpdateType.PARTIAL:
                state.partial_transcript = update.text
            else:
                state.final_transcript = (
                    f"{state.final_transcript} {update.text}".strip()
                    if state.final_transcript
                    else update.text
                )
                state.partial_transcript = ""
            state.raw_confidence = update.raw_confidence
            state.normalized_confidence = update.normalized_confidence
            state.latency_ms = update.latency_ms
            state.metrics = adapter.get_metrics()
        await self._publish_snapshot()

    async def _handle_status(
        self,
        provider_id: str,
        status: ProviderStatus,
        error: Optional[str],
    ) -> None:
        async with self._lock:
            state = self._states.get(provider_id)
            if not state:
                return
            state.status = status
            state.error = error
            adapter = self._providers.get(provider_id)
            if adapter:
                state.metrics = adapter.get_metrics()
        await self._publish_snapshot()

    def _build_snapshot_fields(self, providers: list[ProviderState]) -> dict:
        raw_transcripts = {
            p.provider: transcript
            for p in providers
            if (transcript := _effective_transcript(p))
        }
        max_words = max((len(t.split()) for t in raw_transcripts.values()), default=0)

        provider_scores = []
        for provider in providers:
            if not raw_transcripts.get(provider.provider):
                continue
            scored = score_provider(
                provider=provider.provider,
                transcript=raw_transcripts[provider.provider],
                normalized_confidence=provider.normalized_confidence,
                audio_duration_seconds=self._audio_duration_seconds,
                detected_language=self.config.detected_language,
                expected_language=self.config.language if self.config.language != "auto" else None,
                max_word_count=max_words,
            )
            provider.composite_score = scored.composite
            provider_scores.append(ProviderScoreInfo(**scored.to_dict()))

        ranked_scores = rank_providers(
            [
                score_provider(
                    provider=p.provider,
                    transcript=raw_transcripts[p.provider],
                    normalized_confidence=p.normalized_confidence,
                    audio_duration_seconds=self._audio_duration_seconds,
                    detected_language=self.config.detected_language,
                    expected_language=self.config.language if self.config.language != "auto" else None,
                    max_word_count=max_words,
                )
                for p in providers
                if raw_transcripts.get(p.provider)
            ]
        )
        for idx, scored in enumerate(ranked_scores, start=1):
            for provider in providers:
                if provider.provider == scored.provider:
                    provider.composite_score = scored.composite
                    provider.ranking = idx

        selected, auto_selected, best_score = self._selector.select(providers)
        ranked = sorted([p for p in providers if p.ranking > 0], key=lambda p: p.ranking)
        best_provider = ranked[0].provider if ranked else None

        weights = {s.provider: s.composite for s in ranked_scores}
        consensus = build_consensus(raw_transcripts, provider_weights=weights)
        consensus_text = postprocess_transcript(consensus.text)

        primary_raw = ""
        if self.config.transcript_mode == TranscriptMode.CONSENSUS and consensus_text:
            primary_raw = consensus.text
            primary = consensus_text
        elif selected:
            sel_state = self._states.get(selected)
            if sel_state:
                primary_raw = sel_state.final_transcript
                if sel_state.partial_transcript:
                    primary_raw = f"{primary_raw} {sel_state.partial_transcript}".strip()
                primary = postprocess_transcript(primary_raw)
            else:
                primary = ""
        else:
            primary = consensus_text or ""

        warnings = list(self._warnings)
        if (
            self.config.language_confidence is not None
            and self.config.language_confidence <= float(os.getenv("STT_LANGUAGE_CONFIDENCE_THRESHOLD", "0.80"))
            and self.config.language_mode == LanguageMode.MULTILINGUAL
        ):
            warnings.append("Low language confidence — using multilingual auto-detect mode.")
        if self.config.audio_quality and self.config.audio_quality.score < 60:
            warnings.append("Audio quality degraded — check isolation or clipping.")
        for provider in providers:
            if provider.normalized_confidence is not None and provider.composite_score is not None:
                conf_norm = provider.normalized_confidence / 100.0
                if abs(conf_norm - provider.composite_score) > 0.35:
                    warnings.append(f"Provider confidence mismatch for {provider.display_name}.")

        return {
            "selected_provider": selected,
            "auto_selected_provider": auto_selected,
            "best_provider": best_provider,
            "best_confidence": self._selector._best_display_score(
                next((p for p in providers if p.ranking == 1), None)
            ),
            "primary_transcript": primary,
            "consensus_transcript": consensus_text,
            "processed_transcript": primary,
            "provider_scores": provider_scores,
            "provider_raw_transcripts": raw_transcripts,
            "warnings": warnings,
        }

    async def _publish_snapshot(self) -> None:
        async with self._lock:
            providers = list(self._states.values())
            fields = self._build_snapshot_fields(providers)
            snapshot = SttSessionSnapshot(
                session_id=self.session_id,
                selection_mode=self.config.selection_mode,
                providers=providers,
                source=self.config.source,
                recording_id=self.config.recording_id,
                recording_file_name=self.config.recording_file_name,
                user_audio_url=self.config.user_audio_url,
                feed_progress=self._feed_progress,
                feed_complete=self._feed_complete,
                language=self.config.language,
                detected_language=self.config.detected_language,
                language_code=self.config.language_code,
                language_confidence=self.config.language_confidence,
                language_detection_method=self.config.language_detection_method,
                language_mode=self.config.language_mode,
                language_candidates=self.config.language_candidates,
                language_hints=self.config.language_hints,
                transcript_mode=self.config.transcript_mode,
                audio_source_type=self.config.audio_source_type,
                audio_quality=self.config.audio_quality,
                updated_at=datetime.utcnow(),
                **fields,
            )

        if self._on_snapshot:
            await self._on_snapshot(snapshot)

    def current_snapshot(self) -> SttSessionSnapshot:
        providers = list(self._states.values())
        fields = self._build_snapshot_fields(providers)
        return SttSessionSnapshot(
            session_id=self.session_id,
            selection_mode=self.config.selection_mode,
            providers=providers,
            source=self.config.source,
            recording_id=self.config.recording_id,
            recording_file_name=self.config.recording_file_name,
            user_audio_url=self.config.user_audio_url,
            feed_progress=self._feed_progress,
            feed_complete=self._feed_complete,
            language=self.config.language,
            detected_language=self.config.detected_language,
            language_code=self.config.language_code,
            language_confidence=self.config.language_confidence,
            language_detection_method=self.config.language_detection_method,
            language_mode=self.config.language_mode,
            language_candidates=self.config.language_candidates,
            language_hints=self.config.language_hints,
            transcript_mode=self.config.transcript_mode,
            audio_source_type=self.config.audio_source_type,
            audio_quality=self.config.audio_quality,
            updated_at=datetime.utcnow(),
            **fields,
        )

    def provider_metrics(self) -> list:
        return [p.get_metrics() for p in self._providers.values()]
