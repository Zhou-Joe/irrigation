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

# ── Ensure Maxicom runtime data is as fresh as the share allows ────────────
# Reports cover windows ending yesterday (daily/weekly/monthly); the newest
# data lives in the MC2Backup zip the Win7 box writes daily ~16:01. Fixed
# import crons (08:00 / 16:30) usually cover it, but a missed run or a late
# zip would make an email stale. Compare the newest zip on the share with the
# marker maxicom_nightly.sh writes; import first when a newer one exists.
# Never blocks dispatch: any failure here just sends with current data.
if [ -f "$ENV_FILE" ]; then
    SMB_LATEST=$(smbclient "//$MAXICOM_SMB_HOST/$MAXICOM_SMB_SHARE" \
        -U "${MAXICOM_SMB_USER}%${MAXICOM_SMB_PASS}" \
        --option='client min protocol=SMB2' -c 'ls' 2>/dev/null \
        | grep -oE 'MC2Backup[0-9]{8}\.zip' \
        | awk '{
            mm = substr($0, 10, 2); dd = substr($0, 12, 2); yyyy = substr($0, 14, 4);
            print yyyy mm dd, $0;
          }' \
        | sort | tail -1 | awk '{print $2}') || true
    SMB_LAST_IMPORT=$(cat "$PROJECT/db_backups/.maxicom_last_zip" 2>/dev/null) || true
    if [ -n "$SMB_LATEST" ] && [ "$SMB_LATEST" != "$SMB_LAST_IMPORT" ]; then
        echo "$(ts) newer Maxicom zip on share ($SMB_LATEST, last imported: ${SMB_LAST_IMPORT:-none}) — importing before dispatch" >> "$LOG"
        bash "$PROJECT/maxicom_nightly.sh" >> "$PROJECT/db_backups/maxicom_import.log" 2>&1 || \
            echo "$(ts) WARNING: pre-dispatch import failed — sending with current data" >> "$LOG"
    fi
fi

echo "$(ts) sending due email reports..." >> "$LOG"
"$PY" "$MANAGE" send_report_email >> "$LOG" 2>&1 || true

echo "$(ts) === email report dispatch done ===" >> "$LOG"
