"""Tests for simulated STT provider and registry."""

from __future__ import annotations

import asyncio

import pytest

from src.stt.providers.registry import ProviderRegistry
from src.stt.providers.simulated import SimulatedSttProvider


@pytest.mark.asyncio
async def test_simulated_provider_stays_blank():
    updates = []

    async def on_update(update):
        updates.append(update)

    async def on_status(status, error):
        pass

    provider = SimulatedSttProvider(
        "deepgram",
        "Deepgram",
        base_confidence=0.94,
        provides_confidence=True,
    )
    provider.set_callbacks(on_update, on_status)
    await provider.start(sample_rate=16000, language="en-US")

    pcm = b"\x00\x01" * 2048
    for _ in range(32):
        await provider.send_audio(pcm)

    await provider.flush()
    await provider.stop()

    assert updates == []


def test_registry_creates_simulated_when_unconfigured(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setenv("STT_ALLOW_SIMULATED", "true")
    provider = ProviderRegistry.create("deepgram")
    assert provider.is_simulated is True
    assert provider.provider_id == "deepgram"


def test_registry_all_provider_ids():
    ids = ProviderRegistry.available_provider_ids()
    assert set(ids) == {"deepgram", "azure", "sarvam"}


def test_registry_default_provider_ids():
    assert ProviderRegistry.default_provider_ids() == ["deepgram", "azure", "sarvam"]
