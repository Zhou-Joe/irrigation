#!/usr/bin/env bash
#
# deploy.sh — production deploy helper for the internal server.
#
# Deployment model (per project convention):
#   1. git pull the latest main
#   2. pip install — install/upgrade Python deps from requirements.txt
#   3. collectstatic — rebuilds staticfiles/ so WhiteNoise serves fresh assets
#   4. migrate — apply any new DB migrations
#   5. restart the app process (see note below)
#
# Why collectstatic matters:
#   Production serves static files via WhiteNoise from STATIC_ROOT (staticfiles/).
#   That directory is a BUILD ARTIFACT — it is gitignored and intentionally NOT
#   committed. The single source of truth is internal_server/static/. After every
#   `git pull`, collectstatic must run or WhiteNoise will serve stale/missing CSS/JS.
#
# Restart note:
#   This script intentionally does NOT restart the app process, because the
#   process manager (systemd / supervisor / gunicorn / runserver screen, etc.)
#   varies by host. Restart it the same way you normally do after this script
#   finishes, e.g.:
#       sudo systemctl restart horticulture
#       # or:  pkill -f runserver && nohup python manage.py runserver ... &
#
# Usage:
#   ./deploy.sh              # pull + collectstatic + migrate
#   ./deploy.sh --no-pull    # skip the git pull (you already pulled)
#   ./deploy.sh --no-migrate # skip migrations

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DO_PULL=1
DO_MIGRATE=1
for arg in "$@"; do
    case "$arg" in
        --no-pull)    DO_PULL=0 ;;
        --no-migrate) DO_MIGRATE=0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

# Activate the project venv if present (one level up, matching development.md).
if [ -f "../.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source ../.venv/bin/activate
fi

echo "==> [1/4] git pull"
if [ "$DO_PULL" -eq 1 ]; then
    git -C "$SCRIPT_DIR/.." pull --ff-only
else
    echo "    (skipped)"
fi

echo "==> [2/4] install Python dependencies"
# requirements.txt is the source of truth for runtime deps. New code can add
# packages (e.g. langgraph-checkpoint-sqlite for the AI agent); install/upgrade
# them so the app imports cleanly after restart. Runs inside the venv above.
python -m pip install -r requirements.txt

echo "==> [3/4] collectstatic"
python manage.py collectstatic --noinput --clear

if [ "$DO_MIGRATE" -eq 1 ]; then
    echo "==> [4/4] migrate"
    python manage.py migrate --noinput
else
    echo "==> [4/4] migrate (skipped)"
fi

echo ""
echo "Done. Now restart the app process the way you normally do."
