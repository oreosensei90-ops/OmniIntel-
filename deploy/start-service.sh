#!/usr/bin/env bash
set -euo pipefail

: "${OMNIINTEL_DATABASE:=/var/lib/omniintel/omniintel.db}"
export OMNIINTEL_DATABASE
mkdir -p "$(dirname "$OMNIINTEL_DATABASE")" "${OMNIINTEL_ASSET_DIR:-/var/lib/omniintel/assets}" "${OMNIINTEL_UPLOAD_DIR:-/var/lib/omniintel/uploads}"

omniintel-worker --database "$OMNIINTEL_DATABASE" &
worker_pid=$!
uvicorn omniintel.api:app --host "${OMNIINTEL_API_HOST:-0.0.0.0}" --port "${PORT:-8000}" &
api_pid=$!

shutdown() {
  kill "$worker_pid" "$api_pid" 2>/dev/null || true
  wait "$worker_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
}
trap shutdown TERM INT

set +e
wait -n "$worker_pid" "$api_pid"
status=$?
set -e
shutdown
exit "$status"
