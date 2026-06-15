"""Generate PDF, CSV, and JSON reports."""

from __future__ import annotations

import csv
import json
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from src.analytics.models import CallAnalytics
from src.utils.gcs_storage import GcsStorageClient

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Create exportable reports and optionally upload to GCS."""

    def __init__(self) -> None:
        self.bucket_name = os.getenv("BUCKET_NAME", "cadence-audio")
        self.local_reports_dir = Path(os.getenv("REPORTS_DIR", "output/reports"))
        self.local_reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_all(
        self,
        recording_id: str,
        analytics: CallAnalytics,
        recording_url: str,
        user_audio_url: str,
        agent_audio_url: str,
        original_url: str,
    ) -> dict:
        base = self.local_reports_dir / recording_id
        base.mkdir(parents=True, exist_ok=True)

        json_path = base / "report.json"
        csv_path = base / "report.csv"
        pdf_path = base / "report.pdf"

        self.generate_json(json_path, analytics, recording_url, user_audio_url, agent_audio_url)
        self.generate_csv(csv_path, analytics, recording_url, user_audio_url, agent_audio_url)
        self.generate_pdf(pdf_path, analytics, recording_url)

        urls = {}
        try:
            gcs = GcsStorageClient.from_adc()
            report_uploads = [
                ("json_url", json_path, f"reports/{recording_id}/report.json", "application/json"),
                ("csv_url", csv_path, f"reports/{recording_id}/report.csv", "text/csv"),
                ("pdf_url", pdf_path, f"reports/{recording_id}/report.pdf", "application/pdf"),
            ]
            for url_key, local_path, object_path, content_type in report_uploads:
                gs_uri = gcs.upload_object(local_path, object_path, content_type=content_type)
                urls[url_key] = gcs.resolve_access_url(
                    object_path,
                    gs_uri,
                    local_fallback=str(local_path.resolve()),
                )
        except Exception as exc:
            logger.warning("Report GCS upload failed: %s", exc)
            urls = {
                "json_url": str(json_path),
                "csv_url": str(csv_path),
                "pdf_url": str(pdf_path),
            }

        return urls

    @staticmethod
    def generate_json(
        path: Path,
        analytics: CallAnalytics,
        recording_url: str,
        user_audio_url: str,
        agent_audio_url: str,
    ) -> Path:
        payload = {
            "recording_url": recording_url,
            "user_audio_url": user_audio_url,
            "agent_audio_url": agent_audio_url,
            **analytics.model_dump(),
        }
        path.write_text(json.dumps(payload, indent=2))
        return path

    @staticmethod
    def generate_csv(
        path: Path,
        analytics: CallAnalytics,
        recording_url: str,
        user_audio_url: str,
        agent_audio_url: str,
    ) -> Path:
        rows = [
            ("recording_url", recording_url),
            ("user_audio_url", user_audio_url),
            ("agent_audio_url", agent_audio_url),
            ("duration_seconds", analytics.call_duration_seconds),
            ("user_talk_time", analytics.user_talk_time_seconds),
            ("agent_talk_time", analytics.agent_talk_time_seconds),
            ("avg_latency_ms", analytics.avg_agent_latency_ms),
            ("avg_confidence", analytics.avg_user_confidence),
            ("interruptions", analytics.total_interruptions),
            ("sentiment", analytics.sentiment.value),
            ("speaker_switches", analytics.speaker_switches),
            ("silence_duration_seconds", analytics.silence_duration_seconds),
        ]
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            writer.writerows(rows)
        return path

    @staticmethod
    def generate_pdf(path: Path, analytics: CallAnalytics, recording_url: str) -> Path:
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            path.write_text(f"Call Analytics Report\nURL: {recording_url}\n")
            return path

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 50

        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, "Voice Isolation & Call Analytics Report")
        y -= 30
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Recording: {recording_url[:80]}...")
        y -= 40

        metrics = [
            ("Call Duration (s)", analytics.call_duration_seconds),
            ("User Talk Time (s)", analytics.user_talk_time_seconds),
            ("Agent Talk Time (s)", analytics.agent_talk_time_seconds),
            ("Avg Agent Latency (ms)", analytics.avg_agent_latency_ms),
            ("Avg User Confidence", analytics.avg_user_confidence),
            ("Interruptions", analytics.total_interruptions),
            ("Silence (s)", analytics.silence_duration_seconds),
            ("Speaker Switches", analytics.speaker_switches),
            ("Sentiment", analytics.sentiment.value),
            ("User WPM", analytics.user_speaking_rate_wpm),
            ("Agent WPM", analytics.agent_speaking_rate_wpm),
        ]

        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Metrics")
        y -= 20
        c.setFont("Helvetica", 10)
        for label, value in metrics:
            c.drawString(60, y, f"{label}: {value}")
            y -= 16
            if y < 50:
                c.showPage()
                y = height - 50

        c.save()
        path.write_bytes(buffer.getvalue())
        return path
