"""Identify human vs Blue Machines AI agent speakers."""

from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from typing import Optional

import numpy as np

from src.diarization.models import (
    AgentTranscriptEntry,
    IdentificationStrategy,
    SpeakerIdentification,
    SpeakerSegment,
)

logger = logging.getLogger(__name__)

SHORT_UTTERANCE_SEC = float(os.getenv("ISOLATION_SHORT_UTTERANCE_SEC", "0.8"))
LONG_UTTERANCE_SEC = float(os.getenv("ISOLATION_LONG_UTTERANCE_SEC", "2.0"))
BACKCHANNEL_SHORT_RATIO = float(os.getenv("ISOLATION_BACKCHANNEL_RATIO", "0.45"))


class SpeakerSelector:
    """Select human speaker by identifying and excluding the agent."""

    def identify(
        self,
        segments: list[SpeakerSegment],
        agent_transcript: Optional[list[AgentTranscriptEntry | str]] = None,
        agent_reference_audio_path: Optional[str] = None,
        speaker_embeddings: Optional[dict[str, np.ndarray]] = None,
    ) -> SpeakerIdentification:
        speakers = sorted({s.speaker for s in segments})

        if len(speakers) < 2:
            raise ValueError(
                f"Expected 2 speakers (human + agent), found {len(speakers)}: {speakers}"
            )
        if len(speakers) > 2:
            logger.warning(
                "Found %d speakers; using top-2 by total speech duration", len(speakers)
            )
            speakers = self._top_speakers_by_duration(segments, limit=2)

        stats = self._compute_speaker_stats(segments, speakers)

        transcript_entries = self._normalize_transcript(agent_transcript)

        if transcript_entries and self._has_timestamps(transcript_entries):
            result = self._identify_by_transcript(segments, speakers, transcript_entries, stats)
            if result.confidence >= 0.6:
                logger.info(
                    "Agent identified via transcript match: %s (confidence=%.2f)",
                    result.agent_speaker,
                    result.confidence,
                )
                return result

        if agent_reference_audio_path:
            result = self._identify_by_reference_audio(
                agent_reference_audio_path,
                speakers,
                stats,
                speaker_embeddings,
            )
            if result.confidence >= 0.65:
                logger.info(
                    "Agent identified via reference audio: %s (confidence=%.2f)",
                    result.agent_speaker,
                    result.confidence,
                )
                return result

        result = self._identify_by_call_patterns(segments, speakers, stats, transcript_entries)
        logger.info(
            "Agent identified via call patterns: %s human=%s (confidence=%.2f)",
            result.agent_speaker,
            result.human_speaker,
            result.confidence,
        )
        return result

    @staticmethod
    def _normalize_transcript(
        entries: Optional[list[AgentTranscriptEntry | str]],
    ) -> list[AgentTranscriptEntry]:
        if not entries:
            return []

        normalized: list[AgentTranscriptEntry] = []
        for entry in entries:
            if isinstance(entry, str):
                normalized.append(AgentTranscriptEntry(text=entry))
            else:
                normalized.append(entry)
        return normalized

    @staticmethod
    def _has_timestamps(entries: list[AgentTranscriptEntry]) -> bool:
        return any(e.start is not None and e.end is not None for e in entries)

    @staticmethod
    def _top_speakers_by_duration(
        segments: list[SpeakerSegment], limit: int
    ) -> list[str]:
        durations: dict[str, float] = defaultdict(float)
        for seg in segments:
            durations[seg.speaker] += seg.duration

        ranked = sorted(durations.items(), key=lambda x: x[1], reverse=True)
        return [speaker for speaker, _ in ranked[:limit]]

    @staticmethod
    def _compute_speaker_stats(
        segments: list[SpeakerSegment], speakers: list[str]
    ) -> dict[str, dict]:
        stats: dict[str, dict] = {s: defaultdict(float) for s in speakers}
        turn_order: list[str] = []

        for seg in segments:
            if seg.speaker not in stats:
                continue
            stats[seg.speaker]["total_duration"] += seg.duration
            stats[seg.speaker]["segment_count"] += 1
            stats[seg.speaker]["duration_sum_sq"] += seg.duration ** 2
            if seg.duration < SHORT_UTTERANCE_SEC:
                stats[seg.speaker]["short_segment_count"] += 1
            if seg.duration >= LONG_UTTERANCE_SEC:
                stats[seg.speaker]["long_segment_count"] += 1
            turn_order.append(seg.speaker)

        for speaker in speakers:
            count = int(stats[speaker]["segment_count"])
            total = stats[speaker]["total_duration"]
            stats[speaker]["avg_segment_duration"] = total / count if count else 0.0
            stats[speaker]["short_segment_ratio"] = (
                stats[speaker]["short_segment_count"] / count if count else 0.0
            )
            stats[speaker]["long_segment_ratio"] = (
                stats[speaker]["long_segment_count"] / count if count else 0.0
            )

            if count > 1:
                mean = stats[speaker]["avg_segment_duration"]
                variance = (stats[speaker]["duration_sum_sq"] / count) - (mean ** 2)
                stats[speaker]["segment_duration_std"] = math.sqrt(max(variance, 0.0))
            else:
                stats[speaker]["segment_duration_std"] = 0.0

        stats["_turn_order"] = turn_order
        return stats

    @staticmethod
    def _short_segment_ratio(segments: list[SpeakerSegment], speaker: str) -> float:
        speaker_segs = [s for s in segments if s.speaker == speaker]
        if not speaker_segs:
            return 0.0
        short = sum(1 for s in speaker_segs if s.duration < SHORT_UTTERANCE_SEC)
        return short / len(speaker_segs)

    def _identify_by_call_patterns(
        self,
        segments: list[SpeakerSegment],
        speakers: list[str],
        stats: dict[str, dict],
        transcript: list[AgentTranscriptEntry],
    ) -> SpeakerIdentification:
        """
        Identify speakers using voice-agent call patterns.

        Two common layouts:
        1. Agent-led scripted call — agent long monologues, user short backchannels
           ("haan", "ok", "ji"). The user has a high short-utterance ratio.
        2. User-led inbound call — user longer explanations, agent brief replies.
           Talk-time is dominated by the user without a backchannel split.
        """
        short_ratios = {s: self._short_segment_ratio(segments, s) for s in speakers}
        durations = {
            s: stats[s].get("total_duration", 0.0) for s in speakers if s in stats
        }

        logger.info(
            "Speaker stats: %s",
            {
                s: {
                    "dur": round(durations.get(s, 0.0), 1),
                    "short_ratio": round(short_ratios[s], 2),
                    "long_ratio": round(stats[s].get("long_segment_ratio", 0.0), 2),
                    "avg_seg": round(stats[s].get("avg_segment_duration", 0.0), 2),
                }
                for s in speakers
            },
        )

        user_candidate = max(short_ratios, key=short_ratios.get)
        agent_candidate = min(short_ratios, key=short_ratios.get)
        ratio_gap = short_ratios[user_candidate] - short_ratios[agent_candidate]

        if (
            short_ratios[user_candidate] >= BACKCHANNEL_SHORT_RATIO
            and ratio_gap >= 0.20
        ):
            human_speaker = user_candidate
            agent_speaker = agent_candidate
            confidence = min(0.70 + ratio_gap * 0.5, 0.92)
            strategy = IdentificationStrategy.HEURISTICS
            logger.info(
                "Backchannel pattern detected: user=%s (%.0f%% short segs)",
                human_speaker,
                short_ratios[user_candidate] * 100,
            )
        elif durations:
            human_speaker = max(durations, key=durations.get)
            agent_speaker = min(durations, key=durations.get)
            dur_total = sum(durations.values()) or 1.0
            dur_gap = abs(durations[human_speaker] - durations[agent_speaker]) / dur_total
            confidence = min(0.60 + dur_gap * 0.4, 0.85)
            strategy = IdentificationStrategy.HEURISTICS
            logger.info(
                "Talk-time pattern: user=%s (%.1fs vs agent %.1fs)",
                human_speaker,
                durations[human_speaker],
                durations[agent_speaker],
            )
        else:
            scores = self._score_agent_likelihood(segments, speakers, stats, transcript)
            agent_speaker = max(scores, key=scores.get)
            human_speaker = [s for s in speakers if s != agent_speaker][0]
            confidence = 0.55
            strategy = IdentificationStrategy.HEURISTICS

        return SpeakerIdentification(
            human_speaker=human_speaker,
            agent_speaker=agent_speaker,
            confidence=round(confidence, 3),
            strategy=strategy,
            speaker_stats={k: v for k, v in stats.items() if not k.startswith("_")},
        )

    def _score_agent_likelihood(
        self,
        segments: list[SpeakerSegment],
        speakers: list[str],
        stats: dict[str, dict],
        transcript: list[AgentTranscriptEntry],
    ) -> dict[str, float]:
        """Fallback scoring when primary patterns are ambiguous."""
        scores: dict[str, float] = {s: 0.0 for s in speakers}

        for speaker in speakers:
            scores[speaker] += stats[speaker].get("long_segment_ratio", 0.0) * 0.35
            scores[speaker] += stats[speaker].get("avg_segment_duration", 0.0) * 0.10
            scores[speaker] += (1.0 - stats[speaker].get("short_segment_ratio", 0.0)) * 0.25

        response_scores = self._score_response_pattern(segments, speakers)
        for speaker, score in response_scores.items():
            scores[speaker] += score * 0.10

        if transcript and not self._has_timestamps(transcript):
            total_text_len = sum(len(e.text) for e in transcript)
            duration_ratios = {
                s: stats[s].get("total_duration", 0.0) for s in speakers if s in stats
            }
            total_speech = sum(duration_ratios.values()) or 1.0
            expected_agent_ratio = min(total_text_len / (total_text_len + 500), 0.6)
            for speaker, dur in duration_ratios.items():
                ratio = dur / total_speech
                closeness = 1.0 - abs(ratio - expected_agent_ratio)
                scores[speaker] += closeness * 0.10

        return scores

    def _identify_by_transcript(
        self,
        segments: list[SpeakerSegment],
        speakers: list[str],
        transcript: list[AgentTranscriptEntry],
        stats: dict[str, dict],
    ) -> SpeakerIdentification:
        agent_ranges = [
            (e.start, e.end)
            for e in transcript
            if e.start is not None and e.end is not None
        ]

        overlap_scores: dict[str, float] = {s: 0.0 for s in speakers}
        total_agent_time = sum(end - start for start, end in agent_ranges)

        for seg in segments:
            if seg.speaker not in overlap_scores:
                continue
            for start, end in agent_ranges:
                overlap = self._overlap(seg.start, seg.end, start, end)
                overlap_scores[seg.speaker] += overlap

        agent_speaker = max(overlap_scores, key=overlap_scores.get)
        human_speaker = [s for s in speakers if s != agent_speaker][0]

        if total_agent_time > 0:
            confidence = min(overlap_scores[agent_speaker] / total_agent_time, 1.0)
        else:
            confidence = 0.5

        return SpeakerIdentification(
            human_speaker=human_speaker,
            agent_speaker=agent_speaker,
            confidence=round(confidence, 3),
            strategy=IdentificationStrategy.TRANSCRIPT_MATCH,
            speaker_stats={k: v for k, v in stats.items() if not k.startswith("_")},
        )

    def _identify_by_reference_audio(
        self,
        reference_path: str,
        speakers: list[str],
        stats: dict[str, dict],
        speaker_embeddings: Optional[dict[str, np.ndarray]],
    ) -> SpeakerIdentification:
        if not speaker_embeddings:
            return SpeakerIdentification(
                human_speaker=speakers[0],
                agent_speaker=speakers[1],
                confidence=0.0,
                strategy=IdentificationStrategy.REFERENCE_AUDIO,
                speaker_stats={k: v for k, v in stats.items() if not k.startswith("_")},
            )

        ref_embedding = self._extract_reference_embedding(reference_path)
        if ref_embedding is None:
            return SpeakerIdentification(
                human_speaker=speakers[0],
                agent_speaker=speakers[1],
                confidence=0.0,
                strategy=IdentificationStrategy.REFERENCE_AUDIO,
                speaker_stats={k: v for k, v in stats.items() if not k.startswith("_")},
            )

        similarities: dict[str, float] = {}
        for speaker in speakers:
            if speaker in speaker_embeddings:
                similarities[speaker] = self._cosine_similarity(
                    ref_embedding, speaker_embeddings[speaker]
                )
            else:
                similarities[speaker] = 0.0

        agent_speaker = max(similarities, key=similarities.get)
        human_speaker = [s for s in speakers if s != agent_speaker][0]
        confidence = max(0.0, min(similarities[agent_speaker], 1.0))

        return SpeakerIdentification(
            human_speaker=human_speaker,
            agent_speaker=agent_speaker,
            confidence=round(confidence, 3),
            strategy=IdentificationStrategy.REFERENCE_AUDIO,
            speaker_stats={k: v for k, v in stats.items() if not k.startswith("_")},
        )

    @staticmethod
    def _score_response_pattern(
        segments: list[SpeakerSegment], speakers: list[str]
    ) -> dict[str, float]:
        """Score speakers based on turn-taking response latency."""
        scores = {s: 0.0 for s in speakers}
        gaps_as_responder: dict[str, list[float]] = {s: [] for s in speakers}

        sorted_segments = sorted(segments, key=lambda s: s.start)
        for i in range(1, len(sorted_segments)):
            prev = sorted_segments[i - 1]
            curr = sorted_segments[i]
            if prev.speaker != curr.speaker and curr.speaker in gaps_as_responder:
                gap = curr.start - prev.end
                if 0.1 <= gap <= 3.0:
                    gaps_as_responder[curr.speaker].append(gap)

        for speaker, gaps in gaps_as_responder.items():
            if gaps:
                avg_gap = sum(gaps) / len(gaps)
                if 0.3 <= avg_gap <= 1.5:
                    scores[speaker] += 1.0

        total = sum(scores.values()) or 1.0
        return {s: scores[s] / total for s in speakers}

    @staticmethod
    def _overlap(seg_start: float, seg_end: float, range_start: float, range_end: float) -> float:
        return max(0.0, min(seg_end, range_end) - max(seg_start, range_start))

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        a_norm = np.linalg.norm(a)
        b_norm = np.linalg.norm(b)
        if a_norm == 0 or b_norm == 0:
            return 0.0
        return float(np.dot(a, b) / (a_norm * b_norm))

    def _extract_reference_embedding(self, reference_path: str) -> Optional[np.ndarray]:
        try:
            from pyannote.audio import Inference, Model

            model_name = os.getenv(
                "PYANNOTE_EMBEDDING_MODEL",
                "pyannote/wespeaker-voxceleb-resnet34-LM",
            )
            hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

            model = Model.from_pretrained(model_name, token=hf_token)
            inference = Inference(model, window="whole")

            embedding = inference(reference_path)
            return np.asarray(embedding).flatten()
        except Exception as exc:
            logger.warning("Failed to extract reference embedding: %s", exc)
            return None
