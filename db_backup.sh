#!/bin/bash
# Daily database backup — uses SQLite's safe online-backup API so a live
# Django write can't corrupt the snapshot, then gzip + retain 30 days.
set -euo pipefail

DB="/home/projects/irrigation/internal_server/db.sqlite3"
BACKUP_DIR="/home/projects/irrigation/db_backups"
RETAIN_DAYS=30
PY="/home/projects/irrigation/.venv/bin/python"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/db_$TS.sqlite3"

mkdir -p "$BACKUP_DIR"

# Consistent snapshot via SQLite backup API (safe under concurrent writes)
"$PY" - "$DB" "$OUT" <<'PYEOF'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
con = sqlite3.connect(src)
bck = sqlite3.connect(dst)
con.backup(bck)
bck.close(); con.close()
PYEOF

gzip -f "$OUT"
echo "$(date '+%Y-%m-%d %H:%M:%S') backed up → ${OUT}.gz ($(du -h ${OUT}.gz | cut -f1))" >> "$BACKUP_DIR/backup.log"

# Prune backups older than RETAIN_DAYS
find "$BACKUP_DIR" -name "db_*.sqlite3.gz" -mtime +$RETAIN_DAYS -delete
pruned=$(find "$BACKUP_DIR" -name "db_*.sqlite3.gz" | wc -l)
echo "$(date '+%Y-%m-%d %H:%M:%S') retention: $pruned backups kept (>${RETAIN_DAYS}d pruned)" >> "$BACKUP_DIR/backup.log"
