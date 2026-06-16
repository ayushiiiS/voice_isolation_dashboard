"""Pydantic models for multi-provider streaming STT."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SelectionMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ProviderStatus(str, Enum):
    CONNECTING = "connecting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class TranscriptUpdateType(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"


class LanguageMode(str, Enum):
    FIXED = "fixed"
    AUTO = "auto"
    MULTILINGUAL = "multilingual"


class TranscriptMode(str, Enum):
    CONSENSUS = "consensus"
    SINGLE = "single"


class AudioQualityInfo(BaseModel):
    score: float = 0.0
    sample_rate: int = 0
    channels: int = 1
    duration_seconds: float = 0.0
    clipping_ratio: float = 0.0
    silence_ratio: float = 0.0
    snr_db: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    source_label: str = ""


class LanguageCandidateInfo(BaseModel):
    language: str
    language_code: str
    confidence: float


class ProviderScoreInfo(BaseModel):
    provider: str
    confidence: float
    completeness: float
    language_match: float
    composite: float
    word_count: int = 0


class TranscriptUpdate(BaseModel):
    """A partial or final transcript from a single provider."""

    provider: str
    update_type: TranscriptUpdateType
    text: str
    raw_confidence: Optional[float] = None
    normalized_confidence: Optional[float] = None
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())
    is_final: bool = False


class ProviderMetrics(BaseModel):
    """Rolling metrics for one provider during a session."""

    provider: str
    current_confidence: Optional[float] = None
    average_confidence: Optional[float] = None
    current_latency_ms: float = 0.0
    average_latency_ms: float = 0.0
    error_count: int = 0
    reconnect_count: int = 0
    uptime_seconds: float = 0.0
    transcript_count: int = 0
    last_error: Optional[str] = None


class ProviderState(BaseModel):
    """Live state for one provider in the comparison panel."""

    provider: str
    display_name: str
    status: ProviderStatus = ProviderStatus.CONNECTING
    partial_transcript: str = ""
    final_transcript: str = ""
    raw_confidence: Optional[float] = None
    normalized_confidence: Optional[float] = None
    latency_ms: float = 0.0
    ranking: int = 0
    composite_score: Optional[float] = None
    metrics: ProviderMetrics = Field(default_factory=lambda: ProviderMetrics(provider=""))
    error: Optional[str] = None
    is_simulated: bool = False


class SttAudioSource(str, Enum):
    MICROPHONE = "microphone"
    ISOLATED_USER_AUDIO = "isolated_user_audio"


class SttSessionConfig(BaseModel):
    """Client configuration for a streaming STT session."""

    enabled_providers: list[str] = Field(
        default_factory=lambda: ["deepgram", "azure", "openai", "google", "aws"]
    )
    selection_mode: SelectionMode = SelectionMode.AUTO
    manual_provider: Optional[str] = None
    hysteresis_threshold: float = Field(
        default=5.0,
        ge=0.0,
        le=100.0,
        description="Minimum confidence gap (0-100) required to switch auto-selected provider.",
    )
    sample_rate: int = 16000
    language: str = "en-US"
    auto_detect_language: bool = True
    language_override: Optional[str] = None
    detected_language: Optional[str] = None
    language_code: Optional[str] = None
    language_confidence: Optional[float] = None
    language_detection_method: Optional[str] = None
    language_mode: LanguageMode = LanguageMode.FIXED
    language_candidates: list[LanguageCandidateInfo] = Field(default_factory=list)
    language_hints: list[str] = Field(default_factory=list)
    transcript_mode: TranscriptMode = TranscriptMode.CONSENSUS
    audio_source_type: Optional[str] = None
    audio_quality: Optional[AudioQualityInfo] = None
    source: SttAudioSource = SttAudioSource.ISOLATED_USER_AUDIO
    recording_id: Optional[str] = None
    user_audio_url: Optional[str] = None
    recording_file_name: Optional[str] = None


class SttSessionSnapshot(BaseModel):
    """Full session state pushed to clients."""

    session_id: str
    selection_mode: SelectionMode
    selected_provider: Optional[str] = None
    auto_selected_provider: Optional[str] = None
    best_provider: Optional[str] = None
    best_confidence: Optional[float] = None
    primary_transcript: str = ""
    providers: list[ProviderState] = Field(default_factory=list)
    source: SttAudioSource = SttAudioSource.MICROPHONE
    recording_id: Optional[str] = None
    recording_file_name: Optional[str] = None
    user_audio_url: Optional[str] = None
    feed_progress: float = 0.0
    feed_complete: bool = False
    language: str = "en-US"
    detected_language: Optional[str] = None
    language_code: Optional[str] = None
    language_confidence: Optional[float] = None
    language_detection_method: Optional[str] = None
    language_mode: LanguageMode = LanguageMode.FIXED
    language_candidates: list[LanguageCandidateInfo] = Field(default_factory=list)
    language_hints: list[str] = Field(default_factory=list)
    transcript_mode: TranscriptMode = TranscriptMode.CONSENSUS
    audio_source_type: Optional[str] = None
    audio_quality: Optional[AudioQualityInfo] = None
    consensus_transcript: str = ""
    processed_transcript: str = ""
    provider_scores: list[ProviderScoreInfo] = Field(default_factory=list)
    provider_raw_transcripts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class SttSessionRecord(BaseModel):
    """Persisted session summary for MongoDB."""

    session_id: str
    user_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    config: SttSessionConfig
    final_snapshot: Optional[SttSessionSnapshot] = None
    provider_metrics: list[ProviderMetrics] = Field(default_factory=list)
