#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python -m celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
