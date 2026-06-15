#!/usr/bin/env python3
"""Isolate user voice from GCS recording URLs and export signed URLs.

Source audio is fetched from GCS into temporary files only (never saved under
output/downloads). Isolated audio is uploaded to GCS when credentials allow it.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from batch_process import (
    extract_recording_id,
    read_recording_urls,
    strip_url_query_params,
)
from src.isolation.pipeline import VoiceIsolationPipeline
from src.utils.gcs_download import parse_gcs_location
from src.utils.gcs_storage import GcsStorageClient, resolve_credentials_path

logger = logging.getLogger(__name__)

FULL_COLUMNS = [
    "recording_url",
    "recording_id",
    "status",
    "user_voice_url",
    "gcs_object_path",
    "processing_time",
    "error",
]
URLS_ONLY_COLUMN = "user_voice_url"


@dataclass(frozen=True)
class RowResult:
    recording_url: str
    recording_id: str
    status: str
    user_voice_url: str
    gcs_object_path: str
    processing_time: float
    error: str


def resolve_pyannote_model_path() -> None:
    """Use cached Community-1 model when HF_TOKEN is not set."""
    if os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("PYANNOTE_MODEL_PATH"):
        return

    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    model_dir = cache_root / "models--pyannote--speaker-diarization-community-1" / "snapshots"
    if not model_dir.is_dir():
        return

    snapshots = sorted(path for path in model_dir.iterdir() if path.is_dir())
    if snapshots:
        os.environ["PYANNOTE_MODEL_PATH"] = str(snapshots[-1])
        logger.info("Using cached pyannote model: %s", snapshots[-1])


def isolated_object_path(recording_url: str) -> tuple[str, str]:
    """Return (bucket, object_path) for the isolated user-only WAV."""
    clean_url = strip_url_query_params(recording_url)
    location = parse_gcs_location(clean_url)
    if location is None:
        raise ValueError(f"Not a GCS recording URL: {recording_url}")

    bucket_name, object_path = location
    folder, _ = object_path.rsplit("/", 1)
    return bucket_name, f"{folder}/user_only.wav"


def load_completed_ids(results_path: Path) -> set[str]:
    if not results_path.exists():
        return set()

    completed: set[str] = set()
    with results_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") == "success" and row.get("recording_id"):
                completed.add(row["recording_id"])
    return completed


class IncrementalCsvWriter:
    def __init__(self, path: Path, fieldnames: list[str]) -> None:
        self.path = path
        self.fieldnames = fieldnames
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL).writeheader()

    def append(self, row: dict[str, str]) -> None:
        with self._lock:
            with self.path.open("a", newline="", encoding="utf-8") as handle:
                csv.DictWriter(
                    handle,
                    fieldnames=self.fieldnames,
                    quoting=csv.QUOTE_ALL,
                ).writerow(row)


def row_to_dict(result: RowResult) -> dict[str, str]:
    return {
        "recording_url": result.recording_url,
        "recording_id": result.recording_id,
        "status": result.status,
        "user_voice_url": result.user_voice_url,
        "gcs_object_path": result.gcs_object_path,
        "processing_time": f"{result.processing_time:.3f}",
        "error": result.error,
    }


def write_urls_only_csv(full_results_path: Path, urls_only_path: Path) -> int:
    rows: list[str] = []
    with full_results_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") == "success" and row.get("user_voice_url"):
                rows.append(row["user_voice_url"])

    urls_only_path.parent.mkdir(parents=True, exist_ok=True)
    with urls_only_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow([URLS_ONLY_COLUMN])
        for url in rows:
            writer.writerow([url])
    return len(rows)


def process_recording(
    recording_url: str,
    gcs_client: GcsStorageClient,
    bucket_name: str,
    expiration_hours: int,
) -> RowResult:
    import time

    clean_url = strip_url_query_params(recording_url)
    recording_id = extract_recording_id(clean_url)
    start = time.perf_counter()
    work_dir = Path(tempfile.mkdtemp(prefix=f"vi_{recording_id}_"))

    try:
        target_bucket, object_path = isolated_object_path(clean_url)
        if target_bucket != bucket_name:
            raise ValueError(
                f"Recording bucket {target_bucket} does not match configured bucket {bucket_name}"
            )

        pipeline = VoiceIsolationPipeline()
        result = pipeline.run(audio_path=clean_url, output_dir=str(work_dir))

        signed_url = gcs_client.upload_and_sign(
            local_path=Path(result.isolated_audio_path),
            bucket_name=bucket_name,
            object_path=object_path,
        )

        elapsed = round(time.perf_counter() - start, 3)
        logger.info("Processed %s -> %s", recording_id, object_path)
        return RowResult(
            recording_url=clean_url,
            recording_id=recording_id,
            status="success",
            user_voice_url=signed_url,
            gcs_object_path=f"gs://{bucket_name}/{object_path}",
            processing_time=elapsed,
            error="",
        )
    except Exception as exc:
        elapsed = round(time.perf_counter() - start, 3)
        logger.error("Failed %s: %s", recording_id, exc)
        object_path = ""
        try:
            _, object_path = isolated_object_path(clean_url)
            object_path = f"gs://{bucket_name}/{object_path}"
        except ValueError:
            pass
        return RowResult(
            recording_url=clean_url,
            recording_id=recording_id,
            status="failed",
            user_voice_url="",
            gcs_object_path=object_path,
            processing_time=elapsed,
            error=str(exc),
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Isolate user voice from recording URLs and export signed GCS URLs.",
    )
    parser.add_argument(
        "--input",
        default="output/public_urls_urls_only.csv",
        help="CSV with recording_url column (default: output/public_urls_urls_only.csv)",
    )
    parser.add_argument(
        "--output",
        default="output/user_voice_urls.csv",
        help="Full results CSV path (default: output/user_voice_urls.csv)",
    )
    parser.add_argument(
        "--urls-only-output",
        default="output/user_voice_urls_only.csv",
        help="URLs-only CSV path (default: output/user_voice_urls_only.csv)",
    )
    parser.add_argument(
        "--gcs-credentials",
        type=Path,
        default=None,
        help="Service-account JSON (or use GOOGLE_APPLICATION_CREDENTIALS).",
    )
    parser.add_argument(
        "--gcs-bucket",
        default="bluemachines-prod",
        help="Destination GCS bucket (default: bluemachines-prod).",
    )
    parser.add_argument(
        "--gcs-expiration-hours",
        type=int,
        default=168,
        help="Signed URL lifetime in hours (default: 168).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers (default: 1; pyannote is memory-heavy).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip recording IDs already marked success in the output CSV.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N recordings (0 = all).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    if args.workers < 1:
        logger.error("--workers must be at least 1")
        return 1

    resolve_pyannote_model_path()

    try:
        credentials_path = resolve_credentials_path(args.gcs_credentials)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    urls_only_path = Path(args.urls_only_output).resolve()

    try:
        recording_urls = read_recording_urls(input_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    completed_ids: set[str] = set()
    if args.resume:
        completed_ids = load_completed_ids(output_path)
        if completed_ids:
            logger.info("Resuming: skipping %d completed recording(s)", len(completed_ids))

    pending_urls = [
        url
        for url in recording_urls
        if extract_recording_id(strip_url_query_params(url)) not in completed_ids
    ]
    if args.limit > 0:
        pending_urls = pending_urls[: args.limit]

    if not pending_urls:
        count = write_urls_only_csv(output_path, urls_only_path)
        logger.info("Nothing to process. Wrote %d URL(s) to %s", count, urls_only_path)
        return 0

    gcs_client = GcsStorageClient(credentials_path, args.gcs_expiration_hours)
    writer = IncrementalCsvWriter(output_path, FULL_COLUMNS)

    logger.info(
        "Processing %d recording(s) with %d worker(s); temp-only source fetch",
        len(pending_urls),
        args.workers,
    )

    results: list[RowResult] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_recording,
                url,
                gcs_client,
                args.gcs_bucket,
                args.gcs_expiration_hours,
            ): url
            for url in pending_urls
        }

        with tqdm(total=len(futures), desc="Isolating user voice", unit="recording") as progress:
            for future in as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    clean = strip_url_query_params(url)
                    result = RowResult(
                        recording_url=clean,
                        recording_id=extract_recording_id(clean),
                        status="failed",
                        user_voice_url="",
                        gcs_object_path="",
                        processing_time=0.0,
                        error=f"Worker failure: {exc}",
                    )
                results.append(result)
                writer.append(row_to_dict(result))
                progress.update(1)
                progress.set_postfix(id=result.recording_id, status=result.status)

    succeeded = sum(1 for result in results if result.status == "success")
    failed = len(results) - succeeded
    url_count = write_urls_only_csv(output_path, urls_only_path)

    logger.info(
        "Done: %d succeeded, %d failed. Full results: %s. URLs-only (%d): %s",
        succeeded,
        failed,
        output_path,
        url_count,
        urls_only_path,
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
