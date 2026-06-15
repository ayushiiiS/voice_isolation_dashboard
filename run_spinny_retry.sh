#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-secrets/bm-gcs-credentials.json}"

# Unsigned URLs from public_urls_urls_only.csv (GCS API download, not expired signed URLs)
exec python3 isolate_spinny_local.py \
  --input output/public_urls_retry_unsigned.csv \
  --output-dir spinny_aryan_isolated_audio \
  --resume \
  --workers "${WORKERS:-3}" \
  --device "${DEVICE:-cpu}"
