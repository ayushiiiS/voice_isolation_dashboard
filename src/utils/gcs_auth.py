"""Google Cloud credential loading for user account authentication."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

import google.auth
import google.auth.exceptions
import google.auth.transport.requests
from google.auth.credentials import Credentials
from google.oauth2.credentials import Credentials as UserCredentials

logger = logging.getLogger(__name__)

GCS_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/devstorage.read_write",
)

# adc | gcloud_cli — see GCS_CREDENTIALS_SOURCE in .env
DEFAULT_CREDENTIALS_SOURCE = "gcloud_cli"


@dataclass(frozen=True)
class GcpIdentity:
    """Resolved GCP authentication identity."""

    credential_source: str
    principal_email: str
    project_id: Optional[str]
    bucket_name: str


class GcloudCliCredentials(UserCredentials):
    """OAuth credentials refreshed from the active `gcloud auth login` session."""

    def refresh(self, request) -> None:  # noqa: ANN001
        self.token = _gcloud_print_access_token()


class GcsPermissionError(PermissionError):
    """Raised when the active principal lacks required GCS permissions."""

    def __init__(
        self,
        *,
        principal: str,
        bucket: str,
        object_path: str,
        permission: str,
        credential_source: str,
        original: Exception,
    ) -> None:
        self.principal = principal
        self.bucket = bucket
        self.object_path = object_path
        self.permission = permission
        self.credential_source = credential_source
        message = (
            f"GCS permission denied for principal '{principal}' "
            f"(credential source: {credential_source}). "
            f"Missing permission '{permission}' on "
            f"gs://{bucket}/{object_path}. Original error: {original}"
        )
        super().__init__(message)


def get_credentials_source() -> str:
    return os.getenv("GCS_CREDENTIALS_SOURCE", DEFAULT_CREDENTIALS_SOURCE).strip().lower()


def configure_adc_credentials() -> None:
    """Remove service-account key env var so google-auth does not load bm-gcs JSON."""
    use_adc = os.getenv("GCS_USE_ADC", "true").lower() == "true"
    if not use_adc:
        return

    removed = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    if removed:
        logger.info(
            "Removed GOOGLE_APPLICATION_CREDENTIALS=%s",
            removed,
        )


def _run_gcloud(args: list[str]) -> str:
    try:
        return subprocess.check_output(["gcloud", *args], text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"gcloud {' '.join(args)} failed: {exc.output}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gcloud CLI not found. Install Google Cloud SDK or set GCS_CREDENTIALS_SOURCE=adc"
        ) from exc


def _gcloud_active_account() -> str:
    account = _run_gcloud(["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"])
    if not account:
        raise RuntimeError(
            "No active gcloud account. Run: gcloud auth login "
            "(sign in as ayushi.s.ext@bluemachines.ai)"
        )
    return account.splitlines()[0].strip()


def _gcloud_print_access_token() -> str:
    return _run_gcloud(["auth", "print-access-token"])


def _gcloud_project() -> Optional[str]:
    project = _run_gcloud(["config", "get-value", "project"])
    if not project or project == "(unset)":
        return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    return project


def load_gcloud_cli_credentials() -> tuple[Credentials, Optional[str], str]:
    """Load credentials from active `gcloud auth login` session."""
    configure_adc_credentials()
    account = _gcloud_active_account()
    token = _gcloud_print_access_token()
    project = _gcloud_project()

    logger.info(
        "GCS credentials loaded from gcloud CLI user session (account=%s)",
        account,
    )
    credentials = GcloudCliCredentials(token=token)
    return credentials, project, account


def load_adc_credentials() -> tuple[Credentials, Optional[str], Optional[str]]:
    """Load Application Default Credentials from ~/.config/gcloud/application_default_credentials.json."""
    configure_adc_credentials()
    try:
        credentials, project = google.auth.default(scopes=list(GCS_SCOPES))
    except google.auth.exceptions.DefaultCredentialsError as exc:
        raise RuntimeError(
            "Application Default Credentials not configured. "
            "Either run: gcloud auth application-default login "
            "(sign in as ayushi.s.ext@bluemachines.ai and consent to cloud-platform scope), "
            "or set GCS_CREDENTIALS_SOURCE=gcloud_cli to use your existing gcloud auth login."
        ) from exc
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    return credentials, project, None


def load_gcp_credentials() -> tuple[Credentials, Optional[str], str, str]:
    """
    Load GCP credentials based on GCS_CREDENTIALS_SOURCE.

    Returns (credentials, project_id, principal_email, credential_source).
    """
    source = get_credentials_source()

    if source == "gcloud_cli":
        credentials, project, account = load_gcloud_cli_credentials()
        return credentials, project, account, "gcloud_cli_user"

    if source == "adc":
        credentials, project, _ = load_adc_credentials()
        principal, resolved_source = resolve_principal_email(credentials, "user_adc")
        return credentials, project, principal, resolved_source

    raise RuntimeError(
        f"Invalid GCS_CREDENTIALS_SOURCE={source!r}. Use 'adc' or 'gcloud_cli'."
    )


def resolve_principal_email(
    credentials: Credentials, default_source: str = "user_adc"
) -> tuple[str, str]:
    """Return (principal_email, credential_source) from credential object."""
    sa_email = getattr(credentials, "service_account_email", None)
    if sa_email:
        source = (
            "service_account_key"
            if os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            else "service_account_adc"
        )
        return sa_email, source

    signer_email = getattr(credentials, "signer_email", None)
    if signer_email:
        return signer_email, "service_account_adc"

    token = getattr(credentials, "token", None)
    if not token:
        raise RuntimeError("Could not determine authenticated GCP principal: token missing.")

    import requests

    response = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    email = response.json().get("email")
    if not email:
        raise RuntimeError("Could not determine GCP user email from token.")
    return email, default_source


def resolve_gcp_identity() -> GcpIdentity:
    """Resolve the active GCP identity."""
    credentials, project, principal, source = load_gcp_credentials()
    bucket = os.getenv("BUCKET_NAME", "cadence-audio")

    return GcpIdentity(
        credential_source=source,
        principal_email=principal,
        project_id=project,
        bucket_name=bucket,
    )


def log_gcp_identity_at_startup() -> GcpIdentity:
    """Log GCP project, principal, bucket, and credential source at startup."""
    source_mode = get_credentials_source()
    logger.info("GCS_CREDENTIALS_SOURCE=%s", source_mode)

    identity = resolve_gcp_identity()
    logger.info("GCP credential source: %s", identity.credential_source)
    logger.info("GCP authenticated principal: %s", identity.principal_email)
    logger.info("GCP project: %s", identity.project_id or "(not set)")
    logger.info("GCS upload bucket: gs://%s", identity.bucket_name)
    return identity


def credentials_support_signing(credential_source: str) -> bool:
    """
    Return True when credentials can produce GCS V4 signed URLs.

    User OAuth tokens from ``gcloud auth login`` or user ADC hold access tokens
    only — they have no private key for ``sign_bytes()``.
    """
    return credential_source not in ("gcloud_cli_user", "user_adc")


def permission_for_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "403" in message or "forbidden" in message or "denied" in message:
        return "storage.objects.create (Storage Object Creator) or storage.objects.delete"
    if "404" in message or "not found" in message:
        return "storage.buckets.get (bucket must exist and be accessible)"
    return "storage.objects.create"
