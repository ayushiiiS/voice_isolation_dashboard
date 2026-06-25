"""Analytics data models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"



class TranscriptEntry(BaseModel):
    speaker: str
    role: str
    text: str
    start: float
    end: float
    confidence: float = 0.0


class LatencyPoint(BaseModel):
    user_utterance_end: float
    agent_response_start: float
    latency_ms: float


class TimelineSegment(BaseModel):
    speaker: str
    role: str
    start: float
    end: float


class SentimentBreakdown(BaseModel):
    positive: float = 0.0
    neutral: float = 0.0
    negative: float = 0.0


class CallAnalytics(BaseModel):
    recording_id: str
    job_id: str
    call_duration_seconds: float
    user_talk_time_seconds: float
    agent_talk_time_seconds: float
    avg_agent_latency_ms: float
    latency_points: list[LatencyPoint] = Field(default_factory=list)
    avg_user_confidence: float = 0.0
    avg_agent_confidence: float = 0.0
    agent_interrupts_user: int = 0
    user_interrupts_agent: int = 0
    total_interruptions: int = 0
    silence_duration_seconds: float = 0.0
    speaker_switches: int = 0
    sentiment: SentimentLabel = SentimentLabel.NEUTRAL
    sentiment_breakdown: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    user_speaking_rate_wpm: float = 0.0
    agent_speaking_rate_wpm: float = 0.0
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    timeline: list[TimelineSegment] = Field(default_factory=list)
    human_speaker: str = ""
    agent_speaker: str = ""
    identification_confidence: float = 0.0
