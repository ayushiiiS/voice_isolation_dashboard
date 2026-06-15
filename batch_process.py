"""Production batch processor for the voice isolation FastAPI service."""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import requests
from tqdm import tqdm

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_OUTPUT_DIR = "output"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
DOWNLOAD_TIMEOUT_SECONDS = 120
ISOLATE_TIMEOUT_SECONDS = 600
SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}

LOCAL_RESULT_COLUMNS = [
    "recording_url",
    "status",
    "processing_time",
    "output_audio",
    "error",
]

URL_RESULT_COLUMNS = [
    "recording_url",
    "status",
    "processing_time",
    "isolated_audio_url",
    "error",
]


@dataclass(frozen=True)
class GcsUploadConfig:
    credentials_path: Path
    bucket_name: str
    object_prefix: str
    expiration_hours: int
    cleanup_local: bool


@dataclass(frozen=True)
class ProcessingResult:
    recording_url: str
    status: str
    processing_time: float
    output_audio: str
    error: str
    isolated_audio_url: str = ""


def setup_logging(log_dir: Path, verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"

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

    logging.getLogger(__name__).info("Logging to %s", log_file)


def extract_recording_id(source: str) -> str:
    """Derive a stable identifier from a URL, GCS path, or local file path."""
    local_path = Path(source).expanduser()
    if local_path.suffix.lower() in SUPPORTED_EXTENSIONS:
        if local_path.stem and local_path.stem != "recording":
            return local_path.stem

    path = urlparse(source).path if urlparse(source).scheme else source
    parts = [part for part in path.split("/") if part]

    for index, part in enumerate(parts):
        if part == "recording" and index + 1 < len(parts):
            candidate = parts[index + 1]
            if candidate and candidate != "recording.ogg":
                return candidate

    suffix = Path(path).stem or "recording"
    url_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return f"{suffix}_{url_hash}"


def read_recording_urls(input_path: Path) -> list[str]:
    """Read recording URLs from a CSV file."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    urls: list[str] = []
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames and "recording_url" in reader.fieldnames:
            for row in reader:
                url = (row.get("recording_url") or "").strip()
                if url:
                    urls.append(url)
        else:
            handle.seek(0)
            for line in handle:
                url = line.strip()
                if url and not url.lower().startswith("recording_url"):
                    urls.append(url)

    if not urls:
        raise ValueError(f"No recording URLs found in {input_path}")

    return urls


def _infer_extension(source: str) -> str:
    parsed = urlparse(source)
    extension = Path(parsed.path).suffix.lower() if parsed.scheme else Path(source).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        extension = ".ogg"
    return extension


def resolve_audio_file(
    source: str,
    download_dir: Path,
    recording_id: str,
    session: requests.Session,
    logger: logging.Logger,
) -> Path:
    """
    Resolve a recording to a local audio file.

    Order: existing local path -> cached download -> GCS API -> signed HTTPS URL.
    """
    from src.utils.gcs_download import try_download_gcs_source

    local_path = Path(source).expanduser()
    if local_path.exists():
        logger.info("Using local audio file for %s: %s", recording_id, local_path)
        return local_path.resolve()

    extension = _infer_extension(source)
    destination = download_dir / f"{recording_id}{extension}"
    if destination.exists() and destination.stat().st_size > 0:
        logger.debug("Using cached download for %s", recording_id)
        return destination.resolve()

    download_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(source)
    is_signed_url = "X-Goog-Signature" in (parsed.query or "")

    if not is_signed_url:
        try:
            gcs_path = try_download_gcs_source(source, destination)
            if gcs_path is not None:
                logger.info("Downloaded %s via GCS API to %s", recording_id, gcs_path)
                return gcs_path.resolve()
        except RuntimeError as exc:
            logger.warning(
                "GCS API download failed for %s, falling back to HTTPS: %s",
                recording_id,
                exc,
            )

    if parsed.scheme not in ("http", "https"):
        raise FileNotFoundError(
            f"Could not resolve audio source for {recording_id}: {source}. "
            "Provide a local path, gs:// URI, or HTTPS URL."
        )

    logger.info("Downloading audio for %s via signed URL", recording_id)
    response = session.get(source, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()

    with destination.open("wb") as handle:
        first_chunk = True
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            if first_chunk and (chunk.startswith(b"<?xml") or chunk.startswith(b"<Error")):
                raise RuntimeError(
                    "Signed GCS URL expired or invalid (SignatureDoesNotMatch). "
                    "Use local paths in recordings.csv (e.g. output/downloads/<id>.ogg), "
                    "set GOOGLE_APPLICATION_CREDENTIALS for direct GCS access, "
                    "or regenerate fresh signed URLs."
                )
            first_chunk = False
            handle.write(chunk)

    if destination.stat().st_size == 0:
        raise RuntimeError("Download returned an empty file.")

    logger.info("Downloaded %s to %s", recording_id, destination)
    return destination.resolve()


def build_recordings_csv_from_downloads(
    downloads_dir: Path,
    output_path: Path,
) -> int:
    """Write a CSV of local paths from files in the downloads directory."""
    files = sorted(
        path
        for path in downloads_dir.glob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["recording_url"])
        for path in files:
            writer.writerow([str(path.resolve())])
    return len(files)


def call_isolate_api(
    api_url: str,
    audio_path: str,
    work_dir: Path,
    session: requests.Session,
    logger: logging.Logger,
) -> dict[str, Any]:
    """POST to /isolate with retries on transient failures."""
    endpoint = f"{api_url.rstrip('/')}/isolate"
    payload = {
        "audio_path": audio_path,
        "agent_transcript": [],
        "output_dir": str(work_dir.resolve()),
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Calling isolate API for %s (attempt %d/%d)",
                audio_path,
                attempt,
                MAX_RETRIES,
            )
            response = session.post(
                endpoint,
                json=payload,
                timeout=ISOLATE_TIMEOUT_SECONDS,
            )

            if response.status_code >= 500:
                raise requests.HTTPError(
                    f"Server error {response.status_code}: {response.text}",
                    response=response,
                )

            if response.status_code >= 400:
                detail = response.text
                try:
                    detail = response.json().get("detail", detail)
                except ValueError:
                    pass
                raise RuntimeError(f"API error {response.status_code}: {detail}")

            return response.json()

        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            logger.warning(
                "Isolate request failed for %s on attempt %d/%d: %s",
                audio_path,
                attempt,
                MAX_RETRIES,
                exc,
            )
            if attempt < MAX_RETRIES:
                sleep_seconds = RETRY_BACKOFF_SECONDS * attempt
                time.sleep(sleep_seconds)

    raise RuntimeError(f"Isolate API failed after {MAX_RETRIES} attempts: {last_error}")


def strip_url_query_params(url: str) -> str:
    """Return the URL without query parameters."""
    parsed = urlparse(url.strip())
    return urlunparse(parsed._replace(query="", fragment=""))


def upload_isolated_audio(
    local_path: Path,
    recording_id: str,
    gcs_config: GcsUploadConfig,
    logger: logging.Logger,
) -> str:
    """Upload isolated audio to GCS and return a signed URL."""
    from src.utils.gcs_storage import GcsStorageClient

    object_path = f"{gcs_config.object_prefix.strip('/')}/{recording_id}/user_only.wav"
    client = GcsStorageClient(
        credentials_path=gcs_config.credentials_path,
        expiration_hours=gcs_config.expiration_hours,
    )
    signed_url = client.upload_and_sign(
        local_path=local_path,
        bucket_name=gcs_config.bucket_name,
        object_path=object_path,
    )
    logger.info("Uploaded isolated audio for %s to gs://%s/%s", recording_id, gcs_config.bucket_name, object_path)
    return signed_url


def cleanup_local_files(
    paths: list[Path],
    logger: logging.Logger,
) -> None:
    """Remove temporary local files after upload."""
    for path in paths:
        try:
            if path.exists():
                path.unlink()
                logger.debug("Removed local file %s", path)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)


def collect_outputs(
    api_response: dict[str, Any],
    recording_id: str,
    isolated_dir: Path,
    diarization_dir: Path,
    logger: logging.Logger,
) -> Path:
    """Copy API output files into the organized batch output directories."""
    isolated_source = Path(api_response["isolated_audio_path"])
    json_source = Path(api_response["diarization_json_path"])
    rttm_source = Path(api_response["diarization_rttm_path"])

    isolated_dest = isolated_dir / f"{recording_id}.wav"
    json_dest = diarization_dir / f"{recording_id}.json"
    rttm_dest = diarization_dir / f"{recording_id}.rttm"

    isolated_dir.mkdir(parents=True, exist_ok=True)
    diarization_dir.mkdir(parents=True, exist_ok=True)

    for source, destination in (
        (isolated_source, isolated_dest),
        (json_source, json_dest),
        (rttm_source, rttm_dest),
    ):
        if not source.exists():
            raise FileNotFoundError(f"Expected output file not found: {source}")
        shutil.copy2(source, destination)
        logger.debug("Copied %s -> %s", source, destination)

    return isolated_dest


def create_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
    return session


def process_recording(
    recording_url: str,
    api_url: str,
    output_root: Path,
    gcs_config: Optional[GcsUploadConfig] = None,
) -> ProcessingResult:
    """Download, isolate, and store outputs for a single recording."""
    logger = logging.getLogger(__name__)
    session = create_http_session()
    recording_id = extract_recording_id(recording_url)
    start_time = time.perf_counter()
    clean_recording_url = strip_url_query_params(recording_url)

    downloads_dir = output_root / "downloads"
    work_dir = output_root / ".work" / recording_id
    isolated_dir = output_root / "isolated_audio"
    diarization_dir = output_root / "diarization"
    local_audio_path: Optional[Path] = None
    output_audio: Optional[Path] = None

    try:
        local_audio_path = resolve_audio_file(
            source=recording_url,
            download_dir=downloads_dir,
            recording_id=recording_id,
            session=session,
            logger=logger,
        )

        api_response = call_isolate_api(
            api_url=api_url,
            audio_path=str(local_audio_path.resolve()),
            work_dir=work_dir,
            session=session,
            logger=logger,
        )

        output_audio = collect_outputs(
            api_response=api_response,
            recording_id=recording_id,
            isolated_dir=isolated_dir,
            diarization_dir=diarization_dir,
            logger=logger,
        )

        isolated_audio_url = ""
        if gcs_config is not None:
            isolated_audio_url = upload_isolated_audio(
                local_path=output_audio,
                recording_id=recording_id,
                gcs_config=gcs_config,
                logger=logger,
            )
            if gcs_config.cleanup_local:
                cleanup_local_files(
                    [
                        local_audio_path,
                        output_audio,
                        diarization_dir / f"{recording_id}.json",
                        diarization_dir / f"{recording_id}.rttm",
                    ],
                    logger,
                )
                if work_dir.exists():
                    shutil.rmtree(work_dir, ignore_errors=True)

        elapsed = round(time.perf_counter() - start_time, 3)
        logger.info(
            "Successfully processed %s in %.3fs -> %s",
            recording_id,
            elapsed,
            isolated_audio_url or output_audio,
        )
        return ProcessingResult(
            recording_url=clean_recording_url,
            status="success",
            processing_time=elapsed,
            output_audio="" if gcs_config else str(output_audio.resolve()),
            isolated_audio_url=isolated_audio_url,
            error="",
        )

    except Exception as exc:
        elapsed = round(time.perf_counter() - start_time, 3)
        logger.error("Failed to process %s: %s", recording_id, exc, exc_info=True)
        return ProcessingResult(
            recording_url=clean_recording_url,
            status="failed",
            processing_time=elapsed,
            output_audio="",
            isolated_audio_url="",
            error=str(exc),
        )


def result_columns(url_output: bool) -> list[str]:
    return URL_RESULT_COLUMNS if url_output else LOCAL_RESULT_COLUMNS


def result_to_row(result: ProcessingResult, url_output: bool) -> dict[str, Any]:
    row = {
        "recording_url": result.recording_url,
        "status": result.status,
        "processing_time": result.processing_time,
        "error": result.error,
    }
    if url_output:
        row["isolated_audio_url"] = result.isolated_audio_url
    else:
        row["output_audio"] = result.output_audio
    return row


class IncrementalResultsWriter:
    """Append batch results to CSV as each recording completes."""

    def __init__(self, results_path: Path, url_output: bool) -> None:
        self.results_path = results_path
        self.url_output = url_output
        self._lock = threading.Lock()
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        with self.results_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=result_columns(url_output), quoting=csv.QUOTE_ALL)
            writer.writeheader()

    def append(self, result: ProcessingResult) -> None:
        with self._lock:
            with self.results_path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=result_columns(self.url_output),
                    quoting=csv.QUOTE_ALL,
                )
                writer.writerow(result_to_row(result, self.url_output))


def write_results_csv(
    results_path: Path,
    results: list[ProcessingResult],
    url_output: bool,
) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=result_columns(url_output),
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for result in results:
            writer.writerow(result_to_row(result, url_output))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch process call recordings through the voice isolation API.",
    )
    parser.add_argument(
        "--input",
        default="recordings.csv",
        help="CSV file with a recording_url column (default: recordings.csv)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent workers (default: 4)",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Voice isolation API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Root output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--results",
        default=None,
        help="Path for results CSV (default: <output-dir>/results.csv)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--build-local-csv",
        action="store_true",
        help=(
            "Write recordings.csv from cached files in <output-dir>/downloads/ "
            "and exit (avoids expired signed URLs)"
        ),
    )
    parser.add_argument(
        "--output-urls",
        action="store_true",
        help="Upload isolated audio to GCS and write signed URLs in the results CSV.",
    )
    parser.add_argument(
        "--gcs-credentials",
        type=Path,
        default=None,
        help="Service-account JSON for GCS upload (or use GOOGLE_APPLICATION_CREDENTIALS).",
    )
    parser.add_argument(
        "--gcs-bucket",
        default="bluemachines-prod",
        help="GCS bucket for isolated audio uploads (default: bluemachines-prod).",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="voice-isolation/isolated",
        help="GCS object prefix for isolated audio (default: voice-isolation/isolated).",
    )
    parser.add_argument(
        "--gcs-expiration-hours",
        type=int,
        default=168,
        help="Signed URL lifetime for uploaded isolated audio (default: 168 hours).",
    )
    parser.add_argument(
        "--cleanup-local",
        action="store_true",
        help="Delete local downloads and isolated files after uploading to GCS.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    output_root = Path(args.output_dir).resolve()
    results_path = Path(args.results or output_root / "results.csv").resolve()
    input_path = Path(args.input).resolve()

    if args.workers < 1:
        logging.error("--workers must be at least 1")
        return 1

    if args.build_local_csv:
        downloads_dir = output_root / "downloads"
        count = build_recordings_csv_from_downloads(downloads_dir, input_path)
        print(f"Wrote {count} local paths to {input_path}")
        return 0 if count > 0 else 1

    setup_logging(output_root / "logs", verbose=args.verbose)
    logger = logging.getLogger(__name__)

    gcs_config: Optional[GcsUploadConfig] = None
    if args.output_urls:
        try:
            from src.utils.gcs_storage import resolve_credentials_path

            credentials_path = resolve_credentials_path(args.gcs_credentials)
            if args.gcs_expiration_hours <= 0:
                raise ValueError("--gcs-expiration-hours must be greater than 0.")
            gcs_config = GcsUploadConfig(
                credentials_path=credentials_path,
                bucket_name=args.gcs_bucket,
                object_prefix=args.gcs_prefix,
                expiration_hours=args.gcs_expiration_hours,
                cleanup_local=args.cleanup_local,
            )
            logger.info(
                "URL output enabled: gs://%s/%s/ (expires in %d hours)",
                gcs_config.bucket_name,
                gcs_config.object_prefix,
                gcs_config.expiration_hours,
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return 1

    try:
        recording_urls = read_recording_urls(input_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    logger.info(
        "Starting batch processing: %d recordings, %d workers, API=%s, output=%s",
        len(recording_urls),
        args.workers,
        args.api_url,
        "signed URLs" if gcs_config else "local paths",
    )

    health_check_url = f"{args.api_url.rstrip('/')}/health"
    try:
        health_response = requests.get(health_check_url, timeout=10)
        health_response.raise_for_status()
        logger.info("API health check passed: %s", health_response.json())
    except requests.RequestException as exc:
        logger.error("API health check failed (%s): %s", health_check_url, exc)
        return 1

    results: list[ProcessingResult] = []
    results_writer = IncrementalResultsWriter(results_path, url_output=gcs_config is not None)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_recording,
                recording_url,
                args.api_url,
                output_root,
                gcs_config,
            ): recording_url
            for recording_url in recording_urls
        }

        with tqdm(total=len(futures), desc="Processing recordings", unit="recording") as progress:
            for future in as_completed(futures):
                recording_url = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.error(
                        "Unexpected worker failure for %s: %s",
                        recording_url,
                        exc,
                        exc_info=True,
                    )
                    result = ProcessingResult(
                        recording_url=strip_url_query_params(recording_url),
                        status="failed",
                        processing_time=0.0,
                        output_audio="",
                        isolated_audio_url="",
                        error=f"Worker failure: {exc}",
                    )
                results.append(result)
                results_writer.append(result)
                progress.update(1)
                progress.set_postfix(
                    last=extract_recording_id(recording_url),
                    status=result.status,
                )

    succeeded = sum(1 for result in results if result.status == "success")
    failed = len(results) - succeeded
    logger.info(
        "Batch complete: %d succeeded, %d failed. Results written to %s",
        succeeded,
        failed,
        results_path,
    )

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
