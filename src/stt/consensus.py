"""Generate consensus transcript from multiple provider outputs."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class ConsensusResult:
    text: str
    agreement_ratio: float
    provider_contributions: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "agreement_ratio": round(self.agreement_ratio, 4),
            "provider_contributions": {
                k: round(v, 4) for k, v in self.provider_contributions.items()
            },
        }


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\S+", (text or "").strip())


def _normalize_token(token: str) -> str:
    return token.lower().strip(".,!?;:'\"")


def build_consensus(
    provider_texts: dict[str, str],
    *,
    provider_weights: dict[str, float] | None = None,
) -> ConsensusResult:
    """Weighted majority voting at token level across provider transcripts."""
    if not provider_texts:
        return ConsensusResult(text="", agreement_ratio=0.0, provider_contributions={})

    weights = provider_weights or {name: 1.0 for name in provider_texts}
    token_lists = {name: _tokenize(text) for name, text in provider_texts.items() if text.strip()}
    if not token_lists:
        return ConsensusResult(text="", agreement_ratio=0.0, provider_contributions={})

    max_len = max(len(tokens) for tokens in token_lists.values())
    chosen: list[str] = []
    agreements: list[float] = []

    for idx in range(max_len):
        votes: Counter[str] = Counter()
        display: dict[str, str] = {}
        for name, tokens in token_lists.items():
            if idx >= len(tokens):
                continue
            raw = tokens[idx]
            norm = _normalize_token(raw)
            votes[norm] += weights.get(name, 1.0)
            display.setdefault(norm, raw)

        if not votes:
            continue
        winner_norm, winner_votes = votes.most_common(1)[0]
        total_votes = sum(votes.values())
        agreements.append(winner_votes / total_votes if total_votes else 0.0)
        chosen.append(display[winner_norm])

    consensus_text = " ".join(chosen)
    agreement_ratio = sum(agreements) / len(agreements) if agreements else 0.0

    contributions: dict[str, float] = {}
    for name, tokens in token_lists.items():
        if not tokens:
            contributions[name] = 0.0
            continue
        matches = 0
        for idx, token in enumerate(tokens):
            if idx < len(chosen) and _normalize_token(token) == _normalize_token(chosen[idx]):
                matches += 1
        contributions[name] = matches / max(len(tokens), 1)

    # If one provider is much longer and others agree on a substring, prefer longest high-similarity.
    if len(token_lists) >= 2:
        texts = list(provider_texts.values())
        best = max(texts, key=lambda t: SequenceMatcher(None, consensus_text, t).ratio())
        if SequenceMatcher(None, consensus_text, best).ratio() > 0.85 and len(best) > len(consensus_text):
            consensus_text = best.strip()

    return ConsensusResult(
        text=consensus_text,
        agreement_ratio=agreement_ratio,
        provider_contributions=contributions,
    )
