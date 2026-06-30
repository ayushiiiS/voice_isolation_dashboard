"""End-to-end voice isolation pipeline orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from src.diarization.models import (
    AgentTranscriptEntry,
    IdentificationStrategy,
    IsolateResponse,
    IsolationMetadata,
)
from src.diarization.pyannote_service import PyannoteDiarizationService
from src.isolation.audio_extractor import AudioExtractor
from src.isolation.speaker_selector import SpeakerSelector

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]


class VoiceIsolationPipeline:
    """Orchestrates diarization, speaker identification, and audio extraction."""

    def __init__(
        self,
        diarization_service: Optional[PyannoteDiarizationService] = None,
        audio_extractor: Optional[AudioExtractor] = None,
        speaker_selector: Optional[SpeakerSelector] = None,
        default_output_dir: str = "output",
    ) -> None:
        self.diarization_service = diarization_service or PyannoteDiarizationService()
        self.audio_extractor = audio_extractor or AudioExtractor()
        self.speaker_selector = speaker_selector or SpeakerSelector()
        self.default_output_dir = Path(default_output_dir)

    def run(
        self,
        audio_path: str,
        agent_transcript: Optional[list[AgentTranscriptEntry | str]] = None,
        agent_reference_audio_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        num_speakers: int = 2,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> IsolateResponse:
        """Execute the full voice isolation pipeline."""

        def report(stage: str, progress: float) -> None:
            if progress_callback:
                progress_callback(stage, progress)
            logger.info("Progress [%s] %.0f%%", stage, progress * 100)

        out_dir = Path(output_dir or self.default_output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        report("loading_audio", 0.0)
        audio, local_path, is_temp = self.audio_extractor.load_audio(audio_path)
        duration_original = self.audio_extractor.duration_seconds(audio)
        report("loading_audio", 1.0)

        temp_paths: list[tuple[Path, bool]] = [(local_path, is_temp)]

        try:
            diarization_path, is_diarization_temp = (
                self.audio_extractor.prepare_for_diarization(audio)
            )
            temp_paths.append((diarization_path, is_diarization_temp))

            report("diarizing", 0.0)
            diarization_result, raw_output, overlap_segments = self.diarization_service.diarize(
                str(diarization_path),
                num_speakers=num_speakers,
                progress_callback=progress_callback,
            )
            report("diarizing", 1.0)

            from src.isolation.audio_extractor import filter_micro_segments

            identification_segments = filter_micro_segments(diarization_result.segments)
            extraction_segments = filter_micro_segments(
                overlap_segments or diarization_result.segments
            )

            diarization_json_path = out_dir / "diarization.json"
            diarization_rttm_path = out_dir / "diarization.rttm"
            self.diarization_service.export_json(diarization_result, diarization_json_path)
            self.diarization_service.export_rttm(
                diarization_result.segments, diarization_rttm_path
            )

            report("identifying_speakers", 0.0)
            speaker_embeddings = self._extract_speaker_embeddings(
                raw_output, diarization_result.speakers
            )
            identification = self.speaker_selector.identify(
                segments=identification_segments,
                agent_transcript=agent_transcript,
                agent_reference_audio_path=agent_reference_audio_path,
                speaker_embeddings=speaker_embeddings,
            )
            report("identifying_speakers", 1.0)

            report("extracting_human_audio", 0.0)
            human_audio, human_segments, agent_segments = (
                self.audio_extractor.extract_human_segments(
                    audio=audio,
                    segments=extraction_segments,
                    human_speaker=identification.human_speaker,
                    agent_speaker=identification.agent_speaker,
                )
            )
            agent_audio, _ = self.audio_extractor.extract_speaker_segments(
                audio=audio,
                segments=extraction_segments,
                speaker_id=identification.agent_speaker,
            )
            report("extracting_human_audio", 1.0)

            report("exporting", 0.0)
            original_path = out_dir / "original.wav"
            isolated_path = out_dir / "user_only.wav"
            agent_path = out_dir / "agent_only.wav"
            self.audio_extractor.export_playback_wav(audio, original_path)
            self.audio_extractor.export_wav(human_audio, isolated_path)
            self.audio_extractor.export_wav(agent_audio, agent_path)
            report("exporting", 1.0)

            duration_user_only = self.audio_extractor.duration_seconds(human_audio)
            duration_agent_only = self.audio_extractor.duration_seconds(agent_audio)

            metadata = IsolationMetadata(
                human_speaker=identification.human_speaker,
                agent_speaker=identification.agent_speaker,
                confidence=identification.confidence,
                strategy=identification.strategy,
                duration_original=duration_original,
                duration_user_only=duration_user_only,
                segment_count_human=len(human_segments),
                segment_count_agent=len(agent_segments),
            )

            report("complete", 1.0)

            return IsolateResponse(
                isolated_audio_path=str(isolated_path.resolve()),
                agent_audio_path=str(agent_path.resolve()),
                diarization_json_path=str(diarization_json_path.resolve()),
                diarization_rttm_path=str(diarization_rttm_path.resolve()),
                human_speaker=identification.human_speaker,
                agent_speaker=identification.agent_speaker,
                confidence=identification.confidence,
                strategy=identification.strategy,
                duration_original=round(duration_original, 3),
                duration_user_only=round(duration_user_only, 3),
                duration_agent_only=round(duration_agent_only, 3),
                metadata=metadata,
            )
        finally:
            for path, should_delete in temp_paths:
                self.audio_extractor.cleanup_temp(path, should_delete)

    @staticmethod
    def _extract_speaker_embeddings(
        raw_output, speakers: list[str]
    ) -> Optional[dict[str, np.ndarray]]:
        if not hasattr(raw_output, "speaker_embeddings"):
            return None

        embeddings = raw_output.speaker_embeddings
        if embeddings is None:
            return None

        try:
            if isinstance(embeddings, dict):
                return {
                    k: np.asarray(v).flatten()
                    for k, v in embeddings.items()
                    if k in speakers
                }

            result: dict[str, np.ndarray] = {}
            for i, speaker in enumerate(speakers):
                if i < len(embeddings):
                    result[speaker] = np.asarray(embeddings[i]).flatten()
            return result or None
        except Exception as exc:
            logger.warning("Could not parse speaker embeddings: %s", exc)
            return None
