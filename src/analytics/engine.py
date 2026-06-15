"""Compute call analytics from diarization segments and optional transcription."""

from __future__ import annotations

import logging
import re
from typing import Optional

from src.analytics.models import (
    CallAnalytics,
    LatencyPoint,
    SentimentBreakdown,
    SentimentLabel,
    TimelineSegment,
    TranscriptEntry,
)
from src.diarization.models import DiarizationResult, SpeakerSegment

logger = logging.getLogger(__name__)

POSITIVE_WORDS = {
    "good", "great", "thanks", "thank", "perfect", "excellent", "happy",
    "wonderful", "awesome", "yes", "sure", "helpful", "love", "nice",
}
NEGATIVE_WORDS = {
    "bad", "no", "not", "never", "problem", "issue", "wrong", "fail",
    "angry", "frustrated", "hate", "terrible", "worst", "cancel", "complaint",
}


class AnalyticsEngine:
    """Derive interaction metrics from diarization and transcript data."""

    def compute(
        self,
        recording_id: str,
        job_id: str,
        diarization: DiarizationResult,
        human_speaker: str,
        agent_speaker: str,
        identification_confidence: float,
        transcript: Optional[list[TranscriptEntry]] = None,
    ) -> CallAnalytics:
        segments = sorted(diarization.segments, key=lambda s: s.start)
        human_segments = [s for s in segments if s.speaker == human_speaker]
        agent_segments = [s for s in segments if s.speaker == agent_speaker]

        user_talk = sum(s.duration for s in human_segments)
        agent_talk = sum(s.duration for s in agent_segments)
        call_duration = diarization.duration or max(
            (s.end for s in segments), default=0.0
        )

        latency_points = self._compute_latencies(human_segments, agent_segments)
        avg_latency = (
            sum(p.latency_ms for p in latency_points) / len(latency_points)
            if latency_points
            else 0.0
        )

        agent_interrupts, user_interrupts = self._count_interruptions(
            segments, human_speaker, agent_speaker
        )
        silence = max(0.0, call_duration - user_talk - agent_talk)
        switches = self._count_speaker_switches(segments)

        timeline = [
            TimelineSegment(
                speaker=s.speaker,
                role="user" if s.speaker == human_speaker else "agent",
                start=round(s.start, 3),
                end=round(s.end, 3),
            )
            for s in segments
        ]

        if transcript is None:
            transcript = self._build_placeholder_transcript(
                segments, human_speaker, agent_speaker
            )

        user_conf, agent_conf = self._avg_confidence(transcript)
        sentiment, breakdown = self._compute_sentiment(transcript)
        user_wpm, agent_wpm = self._speaking_rates(transcript)

        return CallAnalytics(
            recording_id=recording_id,
            job_id=job_id,
            call_duration_seconds=round(call_duration, 3),
            user_talk_time_seconds=round(user_talk, 3),
            agent_talk_time_seconds=round(agent_talk, 3),
            avg_agent_latency_ms=round(avg_latency, 2),
            latency_points=latency_points,
            avg_user_confidence=round(user_conf, 3),
            avg_agent_confidence=round(agent_conf, 3),
            agent_interrupts_user=agent_interrupts,
            user_interrupts_agent=user_interrupts,
            total_interruptions=agent_interrupts + user_interrupts,
            silence_duration_seconds=round(silence, 3),
            speaker_switches=switches,
            sentiment=sentiment,
            sentiment_breakdown=breakdown,
            user_speaking_rate_wpm=round(user_wpm, 1),
            agent_speaking_rate_wpm=round(agent_wpm, 1),
            transcript=transcript,
            timeline=timeline,
            human_speaker=human_speaker,
            agent_speaker=agent_speaker,
            identification_confidence=identification_confidence,
        )

    @staticmethod
    def _compute_latencies(
        human_segments: list[SpeakerSegment],
        agent_segments: list[SpeakerSegment],
    ) -> list[LatencyPoint]:
        points: list[LatencyPoint] = []
        for user_seg in human_segments:
            for agent_seg in agent_segments:
                if agent_seg.start >= user_seg.end:
                    latency_ms = (agent_seg.start - user_seg.end) * 1000
                    points.append(
                        LatencyPoint(
                            user_utterance_end=round(user_seg.end, 3),
                            agent_response_start=round(agent_seg.start, 3),
                            latency_ms=round(latency_ms, 2),
                        )
                    )
                    break
        return points

    @staticmethod
    def _count_interruptions(
        segments: list[SpeakerSegment],
        human_speaker: str,
        agent_speaker: str,
    ) -> tuple[int, int]:
        agent_interrupts = 0
        user_interrupts = 0
        for i, seg in enumerate(segments):
            if i == 0:
                continue
            prev = segments[i - 1]
            if prev.speaker == human_speaker and seg.speaker == agent_speaker:
                if seg.start < prev.end - 0.15:
                    agent_interrupts += 1
            elif prev.speaker == agent_speaker and seg.speaker == human_speaker:
                if seg.start < prev.end - 0.15:
                    user_interrupts += 1
        return agent_interrupts, user_interrupts

    @staticmethod
    def _count_speaker_switches(segments: list[SpeakerSegment]) -> int:
        if len(segments) < 2:
            return 0
        switches = 0
        for i in range(1, len(segments)):
            if segments[i].speaker != segments[i - 1].speaker:
                switches += 1
        return switches

    @staticmethod
    def _build_placeholder_transcript(
        segments: list[SpeakerSegment],
        human_speaker: str,
        agent_speaker: str,
    ) -> list[TranscriptEntry]:
        entries: list[TranscriptEntry] = []
        for seg in segments:
            role = "user" if seg.speaker == human_speaker else "agent"
            entries.append(
                TranscriptEntry(
                    speaker=seg.speaker,
                    role=role,
                    text=f"[{role} speech {seg.start:.1f}s–{seg.end:.1f}s]",
                    start=round(seg.start, 3),
                    end=round(seg.end, 3),
                    confidence=0.85 if role == "user" else 0.92,
                )
            )
        return entries

    @staticmethod
    def _avg_confidence(transcript: list[TranscriptEntry]) -> tuple[float, float]:
        user_confs = [t.confidence for t in transcript if t.role == "user"]
        agent_confs = [t.confidence for t in transcript if t.role == "agent"]
        user_avg = sum(user_confs) / len(user_confs) if user_confs else 0.0
        agent_avg = sum(agent_confs) / len(agent_confs) if agent_confs else 0.0
        return user_avg, agent_avg

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z']+", text.lower())

    def _compute_sentiment(
        self, transcript: list[TranscriptEntry]
    ) -> tuple[SentimentLabel, SentimentBreakdown]:
        pos = neu = neg = 0
        for entry in transcript:
            tokens = self._tokenize(entry.text)
            if not tokens:
                neu += 1
                continue
            p = sum(1 for t in tokens if t in POSITIVE_WORDS)
            n = sum(1 for t in tokens if t in NEGATIVE_WORDS)
            if p > n:
                pos += 1
            elif n > p:
                neg += 1
            else:
                neu += 1

        total = max(pos + neu + neg, 1)
        breakdown = SentimentBreakdown(
            positive=round(pos / total, 3),
            neutral=round(neu / total, 3),
            negative=round(neg / total, 3),
        )
        if pos > neg and pos >= neu:
            label = SentimentLabel.POSITIVE
        elif neg > pos and neg >= neu:
            label = SentimentLabel.NEGATIVE
        else:
            label = SentimentLabel.NEUTRAL
        return label, breakdown

    @staticmethod
    def _speaking_rates(transcript: list[TranscriptEntry]) -> tuple[float, float]:
        def rate_for_role(role: str) -> float:
            entries = [t for t in transcript if t.role == role]
            total_words = sum(len(AnalyticsEngine._tokenize(t.text)) for t in entries)
            total_minutes = sum(t.end - t.start for t in entries) / 60.0
            if total_minutes <= 0:
                return 0.0
            return total_words / total_minutes

        return rate_for_role("user"), rate_for_role("agent")
