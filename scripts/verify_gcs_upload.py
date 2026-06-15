#!/usr/bin/env python3
"""Verify GCS upload to cadence-audio using Application Default Credentials."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.utils.gcs_auth import GcsPermissionError, log_gcp_identity_at_startup
from src.utils.gcs_storage import GcsStorageClient


def main() -> int:
    identity = log_gcp_identity_at_startup()
    print(f"Credential source: {identity.credential_source}")
    print(f"Principal:         {identity.principal_email}")
    print(f"Project:           {identity.project_id}")
    print(f"Bucket:            gs://{identity.bucket_name}")

    gcs = GcsStorageClient.from_adc()
    gcs.verify_bucket_access()

    test_file = Path("output/processed/_adc_upload_test.txt")
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("adc upload test")

    try:
        gs_uri = gcs.upload_object(
            test_file,
            "uploads/_adc_upload_test.txt",
            content_type="text/plain",
        )
        print(f"Upload OK: {gs_uri}")
        signed = gcs.try_generate_signed_url("uploads/_adc_upload_test.txt")
        if signed:
            print(f"Signed URL: {signed[:80]}...")
        else:
            print("Signed URL: not available (user credentials); object stored at gs:// URI above")
        return 0
    except GcsPermissionError as exc:
        print(f"PERMISSION DENIED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
