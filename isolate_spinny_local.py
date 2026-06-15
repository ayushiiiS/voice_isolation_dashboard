#!/usr/bin/env python3
"""Isolate user voice from recording URLs and save WAV files locally."""

from __future__ import annotations

import argparse
import csv
import logging
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests
from tqdm import tqdm

from batch_process import (
    create_http_session,
    extract_recording_id,
    read_recording_urls,
    resolve_audio_file,
    strip_url_query_params,
)
from isolate_user_voice_urls import resolve_pyannote_model_path
from src.diarization.pyannote_service import PyannoteDiarizationService
from src.isolation.pipeline import VoiceIsolationPipeline

logger = logging.getLogger(__name__)

FULL_COLUMNS = [
    "recording_url",
    "recording_id",
    "status",
    "isolated_audio_path",
    "processing_time",
    "error",
]
PATHS_ONLY_COLUMN = "isolated_audio_path"

_worker_state: dict[str, Any] = {}


@dataclass(frozen=True)
class RowResult:
    recording_url: str
    recording_id: str
    status: str
    isolated_audio_path: str
    processing_time: float
    error: str


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
        "isolated_audio_path": result.isolated_audio_path,
        "processing_time": f"{result.processing_time:.3f}",
        "error": result.error,
    }


def write_paths_only_csv(full_results_path: Path, paths_only_path: Path) -> int:
    rows: list[str] = []
    with full_results_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") == "success" and row.get("isolated_audio_path"):
                rows.append(row["isolated_audio_path"])

    paths_only_path.parent.mkdir(parents=True, exist_ok=True)
    with paths_only_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow([PATHS_ONLY_COLUMN])
        for path in rows:
            writer.writerow([path])
    return len(rows)


def process_recording(
    recording_url: str,
    output_dir: Path,
    downloads_dir: Path,
    session: requests.Session,
    pipeline: VoiceIsolationPipeline,
) -> RowResult:
    clean_url = strip_url_query_params(recording_url)
    recording_id = extract_recording_id(clean_url)
    start = time.perf_counter()
    work_dir = Path(tempfile.mkdtemp(prefix=f"vi_{recording_id}_"))
    isolated_dest = output_dir / f"{recording_id}.wav"

    try:
        if isolated_dest.exists() and isolated_dest.stat().st_size > 0:
            elapsed = round(time.perf_counter() - start, 3)
            logger.info("Skipping %s (already exists)", recording_id)
            return RowResult(
                recording_url=clean_url,
                recording_id=recording_id,
                status="success",
                isolated_audio_path=str(isolated_dest.resolve()),
                processing_time=elapsed,
                error="",
            )

        local_audio_path = resolve_audio_file(
            source=recording_url,
            download_dir=downloads_dir,
            recording_id=recording_id,
            session=session,
            logger=logger,
        )

        result = pipeline.run(
            audio_path=str(local_audio_path.resolve()),
            output_dir=str(work_dir),
        )

        isolated_source = Path(result.isolated_audio_path)
        if not isolated_source.exists():
            raise FileNotFoundError(f"Isolation output not found: {isolated_source}")

        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(isolated_source, isolated_dest)

        elapsed = round(time.perf_counter() - start, 3)
        logger.info("Processed %s -> %s", recording_id, isolated_dest)
        return RowResult(
            recording_url=clean_url,
            recording_id=recording_id,
            status="success",
            isolated_audio_path=str(isolated_dest.resolve()),
            processing_time=elapsed,
            error="",
        )
    except Exception as exc:
        elapsed = round(time.perf_counter() - start, 3)
        logger.error("Failed %s: %s", recording_id, exc)
        return RowResult(
            recording_url=clean_url,
            recording_id=recording_id,
            status="failed",
            isolated_audio_path="",
            processing_time=elapsed,
            error=str(exc),
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _init_worker(device: str, output_dir: str, downloads_dir: str) -> None:
    """Load one pyannote pipeline per worker process."""
    resolve_pyannote_model_path()

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        default_credentials = Path("secrets/bm-gcs-credentials.json").resolve()
        if default_credentials.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(default_credentials)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(processName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    global _worker_state
    _worker_state = {
        "pipeline": VoiceIsolationPipeline(
            diarization_service=PyannoteDiarizationService(device=device),
        ),
        "session": create_http_session(),
        "output_dir": Path(output_dir),
        "downloads_dir": Path(downloads_dir),
    }


def _process_recording_worker(recording_url: str) -> RowResult:
    return process_recording(
        recording_url=recording_url,
        output_dir=_worker_state["output_dir"],
        downloads_dir=_worker_state["downloads_dir"],
        session=_worker_state["session"],
        pipeline=_worker_state["pipeline"],
    )


def _run_batch(
    pending_urls: list[str],
    workers: int,
    device: str,
    output_dir: Path,
    downloads_dir: Path,
    writer: IncrementalCsvWriter,
) -> list[RowResult]:
    results: list[RowResult] = []

    if workers == 1:
        session = create_http_session()
        pipeline = VoiceIsolationPipeline(
            diarization_service=PyannoteDiarizationService(device=device),
        )
        with tqdm(total=len(pending_urls), desc="Isolating user voice", unit="recording") as progress:
            for url in pending_urls:
                try:
                    result = process_recording(
                        url, output_dir, downloads_dir, session, pipeline
                    )
                except Exception as exc:
                    clean = strip_url_query_params(url)
                    result = RowResult(
                        recording_url=clean,
                        recording_id=extract_recording_id(clean),
                        status="failed",
                        isolated_audio_path="",
                        processing_time=0.0,
                        error=f"Worker failure: {exc}",
                    )
                results.append(result)
                writer.append(row_to_dict(result))
                progress.update(1)
                progress.set_postfix(id=result.recording_id, status=result.status)
        return results

    mp_context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=mp_context,
        initializer=_init_worker,
        initargs=(device, str(output_dir), str(downloads_dir)),
    ) as executor:
        futures = {
            executor.submit(_process_recording_worker, url): url for url in pending_urls
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
                        isolated_audio_path="",
                        processing_time=0.0,
                        error=f"Worker failure: {exc}",
                    )
                results.append(result)
                writer.append(row_to_dict(result))
                progress.update(1)
                progress.set_postfix(id=result.recording_id, status=result.status)

    return results


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Isolate user voice from recording URLs and save locally.",
    )
    parser.add_argument(
        "--input",
        default="output/public_urls_urls_only.csv",
        help="CSV with recording_url column.",
    )
    parser.add_argument(
        "--output-dir",
        default="spinny_aryan_isolated_audio",
        help="Directory for isolated WAV files and CSV output.",
    )
    parser.add_argument(
        "--results",
        default=None,
        help="Full results CSV (default: <output-dir>/isolated_audio_results.csv).",
    )
    parser.add_argument(
        "--paths-only-output",
        default=None,
        help="Paths-only CSV (default: <output-dir>/isolated_audio_paths_only.csv).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Parallel worker processes (default: 3; each loads its own model).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip recording IDs already marked success in the results CSV.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N recordings (0 = all).",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=("auto", "cpu", "mps", "cuda"),
        help="Pyannote device: auto (mps/cuda/cpu), or force cpu/mps/cuda.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def resolve_device(device: str) -> str:
    """Pick the best available inference device."""
    if device != "auto":
        return device

    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def setup_logging(output_dir: Path, verbose: bool) -> None:
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"batch_{time.strftime('%Y%m%d_%H%M%S')}.log"

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    logger.info("Logging to %s", log_file)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    results_path = Path(args.results or output_dir / "isolated_audio_results.csv").resolve()
    paths_only_path = Path(
        args.paths_only_output or output_dir / "isolated_audio_paths_only.csv"
    ).resolve()
    downloads_dir = output_dir / "downloads"

    setup_logging(output_dir, args.verbose)

    if args.workers < 1:
        logger.error("--workers must be at least 1")
        return 1

    resolve_pyannote_model_path()
    resolved_device = resolve_device(args.device)

    if args.workers > 1 and resolved_device in ("mps", "cuda"):
        logger.info(
            "Parallel mode uses CPU workers (%d processes); GPU (%s) is single-worker only.",
            args.workers,
            resolved_device,
        )
        resolved_device = "cpu"

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        default_credentials = Path("secrets/bm-gcs-credentials.json").resolve()
        if default_credentials.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(default_credentials)
            logger.info("Using GCS credentials: %s", default_credentials)

    input_path = Path(args.input).resolve()
    try:
        recording_urls = read_recording_urls(input_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    completed_ids: set[str] = set()
    if args.resume:
        completed_ids = load_completed_ids(results_path)
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
        count = write_paths_only_csv(results_path, paths_only_path)
        logger.info("Nothing to process. Wrote %d path(s) to %s", count, paths_only_path)
        return 0

    writer = IncrementalCsvWriter(results_path, FULL_COLUMNS)

    logger.info(
        "Processing %d recording(s) into %s with %d worker(s) on %s",
        len(pending_urls),
        output_dir,
        args.workers,
        resolved_device,
    )

    results = _run_batch(
        pending_urls=pending_urls,
        workers=args.workers,
        device=resolved_device,
        output_dir=output_dir,
        downloads_dir=downloads_dir,
        writer=writer,
    )

    succeeded = sum(1 for result in results if result.status == "success")
    failed = len(results) - succeeded
    path_count = write_paths_only_csv(results_path, paths_only_path)

    logger.info(
        "Done: %d succeeded, %d failed. Results: %s. Paths-only (%d): %s",
        succeeded,
        failed,
        results_path,
        path_count,
        paths_only_path,
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
