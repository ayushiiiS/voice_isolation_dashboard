"""pyannote.audio Community-1 speaker diarization service."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from src.diarization.models import DiarizationResult, SpeakerSegment

logger = logging.getLogger(__name__)

COMMUNITY_1_MODEL = "pyannote/speaker-diarization-community-1"


class PyannoteDiarizationService:
    """Runs speaker diarization using pyannote Community-1."""

    def __init__(
        self,
        hf_token: Optional[str] = None,
        model_path: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        self.hf_token = hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        self.model_path = model_path or os.getenv("PYANNOTE_MODEL_PATH")
        self._pipeline = None
        self._device = device or self._resolve_device()

    @staticmethod
    def _resolve_device() -> str:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @property
    def device(self) -> str:
        return self._device

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline

        from pyannote.audio import Pipeline

        if self.model_path:
            logger.info("Loading pyannote pipeline from local path: %s", self.model_path)
            pipeline = Pipeline.from_pretrained(self.model_path)
        else:
            if not self.hf_token:
                raise ValueError(
                    "Hugging Face token required. Set HF_TOKEN env var or pass hf_token. "
                    "Accept model conditions at "
                    "https://huggingface.co/pyannote/speaker-diarization-community-1"
                )
            logger.info("Loading pyannote Community-1 model from Hugging Face")
            pipeline = Pipeline.from_pretrained(COMMUNITY_1_MODEL, token=self.hf_token)

        import torch

        try:
            pipeline.to(torch.device(self._device))
            logger.info("Diarization pipeline loaded on device: %s", self._device)
        except Exception as exc:
            logger.warning(
                "Failed to move pipeline to %s (%s). Falling back to CPU.",
                self._device,
                exc,
            )
            self._device = "cpu"
            pipeline.to(torch.device("cpu"))

        self._pipeline = pipeline
        return pipeline

    def diarize(
        self,
        audio_input: str | dict,
        num_speakers: int = 2,
        use_exclusive: bool = True,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> tuple[DiarizationResult, object]:
        """
        Run diarization on audio.

        Args:
            audio_input: File path or {"waveform": tensor, "sample_rate": int} dict.
            num_speakers: Expected speaker count (default 2 for human + agent).
            use_exclusive: Use exclusive diarization for cleaner turn boundaries.
            progress_callback: Optional callback(stage, progress_fraction).

        Returns:
            Tuple of (DiarizationResult, raw pyannote output with embeddings).
        """
        pipeline = self._load_pipeline()

        if progress_callback:
            progress_callback("diarizing", 0.0)

        from pyannote.audio.pipelines.utils.hook import ProgressHook

        logger.info("Starting diarization (num_speakers=%d)", num_speakers)

        with ProgressHook() as hook:
            output = pipeline(
                audio_input,
                hook=hook,
                num_speakers=num_speakers,
            )

        if progress_callback:
            progress_callback("diarizing", 1.0)

        annotation = (
            output.exclusive_speaker_diarization
            if use_exclusive and hasattr(output, "exclusive_speaker_diarization")
            else output.speaker_diarization
        )

        segments = self._annotation_to_segments(annotation)
        speakers = sorted({s.speaker for s in segments})
        duration = max((s.end for s in segments), default=0.0)

        result = DiarizationResult(
            segments=segments,
            speakers=speakers,
            duration=duration,
            exclusive=use_exclusive,
        )

        logger.info(
            "Diarization complete: %d segments, %d speakers, %.1fs duration",
            len(segments),
            len(speakers),
            duration,
        )

        return result, output

    @staticmethod
    def _annotation_to_segments(annotation) -> list[SpeakerSegment]:
        segments: list[SpeakerSegment] = []

        if hasattr(annotation, "itertracks"):
            for turn, _, speaker in annotation.itertracks(yield_label=True):
                segments.append(
                    SpeakerSegment(speaker=speaker, start=turn.start, end=turn.end)
                )
        else:
            for turn, speaker in annotation:
                segments.append(
                    SpeakerSegment(speaker=speaker, start=turn.start, end=turn.end)
                )

        segments.sort(key=lambda s: (s.start, s.end))
        return segments

    def export_rttm(self, segments: list[SpeakerSegment], output_path: Path) -> None:
        """Export diarization segments to RTTM format."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as f:
            for seg in segments:
                duration = seg.duration
                f.write(
                    f"SPEAKER recording 1 {seg.start:.3f} {duration:.3f} "
                    f"<NA> <NA> {seg.speaker} <NA> <NA>\n"
                )

        logger.info("Exported RTTM to %s", output_path)

    def export_json(self, result: DiarizationResult, output_path: Path) -> None:
        """Export diarization result to JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "speakers": result.speakers,
            "duration": result.duration,
            "exclusive": result.exclusive,
            "segments": [s.model_dump() for s in result.segments],
        }

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        logger.info("Exported diarization JSON to %s", output_path)
