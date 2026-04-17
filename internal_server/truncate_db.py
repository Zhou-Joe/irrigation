"""Truncate the Django SQLite database to keep only 2026 data, then VACUUM."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db.sqlite3')
CUTOFF_2026 = '20260101'  # Maxicom format: YYYYMMDDHHmmSS

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print(f"Database size before: {os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB")
print()

# Tables with Maxicom-format timestamps (YYYYMMDDHHmmSS)
maxicom_ts_tables = {
    'core_maxicomflowreading': 'timestamp',
    'core_maxicomsignallog': 'timestamp',
    'core_maxicomweatherlog': 'timestamp',
    'core_maxicometcheckbook': 'timestamp',
    'core_maxicomschedule': 'date_open',
    'core_maxicomcontroller': 'date_open',
    'core_maxicomstation': 'date_open',
}

for table, col in maxicom_ts_tables.items():
    cursor.execute(f"SELECT COUNT(*) FROM [{table}] WHERE [{col}] < '{CUTOFF_2026}'")
    old_count = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
    total = cursor.fetchone()[0]
    print(f"  {table}: {total} total, {old_count} pre-2026 rows to delete")
    if old_count > 0:
        cursor.execute(f"DELETE FROM [{table}] WHERE [{col}] < '{CUTOFF_2026}'")
        print(f"    -> Deleted {old_count} rows, {total - old_count} remaining")

conn.commit()

# VACUUM to reclaim disk space
print()
print("Running VACUUM to reclaim disk space...")
conn.execute("VACUUM")
conn.close()

print(f"\nDatabase size after:  {os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB")
print("Done!")