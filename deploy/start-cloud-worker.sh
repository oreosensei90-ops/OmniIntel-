#!/bin/sh
set -eu

: "${OMNIINTEL_WORKER_API:?Set OMNIINTEL_WORKER_API to the deployed Cloudflare Worker origin}"
: "${OMNIINTEL_WORKER_TOKEN:?Set OMNIINTEL_WORKER_TOKEN to the Worker bridge token}"

export OMNIINTEL_DATABASE="${OMNIINTEL_DATABASE:-/var/lib/omniintel/worker.sqlite3}"
export OMNIINTEL_UPLOAD_DIR="${OMNIINTEL_UPLOAD_DIR:-/var/lib/omniintel/uploads}"
export OMNIINTEL_ASSET_DIR="${OMNIINTEL_ASSET_DIR:-/var/lib/omniintel/assets}"

mkdir -p "$(dirname "$OMNIINTEL_DATABASE")" "$OMNIINTEL_UPLOAD_DIR" "$OMNIINTEL_ASSET_DIR"

exec omniintel-cloud-worker \
  --api "$OMNIINTEL_WORKER_API" \
  --database "$OMNIINTEL_DATABASE" \
  --upload-dir "$OMNIINTEL_UPLOAD_DIR" \
  --asset-dir "$OMNIINTEL_ASSET_DIR" \
  --poll-seconds "${OMNIINTEL_POLL_SECONDS:-5}"
