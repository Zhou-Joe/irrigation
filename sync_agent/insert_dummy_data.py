"""Insert dummy Maxicom data with RECENT timestamps (last 5 days) so the sync
agent's "latest N days" window picks it up for a true end-to-end test.

Rows are tagged with a recognizable DUMMY marker in a text/description field so
they can be cleaned up later without touching real data. The timestamps use the
REAL current date so the sync window, server storage, and date-range display all
look natural.

Usage:  python insert_dummy_data.py [--clean]
    (default) insert  ~6 tables x a few dozen rows each
    --clean          delete every DUMMY-tagged row
"""
import sys
import random
from datetime import datetime, timedelta

import win32com.client

MDB = r"C:\Users\czhou7\PythonProjects\irrigation\Database\Maxicom2.mdb"
PWD = "RLM6808"
DUMMY_MARKER = "DUMMY"  # planted in any free text field for reliable cleanup

random.seed(42)


def open_db():
    eng = win32com.client.Dispatch("DAO.DBEngine.120")
    return eng.OpenDatabase(MDB, False, False, ";pwd=" + PWD)  # Exclusive=False, ReadWrite


def distinct(dbx, table, col):
    rs = dbx.OpenRecordset(f"SELECT DISTINCT [{col}] FROM [{table}]")
    out = []
    while not rs.EOF:
        v = rs.Fields(col).Value
        if v is not None:
            out.append(v)
        rs.MoveNext()
    rs.Close()
    return out


def recent_ts(day_offset, hour, minute=0, second=0):
    """A real 'now − day_offset' timestamp so the 7-day window picks it up
    naturally and the server stores a believable date."""
    d = datetime.now() - timedelta(days=day_offset)
    return d.strftime(f"%Y%m%d{hour:02d}{minute:02d}{second:02d}")


def add_row(dbx, table, fields):
    rs = dbx.OpenRecordset(table, 1)  # dbOpenDynaset = 1 (allows AddNew)
    rs.AddNew()
    for name, val in fields.items():
        rs.Fields(name).Value = val
    rs.Update()
    rs.Close()


def insert(dbx):
    sites = distinct(dbx, "SITE_CF", "IndexNumber")[:8]
    wstns = distinct(dbx, "WETHR_CF", "IndexNumber")[:6]
    ctrls = distinct(dbx, "CTROL_CF", "IndexNumber")[:10]
    fzones = distinct(dbx, "FLOZO_CF", "IndexNumber")[:10]
    stns = distinct(dbx, "STATN_CF", "IndexNumber")[:15]

    counts = {}

    # XA_WETHR — one reading per weather station, per day, for 5 days
    n = 0
    for ws in wstns:
        for d in range(5):
            add_row(dbx, "XA_WETHR", {
                "XactStamp": recent_ts(d, 4 + d % 3),
                "XactIndex": ws,
                "Temperature": round(random.uniform(15, 35), 2),
                "MaxTemp": round(random.uniform(25, 40), 2),
                "MinTemp": round(random.uniform(5, 20), 2),
                "SolarRadiation": round(random.uniform(0, 30), 2),
                "RainFall": round(random.uniform(0, 5), 2),
                "Humidity": round(random.uniform(30, 90), 2),
                "WindRun": round(random.uniform(0, 50), 2),
                "ET": round(random.uniform(0, 8), 2),
            })
            n += 1
    counts["XA_WETHR"] = n

    # XA_EVENT — a handful of events across sites/days.
    # EventFlag is validation-rule restricted to "A" / "W" / "E".
    n = 0
    events = [
        ("S", 1001, "W", "Excessive flow detected, SEEF started (DUMMY)"),
        ("S", 1002, "E", "Communication error with satellite (DUMMY)"),
        ("W", 2001, "A", "Weather data received (DUMMY)"),
        ("S", 1003, "W", "Low battery warning (DUMMY)"),
    ]
    for d in range(5):
        for src, num, flag, text in events:
            add_row(dbx, "XA_EVENT", {
                "XactStamp": recent_ts(d, 8 + d, 15),
                "XactIndex": random.choice(sites),
                "EventSource": src,
                "EventNumber": num + d,
                "EventFlag": flag,
                "EventTextQualifier": text,
            })
            n += 1
    counts["XA_EVENT"] = n

    # XA_ETCheckBook — one per site per day
    n = 0
    for s in sites:
        for d in range(5):
            add_row(dbx, "XA_ETCheckBook", {
                "XactStamp": recent_ts(d, 4),
                "SiteID": s,
                "SoilMoisture": round(random.uniform(20, 80), 2),
                "Rainfall": round(random.uniform(0, 3), 2),
                "ET": round(random.uniform(1, 8), 2),
                "Irrigation": round(random.uniform(0, 15), 2),
                "SoilMoistureHoldingCapacity": round(random.uniform(50, 100), 2),
                "SoilRefillPercentage": random.randint(40, 100),
            })
            n += 1
    counts["XA_ETCheckBook"] = n

    # XA_RuntimeProject — runtime minutes per station per day (use TimeStamps col)
    n = 0
    for st in stns:
        for d in range(5):
            # a few minutes of runtime each day
            for hr in range(6, 9):
                add_row(dbx, "XA_RuntimeProject", {
                    "TimeStamps": recent_ts(d, hr, random.randint(0, 59)),
                    "StationID": st,
                    "SiteID": random.choice(sites),
                    "RunTime": 1,
                })
                n += 1
    counts["XA_RuntimeProject"] = n

    # XA_LOG — signal logs per controller per day
    n = 0
    for c in ctrls:
        for d in range(5):
            for _ in range(3):
                add_row(dbx, "XA_LOG", {
                    "XactStamp": recent_ts(d, random.randint(6, 18), random.randint(0, 59), random.randint(0, 59)),
                    "XactIndex": c,
                    "ControllerChannel": random.randint(1, 48),
                    "SignalIndex": random.randint(1, 200),
                    "SignalTable": random.choice(["P", "S", "D", "C"]),
                    "SignalType": random.choice(["R", "S", "E"]),
                    "SignalValue": random.randint(0, 255),
                    "SignalMultiplier": random.choice([1.0, 0.1, 10.0]),
                })
                n += 1
    counts["XA_LOG"] = n

    # XA_FLOZO — flow readings per zone per day
    n = 0
    for fz in fzones:
        for d in range(5):
            for _ in range(2):
                add_row(dbx, "XA_FLOZO", {
                    "XactStamp": recent_ts(d, random.randint(0, 23), random.randint(0, 59)),
                    "XactIndex": fz,
                    "FlowZoneValue": random.randint(50, 500),
                    "FlowZoneMultiplier": random.choice([1, 10, 100]),
                    "SiteID": random.choice(sites),
                })
                n += 1
    counts["XA_FLOZO"] = n

    return counts


def clean(dbx):
    """Remove all rows newer than the real data's max date (2026-04-04).

    The live MDB's real data ends 2026-04-03, so every row after that is dummy
    data this script inserted. Also drop any DUMMY-tagged event text for safety.
    """
    tables_ts = [
        ("XA_WETHR", "XactStamp"), ("XA_EVENT", "XactStamp"),
        ("XA_ETCheckBook", "XactStamp"), ("XA_RuntimeProject", "TimeStamps"),
        ("XA_LOG", "XactStamp"), ("XA_FLOZO", "XactStamp"),
    ]
    cutoff = "20260404000000"
    deleted = {}
    for table, col in tables_ts:
        rs = dbx.OpenRecordset(f"SELECT Count(*) AS c FROM [{table}] WHERE [{col}] > '{cutoff}'")
        c = rs.Fields("c").Value
        rs.Close()
        if c:
            dbx.Execute(f"DELETE FROM [{table}] WHERE [{col}] > '{cutoff}'")
        deleted[table] = c
    # Also clean any stray DUMMY-tagged events (in case timestamps overlapped)
    rs = dbx.OpenRecordset("SELECT Count(*) AS c FROM XA_EVENT WHERE EventTextQualifier LIKE '%DUMMY%'")
    c2 = rs.Fields("c").Value
    rs.Close()
    if c2:
        dbx.Execute("DELETE FROM XA_EVENT WHERE EventTextQualifier LIKE '%DUMMY%'")
        deleted["XA_EVENT"] = deleted.get("XA_EVENT", 0) + c2
    return deleted


def main():
    dbx = open_db()
    try:
        if "--clean" in sys.argv:
            print("Cleaning dummy data (timestamps starting with", DUMMY_MARKER + ")...")
            deleted = clean(dbx)
            for t, c in deleted.items():
                print(f"  {t}: deleted {c} rows")
            print("Done.")
        else:
            print("Inserting dummy data with recent timestamps (last 5 days)...")
            counts = insert(dbx)
            print("Inserted:")
            total = 0
            for t, c in counts.items():
                print(f"  {t}: {c} rows")
                total += c
            print(f"Total: {total} rows")
            print()
            print("These appear in a 'latest 7 days' sync window (real current dates).")
            print("To remove later:  python insert_dummy_data.py --clean")
    finally:
        dbx.Close()


if __name__ == "__main__":
    main()
