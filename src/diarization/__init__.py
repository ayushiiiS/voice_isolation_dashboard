"""Speaker diarization module."""

from src.diarization.models import (
    AgentTranscriptEntry,
    DiarizationResult,
    IdentificationStrategy,
    IsolateRequest,
    IsolateResponse,
    IsolationMetadata,
    SpeakerIdentification,
    SpeakerSegment,
)

__all__ = [
    "AgentTranscriptEntry",
    "DiarizationResult",
    "IdentificationStrategy",
    "IsolateRequest",
    "IsolateResponse",
    "IsolationMetadata",
    "SpeakerIdentification",
    "SpeakerSegment",
]


def __getattr__(name: str):
    if name == "PyannoteDiarizationService":
        from src.diarization.pyannote_service import PyannoteDiarizationService

        return PyannoteDiarizationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
