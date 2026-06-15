#!/usr/bin/env python3
"""Upload existing isolated audio files to GCS and write signed URLs to a CSV."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from batch_process import extract_recording_id
from src.utils.gcs_storage import GcsStorageClient, resolve_credentials_path

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload isolated WAV files to GCS and export signed URLs.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("output/isolated_audio"),
        help="Directory containing isolated .wav files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/isolated_audio_urls.csv"),
        help="Output CSV path.",
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
        help="Destination GCS bucket.",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="voice-isolation/isolated",
        help="GCS object prefix.",
    )
    parser.add_argument(
        "--gcs-expiration-hours",
        type=int,
        default=168,
        help="Signed URL lifetime in hours.",
    )
    parser.add_argument(
        "--cleanup-local",
        action="store_true",
        help="Delete local WAV files after successful upload.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = parse_args()

    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        logger.error("Input directory not found: %s", input_dir)
        return 1

    wav_files = sorted(input_dir.glob("*.wav"))
    if not wav_files:
        logger.error("No .wav files found in %s", input_dir)
        return 1

    credentials_path = resolve_credentials_path(args.gcs_credentials)
    client = GcsStorageClient(credentials_path, args.gcs_expiration_hours)
    prefix = args.gcs_prefix.strip("/")

    rows: list[dict[str, str]] = []
    for wav_path in wav_files:
        recording_id = extract_recording_id(str(wav_path))
        object_path = f"{prefix}/{recording_id}/user_only.wav"
        try:
            signed_url = client.upload_and_sign(
                local_path=wav_path,
                bucket_name=args.gcs_bucket,
                object_path=object_path,
            )
            if args.cleanup_local:
                wav_path.unlink()
            rows.append(
                {
                    "recording_id": recording_id,
                    "isolated_audio_url": signed_url,
                    "status": "success",
                    "error": "",
                }
            )
            logger.info("Uploaded %s", recording_id)
        except Exception as exc:
            logger.error("Failed to upload %s: %s", recording_id, exc)
            rows.append(
                {
                    "recording_id": recording_id,
                    "isolated_audio_url": "",
                    "status": "failed",
                    "error": str(exc),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["recording_id", "isolated_audio_url", "status", "error"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)

    succeeded = sum(1 for row in rows if row["status"] == "success")
    logger.info("Wrote %d row(s) (%d succeeded) to %s", len(rows), succeeded, args.output)
    return 0 if succeeded == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
