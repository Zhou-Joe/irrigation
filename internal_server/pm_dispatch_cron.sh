#!/bin/bash
# PM (Preventive Maintenance) daily dispatch cron.
#
# Runs two management commands in sequence:
#   1. mark_pm_overdue       — transitions dispatched GWOs past their
#                              scheduled_date to 'overdue'
#   2. generate_pm_workorders — generates WorkReports for due PM plans
#                              (backfills any missed cycles automatically)
#
# Cron entry (runs 6:00 AM Asia/Shanghai — before the 8 AM shift so field
# workers see today's tasks in the notification bell on login):
#   0 6 * * * /home/projects/irrigation/internal_server/pm_dispatch_cron.sh
#
# Logs to /var/log/pm_dispatch.log
set -euo pipefail

PROJECT="/home/projects/irrigation"
PY="$PROJECT/.venv/bin/python"
MANAGE="$PROJECT/internal_server/manage.py"
ENV_FILE="$PROJECT/.env.production"
LOG="/var/log/pm_dispatch.log"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "$(ts) === PM dispatch start ===" >> "$LOG"

# Load Django env (cron doesn't source profiles).
if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
fi

cd "$PROJECT/internal_server"

echo "$(ts) marking overdue..." >> "$LOG"
"$PY" "$MANAGE" mark_pm_overdue >> "$LOG" 2>&1 || true

echo "$(ts) generating work orders..." >> "$LOG"
"$PY" "$MANAGE" generate_pm_workorders >> "$LOG" 2>&1 || true

echo "$(ts) === PM dispatch done ===" >> "$LOG"
