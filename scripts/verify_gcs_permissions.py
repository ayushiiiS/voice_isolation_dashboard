#!/usr/bin/env python3
"""Verify GCS bucket permissions for the active authenticated principal."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.utils.gcs_auth import (  # noqa: E402
    GcsPermissionError,
    get_credentials_source,
    load_gcp_credentials,
    resolve_gcp_identity,
)
from src.utils.gcs_storage import GcsStorageClient  # noqa: E402


def main() -> int:
    source_mode = get_credentials_source()
    print(f"GCS_CREDENTIALS_SOURCE={source_mode}")

    try:
        identity = resolve_gcp_identity()
    except Exception as exc:
        print(f"ERROR: Could not resolve GCP identity: {exc}")
        return 1

    print(f"Credential source:  {identity.credential_source}")
    print(f"Active principal:   {identity.principal_email}")
    print(f"GCP project:        {identity.project_id or '(not set)'}")
    print(f"Target bucket:      gs://{identity.bucket_name}")
    print()

    gcs = GcsStorageClient.from_adc()

    # Bucket metadata access
    try:
        gcs.verify_bucket_access()
        print("Bucket metadata:    ACCESSIBLE (storage.buckets.get)")
    except GcsPermissionError as exc:
        print(f"Bucket metadata:    DENIED — {exc}")

    # Object create test
    test_path = Path(tempfile.gettempdir()) / "cadence_gcs_perm_test.txt"
    test_path.write_text("permission test")
    test_object = "uploads/_permission_test.txt"

    print()
    print(f"Object create test: gs://{identity.bucket_name}/{test_object}")
    try:
        gs_uri = gcs.upload_object(test_path, test_object, content_type="text/plain")
        print("Create objects:     ALLOWED (storage.objects.create)")
        print(f"Test object:        {gs_uri}")
        signed = gcs.try_generate_signed_url(test_object)
        if signed:
            print("Signed URLs:        SUPPORTED")
        else:
            print(
                "Signed URLs:        NOT AVAILABLE with user credentials "
                "(uploads succeed; app uses /media/ URLs for playback)"
            )
        print()
        print("RESULT: GCS upload permissions OK.")
        return 0
    except GcsPermissionError as exc:
        print("Create objects:     DENIED (storage.objects.create)")
        print()
        print("EXPLANATION:")
        print(
            f"  Principal '{exc.principal}' can reach bucket '{exc.bucket}' "
            "but cannot create objects."
        )
        print(f"  Missing permission: {exc.permission}")
        print()
        print("  The Voice Isolation app will continue using local storage at:")
        print("    output/processed/{recording_id}/")
        print("    http://localhost:8000/media/{recording_id}/...")
        print()
        print("  Ask a GCP admin to grant Storage Object Admin:")
        print("    gcloud storage buckets add-iam-policy-binding "
              f"gs://{identity.bucket_name} \\")
        print(f'      --member="user:{identity.principal_email}" \\')
        print('      --role="roles/storage.objectAdmin"')
        return 1
    except Exception as exc:
        print(f"Create objects:     ERROR — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
