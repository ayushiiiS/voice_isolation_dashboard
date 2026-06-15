"""Download objects from Google Cloud Storage using Application Default Credentials."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from google.cloud import storage

from src.utils.gcs_auth import (
    GcpIdentity,
    configure_adc_credentials,
    load_gcp_credentials,
    resolve_gcp_identity,
)

logger = logging.getLogger(__name__)


def parse_gcs_location(source: str) -> Optional[tuple[str, str]]:
    """
    Parse a GCS location from gs://, storage.googleapis.com, or bucket/object paths.

    Returns (bucket_name, object_path) or None if not a GCS reference.
    """
    if source.startswith("gs://"):
        without_scheme = source[5:]
        bucket, object_path = without_scheme.split("/", 1)
        return bucket, object_path

    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        host = parsed.netloc.lower()
        if host not in ("storage.googleapis.com", "storage.cloud.google.com"):
            return None
        path = unquote(parsed.path.lstrip("/"))
        if "/" not in path:
            return None
        bucket, object_path = path.split("/", 1)
        return bucket, object_path

    if "/" in source and not Path(source).exists():
        bucket, object_path = source.split("/", 1)
        if bucket and object_path and "." in object_path:
            return bucket, object_path

    return None


def _is_signed_gcs_http_url(source: str) -> bool:
    """Return True when the URL already carries V2/V4 signature query params."""
    parsed = urlparse(source)
    query = parsed.query or ""
    return "X-Goog-Signature" in query or "GoogleAccessId" in query


def download_gcs_object(
    bucket_name: str,
    object_path: str,
    destination: Path,
) -> Path:
    """Download a GCS object using Application Default Credentials."""
    configure_adc_credentials()
    credentials, project, principal, source = load_gcp_credentials()
    identity = GcpIdentity(
        credential_source=source,
        principal_email=principal,
        project_id=project,
        bucket_name=os.getenv("BUCKET_NAME", "cadence-audio"),
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Downloading gs://%s/%s to %s (principal=%s, source=%s)",
        bucket_name,
        object_path,
        destination,
        identity.principal_email,
        identity.credential_source,
    )

    client = storage.Client(credentials=credentials, project=identity.project_id or project)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_path)
    blob.download_to_filename(str(destination))
    logger.info(
        "Downloaded gs://%s/%s (%d bytes)",
        bucket_name,
        object_path,
        destination.stat().st_size,
    )
    return destination


def try_download_gcs_source(source: str, destination: Path) -> Optional[Path]:
    """
    Download from GCS when possible.

    - Signed HTTPS URLs: skip GCS API; caller should HTTP GET the URL as-is.
    - gs:// URIs: require GCS API access; raise if denied.
    - Unsigned storage.googleapis.com URLs: try GCS API, then HTTP fallback.
    """
    location = parse_gcs_location(source)
    if location is None:
        return None

    if _is_signed_gcs_http_url(source):
        logger.info(
            "Signed GCS URL detected; skipping GCS API and using HTTP download"
        )
        return None

    bucket_name, object_path = location

    if source.startswith("gs://"):
        try:
            return download_gcs_object(bucket_name, object_path, destination)
        except Exception as exc:
            identity = resolve_gcp_identity()
            logger.error(
                "GCS download failed for gs://%s/%s: %s",
                bucket_name,
                object_path,
                exc,
            )
            raise RuntimeError(
                f"GCS download failed for gs://{bucket_name}/{object_path} "
                f"using principal '{identity.principal_email}' "
                f"(source={identity.credential_source}): {exc}"
            ) from exc

    # HTTPS storage.googleapis.com without signature — try API, fall back to HTTP GET.
    try:
        return download_gcs_object(bucket_name, object_path, destination)
    except Exception as exc:
        logger.warning(
            "GCS API download failed for %s (will try HTTP GET): %s",
            source.split("?")[0],
            exc,
        )
        return None
