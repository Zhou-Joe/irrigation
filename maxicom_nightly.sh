#!/bin/bash
# Nightly Maxicom import: pull the latest .mdb backup from the Win7 SMB share,
# import new stations + runtime into Django (idempotent, CCU-safe), clean up.
# Cron: 0 20 * * *  (runs 8pm daily)
#
# Logs to /home/projects/irrigation/db_backups/maxicom_import.log
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────
SMB_HOST="192.168.137.1"
SMB_SHARE="maxicom backup"
SMB_USER="Administrator"
SMB_PASS="maxicom123"
ZIP_PASS="RLM6808"                       # Maxicom2.mdb DB password (also the zip password)
PROJECT="/home/projects/irrigation"
PY="$PROJECT/.venv/bin/python"
MANAGE="$PROJECT/internal_server/manage.py"
ENV_FILE="$PROJECT/.env.production"
LOG="$PROJECT/db_backups/maxicom_import.log"
TMP_DIR=$(mktemp -d /tmp/maxicom_import.XXXXXX)

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "$(ts) === Maxicom nightly import start ==="
echo "$(ts) tmp dir: $TMP_DIR"

# Load Django env (SECRET_KEY etc.) — cron doesn't source profiles.
if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
fi

trap 'rm -rf "$TMP_DIR"' EXIT

# ── 1. Find latest MC2Backup<MMDDYYYY>.zip on the share ───────────────────
# List share, parse filenames, pick the one with the max (YYYY, MM, DD) date.
LATEST_ZIP=$(smbclient "//$SMB_HOST/$SMB_SHARE" -U "${SMB_USER}%${SMB_PASS}" \
    --option='client min protocol=SMB2' -c 'ls' 2>/dev/null \
    | grep -oE 'MC2Backup[0-9]{8}\.zip' \
    | awk '{
        mm = substr($0, 10, 2); dd = substr($0, 12, 2); yyyy = substr($0, 14, 4);
        print yyyy mm dd, $0;
      }' \
    | sort | tail -1 | awk '{print $2}')

if [ -z "$LATEST_ZIP" ]; then
    echo "$(ts) ERROR: no MC2Backup*.zip found on share (share unreachable?)" >&2
    exit 1
fi
echo "$(ts) latest zip: $LATEST_ZIP"

# ── 2. Download + extract ──────────────────────────────────────────────────
cd "$TMP_DIR"
smbclient "//$SMB_HOST/$SMB_SHARE" -U "${SMB_USER}%${SMB_PASS}" \
    --option='client min protocol=SMB2' \
    -c "prompt; mget $LATEST_ZIP" 2>&1 | tail -1
if [ ! -f "$LATEST_ZIP" ]; then
    echo "$(ts) ERROR: download failed" >&2
    exit 1
fi
echo "$(ts) downloaded: $(du -h "$LATEST_ZIP" | cut -f1)"

unzip -P "$ZIP_PASS" -o "$LATEST_ZIP" Maxicom2.mdb >/dev/null
if [ ! -f Maxicom2.mdb ]; then
    echo "$(ts) ERROR: zip extract failed (wrong password?)" >&2
    exit 1
fi
echo "$(ts) extracted Maxicom2.mdb: $(du -h Maxicom2.mdb | cut -f1)"

# ── 3. Import (idempotent + CCU-safe) ──────────────────────────────────────
cd "$PROJECT/internal_server"
"$PY" "$MANAGE" import_maxicom_mdb_linux --mdb "$TMP_DIR/Maxicom2.mdb" 2>&1 | while read -r line; do
    echo "$(ts)   $line"
done

# ── 4. Cleanup (trap rm -rf handles it, but be explicit) ───────────────────
echo "$(ts) cleanup tmp dir"
# trap on EXIT removes $TMP_DIR

echo "$(ts) === done ==="
