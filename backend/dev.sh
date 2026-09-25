#!/usr/bin/env bash
# Single idempotent developer entrypoint: private data dir -> migrations ->
# pinned model -> API + ingest worker. Safe to run repeatedly.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi

umask 077
exec "$PY" -m backend.app.dev "$@"
