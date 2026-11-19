#!/usr/bin/env bash
set -euo pipefail

: "${OMNIINTEL_DATABASE:=/var/lib/omniintel/omniintel.db}"
export OMNIINTEL_DATABASE
mkdir -p "$(dirname "$OMNIINTEL_DATABASE")" "${OMNIINTEL_ASSET_DIR:-/var/lib/omniintel/assets}" "${OMNIINTEL_UPLOAD_DIR:-/var/lib/omniintel/uploads}"

uvicorn omniintel.api:app --host "${OMNIINTEL_API_HOST:-0.0.0.0}" --port "${PORT:-8000}" &
api_pid=$!

ready=0
for _ in $(seq 1 60); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT:-8000}/health', timeout=2).read()" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  kill "$api_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
  echo "OmniIntel API failed to become healthy; worker was not started." >&2
  exit 1
fi

omniintel-worker --database "$OMNIINTEL_DATABASE" &
worker_pid=$!

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
