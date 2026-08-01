#!/bin/bash
# 定时邮件报表 (Scheduled Email Reports) daily dispatch cron.
#
# Runs the send_report_email management command, which reads every active
# EmailReportConfig and — if its frequency is due today (daily=every day,
# weekly=Monday, monthly=1st) — builds that report's Excel via
# core.excel_exports and emails it as an attachment over SMTP.
#
# Cron entry (runs 7:00 AM Asia/Shanghai — early enough for the morning shift
# to find yesterday's / last week's / last month's report in their inbox):
#   0 7 * * * /home/projects/irrigation/internal_server/email_cron.sh
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
