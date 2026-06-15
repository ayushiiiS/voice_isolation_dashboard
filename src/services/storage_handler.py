"""Resolve storage URLs with GCS upload and local fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from src.services.storage_urls import local_media_url, processed_dir
from src.utils.gcs_auth import GcsPermissionError
from src.utils.gcs_storage import GcsStorageClient

logger = logging.getLogger(__name__)

StorageType = Literal["gcs", "local"]
UploadStatus = Literal["success", "failed"]


@dataclass
class StorageResult:
    user_audio_url: str
    agent_audio_url: str
    diarization_url: str
    storage_type: StorageType
    storage_uri: str
    upload_status: UploadStatus
    user_gs_uri: Optional[str] = None
    agent_gs_uri: Optional[str] = None
    gcs_error: Optional[str] = None
    gcs_principal: Optional[str] = None
    gcs_bucket: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "user_audio_url": self.user_audio_url,
            "agent_audio_url": self.agent_audio_url,
            "diarization_url": self.diarization_url,
            "storage_type": self.storage_type,
            "storage_uri": self.storage_uri,
            "upload_status": self.upload_status,
            "user_gs_uri": self.user_gs_uri,
            "agent_gs_uri": self.agent_gs_uri,
            "gcs_error": self.gcs_error,
            "gcs_principal": self.gcs_principal,
            "gcs_bucket": self.gcs_bucket,
        }


def _local_result(
    recording_id: str,
    *,
    gcs_error: Optional[str] = None,
    principal: Optional[str] = None,
    bucket: Optional[str] = None,
    used_fallback: bool = True,
) -> StorageResult:
    local_path = processed_dir() / recording_id
    if used_fallback:
        logger.warning(
            "Using local storage fallback for recording %s | principal=%s bucket=%s error=%s",
            recording_id,
            principal or "unknown",
            bucket or "unknown",
            gcs_error or "unknown",
        )

    return StorageResult(
        user_audio_url=local_media_url(recording_id, "user_only.wav"),
        agent_audio_url=local_media_url(recording_id, "agent_only.wav"),
        diarization_url=local_media_url(recording_id, "diarization.json"),
        storage_type="local",
        storage_uri=str(local_path.resolve()),
        upload_status="failed",
        gcs_error=gcs_error,
        gcs_principal=principal,
        gcs_bucket=bucket,
    )


def upload_outputs_with_fallback(
    recording_id: str,
    user_path: Path,
    agent_path: Path,
    diarization_path: Path,
) -> StorageResult:
    """
    Attempt GCS upload; on permission or upload errors, fall back to local URLs.

    Processing must never fail because of GCS IAM errors.
    """
    gcs: GcsStorageClient | None = None
    try:
        gcs = GcsStorageClient.from_adc()
        principal = gcs.identity.principal_email
        bucket = gcs.identity.bucket_name
        source = gcs.identity.credential_source

        uploads = [
            (user_path, f"user_audio/{recording_id}/user_only.wav", "audio/wav"),
            (agent_path, f"agent_audio/{recording_id}/agent_only.wav", "audio/wav"),
            (diarization_path, f"reports/{recording_id}/diarization.json", "application/json"),
        ]

        gs_uris: list[str] = []
        playback_urls: list[str] = []

        for local_path, object_path, content_type in uploads:
            logger.info(
                "GCS upload attempt | principal=%s source=%s bucket=gs://%s path=%s local=%s",
                principal,
                source,
                bucket,
                object_path,
                local_path,
            )
            gs_uri = gcs.upload_object(local_path, object_path, content_type=content_type)
            gs_uris.append(gs_uri)
            filename = Path(object_path).name
            playback_urls.append(
                gcs.resolve_access_url(
                    object_path,
                    gs_uri,
                    local_fallback=local_media_url(recording_id, filename),
                )
            )

        logger.info(
            "GCS upload success | principal=%s bucket=gs://%s recording=%s objects=%d",
            principal,
            bucket,
            recording_id,
            len(gs_uris),
        )

        return StorageResult(
            user_audio_url=playback_urls[0],
            agent_audio_url=playback_urls[1],
            diarization_url=playback_urls[2],
            storage_type="gcs",
            storage_uri=gs_uris[0],
            upload_status="success",
            user_gs_uri=gs_uris[0],
            agent_gs_uri=gs_uris[1],
            gcs_principal=principal,
            gcs_bucket=bucket,
        )

    except GcsPermissionError as exc:
        logger.error(
            "GCS upload permission denied | principal=%s bucket=gs://%s path=%s error=%s fallback=local",
            exc.principal,
            exc.bucket,
            exc.object_path,
            exc,
        )
        return _local_result(
            recording_id,
            gcs_error=str(exc),
            principal=exc.principal,
            bucket=exc.bucket,
        )
    except Exception as exc:
        principal = gcs.identity.principal_email if gcs else "unknown"
        bucket = gcs.identity.bucket_name if gcs else "unknown"
        logger.error(
            "GCS upload failed | principal=%s bucket=%s recording=%s error=%s fallback=local",
            principal,
            bucket,
            recording_id,
            exc,
        )
        return _local_result(
            recording_id,
            gcs_error=str(exc),
            principal=principal,
            bucket=bucket,
        )
