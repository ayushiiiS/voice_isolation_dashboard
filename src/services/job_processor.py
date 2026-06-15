"""Process recording jobs: isolation, GCS upload, analytics, reports."""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from bson import ObjectId

from src.utils.recording_url_resolver import recording_display_name, resolve_recording_url

from src.analytics.engine import AnalyticsEngine
from src.diarization.models import DiarizationResult
from src.diarization.pyannote_service import PyannoteDiarizationService
from src.isolation.pipeline import VoiceIsolationPipeline
from src.reports.generator import ReportGenerator
from src.services.storage_handler import upload_outputs_with_fallback
from src.services.storage_urls import persist_processed_outputs

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float, Optional[str]], None]


class JobProcessor:
    """End-to-end job processing for a single recording URL."""

    def __init__(
        self,
        pipeline: Optional[VoiceIsolationPipeline] = None,
        analytics_engine: Optional[AnalyticsEngine] = None,
        report_generator: Optional[ReportGenerator] = None,
    ) -> None:
        self.pipeline = pipeline or VoiceIsolationPipeline()
        self.analytics_engine = analytics_engine or AnalyticsEngine()
        self.report_generator = report_generator or ReportGenerator()
        self.bucket_name = os.getenv("BUCKET_NAME", "cadence-audio")
        self.work_dir = Path(os.getenv("WORK_DIR", "output/.work"))

    def process_recording(
        self,
        recording_url: str,
        job_id: str,
        recording_id: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> dict:
        """Run isolation pipeline, upload to GCS, compute analytics."""
        recording_url = resolve_recording_url(recording_url)

        def report(stage: str, progress: float, message: Optional[str] = None) -> None:
            if progress_callback:
                progress_callback(stage, progress, message)

        work_path = self.work_dir / recording_id
        work_path.mkdir(parents=True, exist_ok=True)

        try:
            report("loading_audio", 0.05, "Downloading recording")

            def pipeline_progress(stage: str, p: float) -> None:
                stage_map = {
                    "loading_audio": (0.05, 0.15),
                    "diarizing": (0.15, 0.55),
                    "identifying_speakers": (0.55, 0.65),
                    "extracting_human_audio": (0.65, 0.75),
                    "exporting": (0.75, 0.85),
                    "complete": (0.85, 0.90),
                }
                lo, hi = stage_map.get(stage, (0.0, 1.0))
                report(stage, lo + p * (hi - lo), stage.replace("_", " ").title())

            result = self.pipeline.run(
                audio_path=recording_url,
                output_dir=str(work_path),
                progress_callback=pipeline_progress,
            )

            report("uploading", 0.90, "Saving outputs")
            persist_processed_outputs(work_path, recording_id)
            storage = upload_outputs_with_fallback(
                recording_id=recording_id,
                user_path=Path(result.isolated_audio_path),
                agent_path=Path(result.agent_audio_path or work_path / "agent_only.wav"),
                diarization_path=work_path / "diarization.json",
            )
            urls = storage.to_dict()

            report("analytics", 0.93, "Computing analytics")
            diarization = self._load_diarization(work_path / "diarization.json")
            analytics = self.analytics_engine.compute(
                recording_id=recording_id,
                job_id=job_id,
                diarization=diarization,
                human_speaker=result.human_speaker,
                agent_speaker=result.agent_speaker,
                identification_confidence=result.confidence,
            )

            report("reports", 0.96, "Generating reports")
            reports = self.report_generator.generate_all(
                recording_id=recording_id,
                analytics=analytics,
                recording_url=recording_url,
                user_audio_url=urls["user_audio_url"],
                agent_audio_url=urls["agent_audio_url"],
                original_url=recording_url,
            )

            report("complete", 1.0, "Processing complete")

            file_name = recording_filename(recording_url)

            return {
                "recording_id": recording_id,
                "job_id": job_id,
                "file_name": file_name,
                "recording_url": recording_url,
                "user_audio_url": urls["user_audio_url"],
                "agent_audio_url": urls["agent_audio_url"],
                "original_audio_url": recording_url,
                "storage_type": urls["storage_type"],
                "storage_uri": urls["storage_uri"],
                "upload_status": urls["upload_status"],
                "gcs_error": urls.get("gcs_error"),
                "diarization": diarization.model_dump(),
                "isolation": result.model_dump(),
                "analytics": analytics.model_dump(),
                "reports": reports,
                "status": "completed",
            }
        except Exception as exc:
            logger.exception("Job processing failed for %s", recording_url)
            return {
                "recording_id": recording_id,
                "job_id": job_id,
                "recording_url": recording_url,
                "status": "failed",
                "error": str(exc),
            }
        finally:
            if os.getenv("KEEP_WORK_DIR", "false").lower() != "true":
                shutil.rmtree(work_path, ignore_errors=True)

    @staticmethod
    def _load_diarization(path: Path) -> DiarizationResult:
        with path.open() as f:
            data = json.load(f)
        return DiarizationResult(**data)

    @staticmethod
    def generate_batch_csv(results: list[dict], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "recording_url",
            "user_audio_url",
            "agent_audio_url",
            "duration_seconds",
            "user_talk_time",
            "agent_talk_time",
            "avg_latency_ms",
            "avg_confidence",
            "interruptions",
            "status",
        ]
        with output_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in results:
                analytics = row.get("analytics") or {}
                writer.writerow(
                    {
                        "recording_url": row.get("recording_url", ""),
                        "user_audio_url": row.get("user_audio_url", ""),
                        "agent_audio_url": row.get("agent_audio_url", ""),
                        "duration_seconds": analytics.get("call_duration_seconds", ""),
                        "user_talk_time": analytics.get("user_talk_time_seconds", ""),
                        "agent_talk_time": analytics.get("agent_talk_time_seconds", ""),
                        "avg_latency_ms": analytics.get("avg_agent_latency_ms", ""),
                        "avg_confidence": analytics.get("avg_user_confidence", ""),
                        "interruptions": analytics.get("total_interruptions", ""),
                        "status": row.get("status", ""),
                    }
                )
        return output_path


async def persist_job_result(db, user_id: str, job_doc: dict, result: dict) -> None:
    """Update MongoDB collections after processing."""
    from src.db.mongodb import col_analytics, col_jobs, col_recordings, col_reports

    now = datetime.now(timezone.utc)
    job_id = job_doc["id"]
    recording_id = result.get("recording_id")

    if result.get("status") == "completed":
        await col_recordings(db).update_one(
            {"_id": ObjectId(recording_id)},
            {
                "$set": {
                    "status": "completed",
                    "user_audio_url": result["user_audio_url"],
                    "agent_audio_url": result["agent_audio_url"],
                    "original_audio_url": result["original_audio_url"],
                    "file_name": result.get("file_name"),
                    "duration_seconds": result["analytics"]["call_duration_seconds"],
                    "user_talk_time_seconds": result["analytics"]["user_talk_time_seconds"],
                    "agent_talk_time_seconds": result["analytics"]["agent_talk_time_seconds"],
                    "avg_agent_latency_ms": result["analytics"]["avg_agent_latency_ms"],
                    "avg_user_confidence": result["analytics"]["avg_user_confidence"],
                    "total_interruptions": result["analytics"]["total_interruptions"],
                    "storage_type": result.get("storage_type", "local"),
                    "storage_uri": result.get("storage_uri"),
                    "upload_status": result.get("upload_status", "failed"),
                    "gcs_error": result.get("gcs_error"),
                    "updated_at": now,
                }
            },
        )
        await col_analytics(db).insert_one(
            {
                **result["analytics"],
                "user_id": user_id,
                "created_at": now,
            }
        )
        await col_reports(db).insert_one(
            {
                "recording_id": recording_id,
                "job_id": job_id,
                "user_id": user_id,
                **result["reports"],
                "created_at": now,
            }
        )

        completed = await col_recordings(db).count_documents(
            {"job_id": job_id, "status": "completed"}
        )
        failed = await col_recordings(db).count_documents(
            {"job_id": job_id, "status": "failed"}
        )
        total = job_doc.get("total_recordings", 1)
        progress = (completed + failed) / max(total, 1)
        job_status = "completed" if completed + failed >= total else "processing"

        update_fields: dict = {
            "completed_count": completed,
            "failed_count": failed,
            "progress": progress,
            "updated_at": now,
            "status": job_status,
        }

        if job_status == "completed" and total > 1:
            batch_csv = await _generate_batch_results_csv(db, job_id)
            if batch_csv:
                update_fields["results_csv_path"] = batch_csv

        await col_jobs(db).update_one(
            {"_id": ObjectId(job_id)},
            {"$set": update_fields},
        )
    else:
        await col_recordings(db).update_one(
            {"_id": ObjectId(recording_id)},
            {
                "$set": {
                    "status": "failed",
                    "error": result.get("error"),
                    "updated_at": now,
                }
            },
        )
        failed = await col_recordings(db).count_documents(
            {"job_id": job_id, "status": "failed"}
        )
        completed = await col_recordings(db).count_documents(
            {"job_id": job_id, "status": "completed"}
        )
        total = job_doc.get("total_recordings", 1)
        await col_jobs(db).update_one(
            {"_id": ObjectId(job_id)},
            {
                "$set": {
                    "failed_count": failed,
                    "completed_count": completed,
                    "progress": (completed + failed) / max(total, 1),
                    "updated_at": now,
                    "status": "completed" if completed + failed >= total else "processing",
                }
            },
        )


def new_recording_id() -> str:
    return str(ObjectId())


def recording_filename(url: str) -> str:
    try:
        return recording_display_name(url)
    except Exception:
        parsed = urlparse(url)
        if parsed.scheme == "gs":
            return parsed.path.rstrip("/").split("/")[-1] or "recording"
        return parsed.path.split("/")[-1] or "recording"


async def _generate_batch_results_csv(db, job_id: str) -> str | None:
    """Build results.csv for a completed batch job."""
    from src.db.mongodb import col_analytics, col_recordings

    recs = await col_recordings(db).find({"job_id": job_id}).to_list(None)
    if not recs:
        return None

    results = []
    for rec in recs:
        analytics = await col_analytics(db).find_one({"recording_id": str(rec["_id"])})
        results.append(
            {
                "recording_url": rec.get("recording_url", ""),
                "user_audio_url": rec.get("user_audio_url", ""),
                "agent_audio_url": rec.get("agent_audio_url", ""),
                "analytics": analytics or {},
                "status": rec.get("status", ""),
            }
        )

    output_path = Path(os.getenv("REPORTS_DIR", "output/reports")) / job_id / "results.csv"
    JobProcessor.generate_batch_csv(results, output_path)
    return str(output_path.resolve())
