#!/bin/bash

# Start the FastAPI server and the durable Meta messaging worker together.
# Binds to 0.0.0.0 and uses $PORT provided by the host (Railway, Render, etc.)

set -euo pipefail

# Both processes must run from server/ to resolve application modules.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

PORT=${PORT:-8000}
WORKERS=${WEB_CONCURRENCY:-1}

service_pids=()

cleanup() {
    trap '' TERM INT
    if [ "${#service_pids[@]}" -gt 0 ]; then
        kill -TERM "${service_pids[@]}" 2>/dev/null || true
        wait "${service_pids[@]}" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

echo "Starting Meta messaging worker..."
python -m workers.meta_messages &
service_pids+=("$!")

echo "Starting FastAPI server on port $PORT with $WORKERS workers..."
uvicorn main:app --host 0.0.0.0 --port "$PORT" --workers "$WORKERS" &
service_pids+=("$!")

# Stop both if either exits, so the host can restart the complete service.
if wait -n "${service_pids[@]}"; then
    exit_status=1
else
    exit_status=$?
fi
echo "A service exited; stopping the web server and Meta worker."
exit "$exit_status"
