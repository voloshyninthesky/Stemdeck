#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required but was not found in PATH"
  exit 1
fi

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
