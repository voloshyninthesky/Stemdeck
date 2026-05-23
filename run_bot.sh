#!/usr/bin/env bash
# Run the Telegram bot locally (outside Docker).
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-.}:$(dirname "$0")"
exec python -m app.telegram_bot
