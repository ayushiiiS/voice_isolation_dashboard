"""Data models for speaker diarization and voice isolation."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class SpeakerSegment(BaseModel):
    """A single diarized speech segment."""

    speaker: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)

    @field_validator("end")
    @classmethod
    def end_after_start(cls, end: float, info: ValidationInfo) -> float:
        start = info.data.get("start", 0.0)
        if end <= start:
            raise ValueError("end must be greater than start")
        return end

    @property
    def duration(self) -> float:
        return self.end - self.start


class AgentTranscriptEntry(BaseModel):
    """A single agent utterance from Blue Machines AI logs."""

    text: str
    start: Optional[float] = Field(default=None, ge=0.0)
    end: Optional[float] = Field(default=None, ge=0.0)


class DiarizationResult(BaseModel):
    """Full diarization output with speaker segments."""

    segments: list[SpeakerSegment]
    speakers: list[str]
    duration: float
    exclusive: bool = False


class IdentificationStrategy(str, Enum):
    TRANSCRIPT_MATCH = "transcript_match"
    HEURISTICS = "heuristics"
    REFERENCE_AUDIO = "reference_audio"
    FALLBACK = "fallback"


class SpeakerIdentification(BaseModel):
    """Result of identifying human vs agent speakers."""

    human_speaker: str
    agent_speaker: str
    confidence: float = Field(ge=0.0, le=1.0)
    strategy: IdentificationStrategy
    speaker_stats: dict[str, dict] = Field(default_factory=dict)


class IsolationMetadata(BaseModel):
    """Metadata returned after voice isolation."""

    human_speaker: str
    agent_speaker: str
    confidence: float
    strategy: IdentificationStrategy
    duration_original: float
    duration_user_only: float
    segment_count_human: int
    segment_count_agent: int


class IsolateRequest(BaseModel):
    """API request body for voice isolation."""

    audio_path: str = Field(
        ...,
        description="Local file path or HTTP(S) URL to the recording (wav/mp3/m4a).",
    )
    agent_transcript: Optional[list[AgentTranscriptEntry | str]] = Field(
        default=None,
        description="Optional agent utterance logs for transcript-based identification.",
    )
    agent_reference_audio_path: Optional[str] = Field(
        default=None,
        description="Optional reference audio of the agent voice for speaker verification.",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Optional output directory. Defaults to ./output.",
    )
    num_speakers: int = Field(
        default=2,
        ge=2,
        le=2,
        description="Expected number of speakers (human + agent).",
    )


class IsolateResponse(BaseModel):
    """API response for voice isolation."""

    isolated_audio_path: str
    agent_audio_path: Optional[str] = None
    diarization_json_path: str
    diarization_rttm_path: str
    human_speaker: str
    agent_speaker: str
    confidence: float
    strategy: IdentificationStrategy
    duration_original: float
    duration_user_only: float
    duration_agent_only: Optional[float] = None
    metadata: IsolationMetadata


class BatchIsolateRequest(BaseModel):
    """Batch processing request."""

    items: list[IsolateRequest] = Field(..., min_length=1, max_length=50)


class BatchIsolateResponse(BaseModel):
    """Batch processing response."""

    results: list[IsolateResponse | dict]
    succeeded: int
    failed: int


class ProgressStage(str, Enum):
    LOADING_AUDIO = "loading_audio"
    DIARIZING = "diarizing"
    IDENTIFYING_SPEAKERS = "identifying_speakers"
    EXTRACTING_HUMAN_AUDIO = "extracting_human_audio"
    EXPORTING = "exporting"
    COMPLETE = "complete"
