#!/bin/bash
# 定时邮件报表 (Scheduled Email Reports) hourly dispatch cron.
#
# Runs the send_report_email management command, which reads every active
# EmailReportConfig and — if its frequency is due now (daily=every day,
# weekly=configured weekday, monthly=configured day-of-month) AND the current
# hour matches the config's send_hour (null/blank → 7) — builds that report's
# Excel via core.excel_exports and emails it as an attachment over SMTP.
#
# Cron entry (runs at the TOP of EVERY HOUR — required so the per-config
# send_hour actually takes effect; a config with send_hour=8 fires only during
# the 08:00 run):
#   0 * * * * /home/projects/irrigation/internal_server/email_cron.sh
#
# Logs to /var/log/email_dispatch.log
set -euo pipefail

PROJECT="/home/projects/irrigation"
PY="$PROJECT/.venv/bin/python"
MANAGE="$PROJECT/internal_server/manage.py"
ENV_FILE="$PROJECT/.env.production"
LOG="/var/log/email_dispatch.log"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "$(ts) === email report dispatch start ===" >> "$LOG"

# Load Django env (cron doesn't source profiles). EMAIL_HOST / EMAIL_HOST_USER /
# EMAIL_HOST_PASSWORD etc. must be set here for SMTP to work.
if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
fi

cd "$PROJECT/internal_server"

echo "$(ts) sending due email reports..." >> "$LOG"
"$PY" "$MANAGE" send_report_email >> "$LOG" 2>&1 || true

echo "$(ts) === email report dispatch done ===" >> "$LOG"
