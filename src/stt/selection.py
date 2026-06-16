"""Auto/manual provider selection with composite scoring and hysteresis."""

from __future__ import annotations

from typing import Optional

from src.stt.models import ProviderState, ProviderStatus, SelectionMode, SttSessionConfig


class ProviderSelector:
    """Select primary transcript source with composite-score ranking."""

    def __init__(self, config: SttSessionConfig) -> None:
        self.config = config
        self._auto_selected: Optional[str] = None

    def update_config(self, config: SttSessionConfig) -> None:
        self.config = config

    @property
    def auto_selected_provider(self) -> Optional[str]:
        return self._auto_selected

    def select(
        self,
        providers: list[ProviderState],
    ) -> tuple[Optional[str], Optional[str], Optional[float]]:
        """Return (selected_provider, auto_selected_provider, best_composite_score)."""
        ranked = self._rank_providers(providers)
        best = ranked[0] if ranked else None
        best_name = best.provider if best else None
        best_score = self._best_display_score(best)

        if self.config.selection_mode == SelectionMode.MANUAL:
            manual = self.config.manual_provider
            if manual and any(p.provider == manual for p in providers):
                return manual, self._auto_selected, best_score
            self._auto_selected = self._apply_hysteresis(ranked)
            return self._auto_selected, self._auto_selected, best_score

        self._auto_selected = self._apply_hysteresis(ranked)
        return self._auto_selected, self._auto_selected, best_score

    def _best_display_score(self, provider: Optional[ProviderState]) -> Optional[float]:
        if not provider:
            return None
        if provider.composite_score is not None:
            return round(provider.composite_score * 100.0, 2)
        return provider.normalized_confidence

    def _rank_providers(self, providers: list[ProviderState]) -> list[ProviderState]:
        active = [
            p
            for p in providers
            if p.status in (ProviderStatus.ACTIVE, ProviderStatus.DEGRADED)
            and (p.composite_score is not None or p.normalized_confidence is not None)
        ]
        active.sort(
            key=lambda p: (
                -(p.composite_score if p.composite_score is not None else (p.normalized_confidence or 0) / 100.0),
                p.latency_ms,
            )
        )
        for idx, provider in enumerate(active, start=1):
            provider.ranking = idx
        return active

    def _apply_hysteresis(self, ranked: list[ProviderState]) -> Optional[str]:
        if not ranked:
            return self._auto_selected

        best = ranked[0]
        if self._auto_selected is None:
            return best.provider

        current = next((p for p in ranked if p.provider == self._auto_selected), None)
        if current is None:
            return best.provider

        best_score = best.composite_score if best.composite_score is not None else (best.normalized_confidence or 0) / 100.0
        current_score = (
            current.composite_score
            if current.composite_score is not None
            else (current.normalized_confidence or 0) / 100.0
        )
        gap = (best_score - current_score) * 100.0
        if gap >= self.config.hysteresis_threshold:
            return best.provider
        return self._auto_selected
