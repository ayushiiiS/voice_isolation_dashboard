"""Tests for auto/manual provider selection with hysteresis."""

from __future__ import annotations

from src.stt.models import ProviderState, ProviderStatus, SelectionMode, SttSessionConfig
from src.stt.selection import ProviderSelector


def _provider(name: str, confidence: float) -> ProviderState:
    return ProviderState(
        provider=name,
        display_name=name.title(),
        status=ProviderStatus.ACTIVE,
        normalized_confidence=confidence,
        latency_ms=100.0,
    )


def test_auto_selects_highest_confidence():
    selector = ProviderSelector(SttSessionConfig(selection_mode=SelectionMode.AUTO))
    selected, auto, best = selector.select(
        [_provider("azure", 91), _provider("deepgram", 94)]
    )
    assert selected == "deepgram"
    assert auto == "deepgram"
    assert best == 94.0


def test_hysteresis_prevents_rapid_switching():
    config = SttSessionConfig(selection_mode=SelectionMode.AUTO, hysteresis_threshold=5.0)
    selector = ProviderSelector(config)
    providers = [_provider("deepgram", 94), _provider("azure", 91)]

    selected1, _, _ = selector.select(providers)
    assert selected1 == "deepgram"

    # Azure improves but gap is only 2 points — should stay on Deepgram.
    providers = [_provider("deepgram", 94), _provider("azure", 96)]
    selected2, _, _ = selector.select(providers)
    assert selected2 == "deepgram"

    # Gap exceeds threshold — switch to Azure.
    providers = [_provider("deepgram", 94), _provider("azure", 99.5)]
    selected3, _, _ = selector.select(providers)
    assert selected3 == "azure"


def test_manual_override():
    config = SttSessionConfig(
        selection_mode=SelectionMode.MANUAL,
        manual_provider="azure",
    )
    selector = ProviderSelector(config)
    selected, auto, best = selector.select(
        [_provider("deepgram", 94), _provider("azure", 91)]
    )
    assert selected == "azure"
    assert best == 94.0


def test_ranking_order():
    selector = ProviderSelector(SttSessionConfig())
    providers = [
        _provider("openai", 89),
        _provider("deepgram", 94),
        _provider("google", 86),
    ]
    selector.select(providers)
    deepgram = next(p for p in providers if p.provider == "deepgram")
    google = next(p for p in providers if p.provider == "google")
    assert deepgram.ranking == 1
    assert google.ranking == 3
