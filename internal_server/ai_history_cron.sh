#!/bin/bash
set -euo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$PROJECT/.env.production" ]; then
    set -a
    . "$PROJECT/.env.production"
    set +a
fi
exec "$PROJECT/.venv/bin/python" "$PROJECT/internal_server/manage.py" prune_ai_history "$@"
