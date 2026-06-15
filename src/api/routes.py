"""FastAPI routes for voice isolation."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.diarization.models import (
    BatchIsolateRequest,
    BatchIsolateResponse,
    IsolateRequest,
    IsolateResponse,
    ProgressStage,
)
from src.isolation.pipeline import VoiceIsolationPipeline

logger = logging.getLogger(__name__)

router = APIRouter()

_pipeline: Optional[VoiceIsolationPipeline] = None
_executor = ThreadPoolExecutor(max_workers=2)
_job_status: dict[str, dict] = {}


def get_pipeline() -> VoiceIsolationPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = VoiceIsolationPipeline()
    return _pipeline


def _run_isolation(request: IsolateRequest) -> IsolateResponse:
    pipeline = get_pipeline()
    return pipeline.run(
        audio_path=request.audio_path,
        agent_transcript=request.agent_transcript,
        agent_reference_audio_path=request.agent_reference_audio_path,
        output_dir=request.output_dir,
        num_speakers=request.num_speakers,
    )


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    pipeline = get_pipeline()
    return {
        "status": "healthy",
        "device": pipeline.diarization_service.device,
        "model": "pyannote/speaker-diarization-community-1",
    }


@router.post("/isolate", response_model=IsolateResponse)
async def isolate_voice(request: IsolateRequest) -> IsolateResponse:
    """
    Isolate human user voice from a Blue Machines AI call recording.

    Removes all voice agent speech and returns user-only audio with diarization metadata.
    """
    logger.info("Received isolation request for: %s", request.audio_path)

    try:
        result = _run_isolation(request)
        logger.info(
            "Isolation complete: human=%s, agent=%s, confidence=%.2f",
            result.human_speaker,
            result.agent_speaker,
            result.confidence,
        )
        return result
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Isolation failed for %s", request.audio_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice isolation failed: {exc}",
        ) from exc


@router.post("/isolate/batch", response_model=BatchIsolateResponse)
async def isolate_batch(request: BatchIsolateRequest) -> BatchIsolateResponse:
    """Process multiple recordings in batch."""
    logger.info("Received batch isolation request: %d items", len(request.items))

    results: list[IsolateResponse | dict] = []
    succeeded = 0
    failed = 0

    for item in request.items:
        try:
            result = _run_isolation(item)
            results.append(result)
            succeeded += 1
        except Exception as exc:
            logger.error("Batch item failed (%s): %s", item.audio_path, exc)
            results.append(
                {
                    "audio_path": item.audio_path,
                    "error": str(exc),
                    "status": "failed",
                }
            )
            failed += 1

    return BatchIsolateResponse(
        results=results,
        succeeded=succeeded,
        failed=failed,
    )


@router.post("/isolate/async")
async def isolate_async(
    request: IsolateRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Submit an async isolation job and poll status via GET /isolate/status/{job_id}."""
    job_id = str(uuid.uuid4())
    _job_status[job_id] = {
        "status": ProgressStage.LOADING_AUDIO.value,
        "progress": 0.0,
        "result": None,
        "error": None,
    }

    def progress_callback(stage: str, progress: float) -> None:
        _job_status[job_id]["status"] = stage
        _job_status[job_id]["progress"] = progress

    def run_job() -> None:
        try:
            pipeline = get_pipeline()
            result = pipeline.run(
                audio_path=request.audio_path,
                agent_transcript=request.agent_transcript,
                agent_reference_audio_path=request.agent_reference_audio_path,
                output_dir=request.output_dir,
                num_speakers=request.num_speakers,
                progress_callback=progress_callback,
            )
            _job_status[job_id]["status"] = ProgressStage.COMPLETE.value
            _job_status[job_id]["progress"] = 1.0
            _job_status[job_id]["result"] = result.model_dump()
        except Exception as exc:
            logger.exception("Async job %s failed", job_id)
            _job_status[job_id]["status"] = "failed"
            _job_status[job_id]["error"] = str(exc)

    background_tasks.add_task(run_job)

    return {
        "job_id": job_id,
        "status": ProgressStage.LOADING_AUDIO.value,
        "message": "Job submitted. Poll GET /isolate/status/{job_id} for progress.",
    }


@router.get("/isolate/status/{job_id}")
async def get_job_status(job_id: str) -> dict:
    """Get status of an async isolation job."""
    if job_id not in _job_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job not found: {job_id}",
        )
    return {"job_id": job_id, **_job_status[job_id]}
