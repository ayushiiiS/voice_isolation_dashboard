"""Tests for multi-provider STT orchestrator."""

from __future__ import annotations

import asyncio

import pytest

from src.stt.models import SelectionMode, SttSessionConfig
from src.stt.orchestrator import MultiProviderOrchestrator
from src.stt.providers.simulated import SimulatedSttProvider


@pytest.fixture
def config():
    return SttSessionConfig(
        enabled_providers=["deepgram", "azure", "openai"],
        selection_mode=SelectionMode.AUTO,
        hysteresis_threshold=5.0,
    )


@pytest.mark.asyncio
async def test_orchestrator_parallel_providers(config, monkeypatch):
    snapshots = []

    async def on_snapshot(snapshot):
        snapshots.append(snapshot)

    orchestrator = MultiProviderOrchestrator(config=config, on_snapshot=on_snapshot)

    def fake_create_enabled(enabled):
        return [
            SimulatedSttProvider("deepgram", "Deepgram", base_confidence=0.94, base_latency_ms=120),
            SimulatedSttProvider("azure", "Azure Speech", base_confidence=0.91, base_latency_ms=150),
            SimulatedSttProvider("openai", "OpenAI", provides_confidence=False, base_latency_ms=210),
        ]

    monkeypatch.setattr(
        "src.stt.orchestrator.ProviderRegistry.create_enabled",
        fake_create_enabled,
    )

    await orchestrator.start()
    await asyncio.sleep(0.1)

    pcm = b"\x00\x01" * 4096
    for _ in range(20):
        await orchestrator.send_audio(pcm)
        await asyncio.sleep(0.01)

    await asyncio.sleep(0.3)
    snapshot = orchestrator.current_snapshot()
    assert len(snapshot.providers) == 3
    assert all(not p.final_transcript for p in snapshot.providers)
    assert snapshots

    await orchestrator.stop()


@pytest.mark.asyncio
async def test_manual_selection_persists(config):
    orchestrator = MultiProviderOrchestrator(
        config=config.model_copy(
            update={"selection_mode": SelectionMode.MANUAL, "manual_provider": "azure"}
        )
    )

    def fake_create_enabled(enabled):
        return [
            SimulatedSttProvider("deepgram", "Deepgram", base_confidence=0.94),
            SimulatedSttProvider("azure", "Azure Speech", base_confidence=0.91),
        ]

    import src.stt.orchestrator as orch_mod

    original = orch_mod.ProviderRegistry.create_enabled
    orch_mod.ProviderRegistry.create_enabled = staticmethod(fake_create_enabled)
    try:
        await orchestrator.start()
        snapshot = orchestrator.current_snapshot()
        assert snapshot.selected_provider == "azure"
    finally:
        orch_mod.ProviderRegistry.create_enabled = original
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_feed_after_start_leaves_transcripts_blank(config, monkeypatch):
    orchestrator = MultiProviderOrchestrator(config=config)

    monkeypatch.setattr(
        "src.stt.orchestrator.ProviderRegistry.create_enabled",
        lambda enabled: [
            SimulatedSttProvider("deepgram", "Deepgram", base_confidence=0.94),
            SimulatedSttProvider("azure", "Azure Speech", base_confidence=0.91),
        ],
    )

    await orchestrator.start()
    assert orchestrator.ready_provider_count() == 2

    pcm = b"\x00\x01" * 3200
    for _ in range(12):
        await orchestrator.send_audio(pcm)

    await orchestrator.mark_feed_complete()
    snapshot = orchestrator.current_snapshot()
    assert all(not p.final_transcript for p in snapshot.providers)
    assert not snapshot.primary_transcript
    assert not snapshot.consensus_transcript
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_composite_score_uses_partial_transcript(config, monkeypatch):
    orchestrator = MultiProviderOrchestrator(config=config)

    monkeypatch.setattr(
        "src.stt.orchestrator.ProviderRegistry.create_enabled",
        lambda enabled: [
            SimulatedSttProvider("deepgram", "Deepgram", base_confidence=0.94),
            SimulatedSttProvider("azure", "Azure Speech", base_confidence=0.91),
        ],
    )

    await orchestrator.start()
    await orchestrator.set_audio_duration(30.0)

    async with orchestrator._lock:
        deepgram = orchestrator._states["deepgram"]
        deepgram.partial_transcript = "hello world this is a partial transcript"
        deepgram.normalized_confidence = 88.0

    await orchestrator._publish_snapshot()
    snapshot = orchestrator.current_snapshot()
    scored = next(p for p in snapshot.providers if p.provider == "deepgram")
    assert scored.composite_score is not None
    assert scored.ranking == 1
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_provider_failure_does_not_break_session(config, monkeypatch):
    class FailingProvider(SimulatedSttProvider):
        def __init__(self):
            super().__init__("deepgram", "Deepgram")

        async def connect(
            self,
            sample_rate: int,
            language: str,
            *,
            language_mode: str = "fixed",
            language_hints: list[str] | None = None,
        ):
            raise RuntimeError("connection failed")

    orchestrator = MultiProviderOrchestrator(config=SttSessionConfig(enabled_providers=["deepgram", "azure"]))

    monkeypatch.setattr(
        "src.stt.orchestrator.ProviderRegistry.create_enabled",
        lambda enabled: [
            FailingProvider(),
            SimulatedSttProvider("azure", "Azure Speech", base_confidence=0.91),
        ],
    )

    await orchestrator.start()
    await asyncio.sleep(0.15)
    snapshot = orchestrator.current_snapshot()
    deepgram = next(p for p in snapshot.providers if p.provider == "deepgram")
    azure = next(p for p in snapshot.providers if p.provider == "azure")
    assert deepgram.status.value in ("error", "connecting")
    assert azure.status.value == "active"
    await orchestrator.stop()
