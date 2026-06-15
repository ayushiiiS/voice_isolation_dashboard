#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-secrets/bm-gcs-credentials.json}"

# Parallel: 3 CPU worker processes (~3x throughput). Override with WORKERS=4 ./run_spinny_batch.sh
# Fastest single-stream: WORKERS=1 DEVICE=mps ./run_spinny_batch.sh
WORKERS="${WORKERS:-3}"
DEVICE="${DEVICE:-cpu}"

exec python isolate_spinny_local.py \
  --input output/public_urls_urls_only.csv \
  --output-dir spinny_aryan_isolated_audio \
  --resume \
  --workers "$WORKERS" \
  --device "$DEVICE"
