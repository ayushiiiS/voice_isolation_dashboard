"""Upload files to Google Cloud Storage using Application Default Credentials."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import storage

from src.utils.gcs_auth import (
    GcsPermissionError,
    GcpIdentity,
    credentials_support_signing,
    load_gcp_credentials,
    log_gcp_identity_at_startup,
    permission_for_error,
)

logger = logging.getLogger(__name__)

_identity: Optional[GcpIdentity] = None


class GcsStorageClient:
    """Upload objects to GCS using ADC and return signed download URLs."""

    def __init__(
        self,
        expiration_hours: int = 168,
        object_prefix: str = "",
        identity: Optional[GcpIdentity] = None,
    ) -> None:
        global _identity
        self._credentials, project, principal, source = load_gcp_credentials()
        self._identity = identity or GcpIdentity(
            credential_source=source,
            principal_email=principal,
            project_id=project or os.getenv("GOOGLE_CLOUD_PROJECT"),
            bucket_name=os.getenv("BUCKET_NAME", "cadence-audio"),
        )
        _identity = self._identity

        logger.info(
            "GCS client ready — principal=%s source=%s bucket=gs://%s",
            self._identity.principal_email,
            self._identity.credential_source,
            self._identity.bucket_name,
        )

        self._client = storage.Client(
            credentials=self._credentials,
            project=self._identity.project_id or project,
        )
        self._bucket_name = self._identity.bucket_name
        self._expiration = timedelta(hours=expiration_hours)
        prefix = (object_prefix or os.getenv("GCS_OBJECT_PREFIX", "")).strip("/")
        self.object_prefix = f"{prefix}/" if prefix else ""

    @classmethod
    def from_adc(cls, expiration_hours: int = 168) -> "GcsStorageClient":
        return cls(expiration_hours=expiration_hours)

    @property
    def identity(self) -> GcpIdentity:
        return self._identity

    def _full_object_path(self, object_path: str) -> str:
        object_path = object_path.lstrip("/")
        if self.object_prefix and not object_path.startswith(self.object_prefix):
            return f"{self.object_prefix}{object_path}"
        return object_path

    def upload_object(
        self,
        local_path: Path,
        object_path: str,
        content_type: str = "audio/wav",
        bucket_name: Optional[str] = None,
    ) -> str:
        """Upload a file and return its gs:// URI. Raises GcsPermissionError on 403."""
        bucket_name = bucket_name or self._bucket_name
        full_path = self._full_object_path(object_path)

        logger.info(
            "Uploading %s → gs://%s/%s as %s",
            local_path,
            bucket_name,
            full_path,
            self._identity.principal_email,
        )

        try:
            bucket = self._client.bucket(bucket_name)
            blob = bucket.blob(full_path)
            blob.upload_from_filename(str(local_path), content_type=content_type)
        except gcp_exceptions.Forbidden as exc:
            raise GcsPermissionError(
                principal=self._identity.principal_email,
                bucket=bucket_name,
                object_path=full_path,
                permission=permission_for_error(exc),
                credential_source=self._identity.credential_source,
                original=exc,
            ) from exc
        except gcp_exceptions.GoogleAPIError as exc:
            if getattr(exc, "code", None) == 403:
                raise GcsPermissionError(
                    principal=self._identity.principal_email,
                    bucket=bucket_name,
                    object_path=full_path,
                    permission=permission_for_error(exc),
                    credential_source=self._identity.credential_source,
                    original=exc,
                ) from exc
            raise
        except Exception as exc:
            if "403" in str(exc):
                raise GcsPermissionError(
                    principal=self._identity.principal_email,
                    bucket=bucket_name,
                    object_path=full_path,
                    permission=permission_for_error(exc),
                    credential_source=self._identity.credential_source,
                    original=exc,
                ) from exc
            raise

        gs_uri = f"gs://{bucket_name}/{full_path}"
        logger.info(
            "Uploaded gs://%s/%s (principal=%s)",
            bucket_name,
            full_path,
            self._identity.principal_email,
        )
        return gs_uri

    def try_generate_signed_url(
        self,
        object_path: str,
        bucket_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a V4 signed URL when credentials support signing.

        User OAuth tokens (gcloud_cli) cannot sign URLs without a private key;
        returns None so callers can use local /media URLs or gs:// references.
        """
        bucket_name = bucket_name or self._bucket_name
        full_path = self._full_object_path(object_path)
        gs_uri = f"gs://{bucket_name}/{full_path}"

        if not credentials_support_signing(self._identity.credential_source):
            logger.info(
                "Signed URL skipped | gs_uri=%s credential_source=%s reason=no_signing_key",
                gs_uri,
                self._identity.credential_source,
            )
            return None

        try:
            bucket = self._client.bucket(bucket_name)
            blob = bucket.blob(full_path)
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=self._expiration,
                method="GET",
                credentials=self._credentials,
            )
            logger.info("Signed URL generated | gs_uri=%s", gs_uri)
            return signed_url
        except Exception as exc:
            reason = "no_signing_key" if "private key" in str(exc).lower() else "sign_error"
            logger.warning(
                "Signed URL failed | gs_uri=%s reason=%s error=%s",
                gs_uri,
                reason,
                exc,
            )
            return None

    def resolve_access_url(
        self,
        object_path: str,
        gs_uri: str,
        *,
        local_fallback: Optional[str] = None,
        bucket_name: Optional[str] = None,
    ) -> str:
        """
        Pick the best browser-accessible URL after a successful upload.

        Priority: signed URL → local /media URL → gs:// URI.
        """
        signed = self.try_generate_signed_url(object_path, bucket_name=bucket_name)
        if signed:
            return signed
        if local_fallback:
            logger.info(
                "Using local playback URL | gs_uri=%s playback=%s",
                gs_uri,
                local_fallback,
            )
            return local_fallback
        logger.info(
            "Using gs:// reference (no signed or local URL) | gs_uri=%s",
            gs_uri,
        )
        return gs_uri

    def upload_and_sign(
        self,
        local_path: Path,
        object_path: str,
        content_type: str = "audio/wav",
        bucket_name: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Upload to GCS and return (access_url, gs_uri).

        access_url is a signed URL when supported, otherwise the gs:// URI.
        """
        gs_uri = self.upload_object(
            local_path, object_path, content_type=content_type, bucket_name=bucket_name
        )
        access_url = self.resolve_access_url(object_path, gs_uri, bucket_name=bucket_name)
        return access_url, gs_uri

    def verify_bucket_access(self) -> None:
        """Verify the authenticated principal can access the upload bucket."""
        bucket_name = self._bucket_name
        logger.info(
            "Verifying bucket access for %s on gs://%s",
            self._identity.principal_email,
            bucket_name,
        )
        try:
            bucket = self._client.bucket(bucket_name)
            bucket.reload()
            logger.info("Bucket gs://%s is accessible", bucket_name)
        except gcp_exceptions.Forbidden as exc:
            raise GcsPermissionError(
                principal=self._identity.principal_email,
                bucket=bucket_name,
                object_path="",
                permission="storage.buckets.get (Storage Legacy Bucket Reader)",
                credential_source=self._identity.credential_source,
                original=exc,
            ) from exc


def get_storage_client() -> GcsStorageClient:
    """Return a shared GCS client using ADC."""
    return GcsStorageClient.from_adc()


__all__ = [
    "GcsStorageClient",
    "get_storage_client",
    "log_gcp_identity_at_startup",
    "GcsPermissionError",
]
