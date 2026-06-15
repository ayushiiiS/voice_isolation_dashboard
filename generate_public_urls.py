#!/usr/bin/env python3
"""Generate publicly accessible URLs from private URLs and credentials."""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pandas as pd

from src.utils.gcs_download import parse_gcs_location

logger = logging.getLogger(__name__)

URL_COLUMN_ALIASES = ("url", "recordingurl", "recording_url", "link", "source_url")
KEY_COLUMN_ALIASES = ("key", "api_key", "token", "access_token", "apikey", "accesstoken")


def setup_logging(verbose: bool, log_file: Path | None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def normalize_column_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def resolve_column(
    df: pd.DataFrame,
    explicit_name: str | None,
    aliases: tuple[str, ...],
    label: str,
) -> str | None:
    """Return the actual DataFrame column name for URL or key."""
    columns_by_normalized = {normalize_column_name(col): col for col in df.columns}

    if explicit_name:
        normalized = normalize_column_name(explicit_name)
        if normalized in columns_by_normalized:
            return columns_by_normalized[normalized]
        if explicit_name in df.columns:
            return explicit_name
        available = ", ".join(df.columns)
        raise ValueError(f"{label} column '{explicit_name}' not found. Available columns: {available}")

    for alias in aliases:
        if alias in columns_by_normalized:
            return columns_by_normalized[alias]

    return None


def is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def build_public_url(url: str, key: str, param_name: str) -> str:
    """Append or replace a query parameter on the URL."""
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL (missing scheme or host): {url}")

    query = parse_qs(parsed.query, keep_blank_values=True)
    query[param_name] = [key.strip()]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


class GcsUrlSigner:
    """Sign GCS URLs using a service-account credentials file."""

    def __init__(self, credentials_path: Path, expiration_hours: int) -> None:
        try:
            from google.cloud import storage
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-storage is required for GCS signed URLs. "
                "Install with: pip install google-cloud-storage"
            ) from exc

        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path)
        )
        self._client = storage.Client(
            credentials=credentials,
            project=credentials.project_id,
        )
        self._expiration = timedelta(hours=expiration_hours)

    def sign(self, url: str) -> str:
        location = parse_gcs_location(url)
        if location is None:
            raise ValueError(f"Not a GCS URL: {url}")

        bucket_name, object_path = location
        blob = self._client.bucket(bucket_name).blob(object_path)
        return blob.generate_signed_url(
            version="v4",
            expiration=self._expiration,
            method="GET",
        )


def process_query_param_rows(
    df: pd.DataFrame,
    url_column: str,
    key_column: str | None,
    default_key: str | None,
    param_name: str,
    dedupe: bool,
) -> pd.DataFrame:
    """Build output rows by appending a key/token as a query parameter."""
    if key_column is None:
        if default_key is None:
            raise ValueError(
                "No key column found in the CSV. Provide --key-column or --default-key."
            )
        logger.info("Using --default-key for all rows (no key column in input).")
        working = df.copy()
        working["_resolved_key"] = default_key
        key_source = "_resolved_key"
    else:
        working = df.copy()
        key_source = key_column

    total_rows = len(working)
    logger.info("Loaded %d row(s) from input.", total_rows)

    if dedupe:
        subset = [url_column, key_source]
        before = len(working)
        working = working.drop_duplicates(subset=subset, keep="first")
        removed = before - len(working)
        if removed:
            logger.warning("Removed %d duplicate row(s) based on (%s).", removed, ", ".join(subset))

    output_rows: list[dict[str, str]] = []
    stats = {"success": 0, "missing_url": 0, "missing_key": 0, "invalid_url": 0}

    for index, row in working.iterrows():
        raw_url = row.get(url_column)
        raw_key = row.get(key_source) if key_source in row else default_key

        url = "" if is_missing(raw_url) else str(raw_url).strip()
        key = "" if is_missing(raw_key) else str(raw_key).strip()

        public_url = ""

        if not url:
            stats["missing_url"] += 1
            logger.warning("Row %s: missing URL — skipping public URL generation.", index)
        elif not key:
            stats["missing_key"] += 1
            logger.warning("Row %s: missing key/token — skipping public URL generation.", index)
        else:
            try:
                public_url = build_public_url(url, key, param_name)
                stats["success"] += 1
            except ValueError as exc:
                stats["invalid_url"] += 1
                logger.error("Row %s: %s", index, exc)

        output_rows.append({"url": url, "key": key, "public_url": public_url})

    result = pd.DataFrame(output_rows)
    logger.info(
        "Finished: %d succeeded, %d missing URL, %d missing key, %d invalid URL.",
        stats["success"],
        stats["missing_url"],
        stats["missing_key"],
        stats["invalid_url"],
    )
    return result


def process_gcs_signed_rows(
    df: pd.DataFrame,
    url_column: str,
    credentials_path: Path,
    expiration_hours: int,
    dedupe: bool,
) -> pd.DataFrame:
    """Build output rows with GCS V4 signed URLs."""
    signer = GcsUrlSigner(credentials_path, expiration_hours)
    working = df.copy()
    total_rows = len(working)
    logger.info("Loaded %d row(s) from input.", total_rows)
    logger.info(
        "Signing GCS URLs with credentials file '%s' (expires in %d hour(s)).",
        credentials_path,
        expiration_hours,
    )

    if dedupe:
        before = len(working)
        working = working.drop_duplicates(subset=[url_column], keep="first")
        removed = before - len(working)
        if removed:
            logger.warning("Removed %d duplicate row(s) based on (%s).", removed, url_column)

    output_rows: list[dict[str, str]] = []
    stats = {"success": 0, "missing_url": 0, "invalid_url": 0, "sign_failed": 0}
    key_label = f"gcs-signed:{credentials_path.name}"

    for index, row in working.iterrows():
        raw_url = row.get(url_column)
        url = "" if is_missing(raw_url) else str(raw_url).strip()
        public_url = ""

        if not url:
            stats["missing_url"] += 1
            logger.warning("Row %s: missing URL — skipping signed URL generation.", index)
        else:
            try:
                public_url = signer.sign(url)
                stats["success"] += 1
            except ValueError as exc:
                stats["invalid_url"] += 1
                logger.error("Row %s: %s", index, exc)
            except Exception as exc:
                stats["sign_failed"] += 1
                logger.error("Row %s: failed to sign URL: %s", index, exc)

        output_rows.append({"url": url, "key": key_label, "public_url": public_url})

    result = pd.DataFrame(output_rows)
    logger.info(
        "Finished: %d succeeded, %d missing URL, %d invalid URL, %d sign failures.",
        stats["success"],
        stats["missing_url"],
        stats["invalid_url"],
        stats["sign_failed"],
    )
    return result


def validate_credentials_file(path: Path) -> None:
    """Ensure the credentials file is valid JSON before processing rows."""
    import json

    try:
        with path.open(encoding="utf-8") as handle:
            json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in credentials file '{path}': {exc}. "
            "The file must be a complete service-account JSON object starting with '{'."
        ) from exc


def resolve_gcs_credentials(explicit_path: Path | None) -> Path:
    """Resolve a GCS service-account JSON path from CLI or environment."""
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise ValueError(f"GCS credentials file not found: {explicit_path}")
        validate_credentials_file(explicit_path)
        return explicit_path

    env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path:
        path = Path(env_path)
        if not path.is_file():
            raise ValueError(
                f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {path}"
            )
        validate_credentials_file(path)
        return path

    raise ValueError(
        "GCS signing requires --gcs-credentials or GOOGLE_APPLICATION_CREDENTIALS."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate public URLs from private URLs. "
            "Use query-parameter mode for API keys, or --gcs-credentials for GCS signed URLs."
        ),
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to input CSV file containing URLs and keys/tokens.",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Path to output CSV file (url, key, public_url).",
    )
    parser.add_argument(
        "--url-column",
        default=None,
        help="Column name for the original URL (auto-detected if omitted).",
    )
    parser.add_argument(
        "--key-column",
        default=None,
        help="Column name for the API key/token (auto-detected if omitted).",
    )
    parser.add_argument(
        "--default-key",
        default=None,
        help="Use this key for every row when the CSV has no key column.",
    )
    parser.add_argument(
        "--param-name",
        default="api_key",
        help="Query parameter name for the key (default: api_key).",
    )
    parser.add_argument(
        "--gcs-credentials",
        type=Path,
        default=None,
        help=(
            "Path to a GCS service-account JSON file. "
            "When set, generates V4 signed URLs instead of appending a query parameter. "
            "Can also use GOOGLE_APPLICATION_CREDENTIALS."
        ),
    )
    parser.add_argument(
        "--gcs-expiration-hours",
        type=int,
        default=24,
        help="Signed URL lifetime in hours when using --gcs-credentials (default: 24).",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Keep duplicate (url, key) rows instead of removing them.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional path to write log output.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose, args.log_file)

    input_path: Path = args.input
    output_path: Path = args.output

    if not input_path.is_file():
        logger.error("Input file not found: %s", input_path)
        return 1

    try:
        df = pd.read_csv(input_path, dtype=str, keep_default_na=True)
    except Exception as exc:
        logger.error("Failed to read CSV '%s': %s", input_path, exc)
        return 1

    if df.empty:
        logger.error("Input CSV is empty: %s", input_path)
        return 1

    try:
        url_column = resolve_column(df, args.url_column, URL_COLUMN_ALIASES, "URL")
        if url_column is None:
            available = ", ".join(df.columns)
            raise ValueError(
                f"Could not detect a URL column. Use --url-column. Available columns: {available}"
            )

        logger.info("Using URL column '%s'.", url_column)

        if args.gcs_credentials is not None or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            credentials_path = resolve_gcs_credentials(args.gcs_credentials)
            if args.gcs_expiration_hours <= 0:
                raise ValueError("--gcs-expiration-hours must be greater than 0.")
            result = process_gcs_signed_rows(
                df=df,
                url_column=url_column,
                credentials_path=credentials_path,
                expiration_hours=args.gcs_expiration_hours,
                dedupe=not args.no_dedupe,
            )
        else:
            key_column = resolve_column(df, args.key_column, KEY_COLUMN_ALIASES, "Key")
            if key_column:
                logger.info("Using key column '%s'.", key_column)
            result = process_query_param_rows(
                df=df,
                url_column=url_column,
                key_column=key_column,
                default_key=args.default_key,
                param_name=args.param_name,
                dedupe=not args.no_dedupe,
            )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL)
        if args.gcs_credentials is not None or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            urls_only_path = output_path.with_name(
                f"{output_path.stem}_urls_only{output_path.suffix}"
            )
            result[["public_url"]].rename(columns={"public_url": "recording_url"}).to_csv(
                urls_only_path,
                index=False,
                quoting=csv.QUOTE_ALL,
            )
            logger.info("Wrote %d signed URL(s) to %s", len(result), urls_only_path)
    except Exception as exc:
        logger.error("Failed to write output CSV '%s': %s", output_path, exc)
        return 1

    logger.info("Wrote %d row(s) to %s", len(result), output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
