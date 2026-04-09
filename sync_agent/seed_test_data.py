"""
MDB Test Data Generator
Inserts random data with current timestamps into Maxicom2.mdb for sync testing.

Usage:
    python seed_test_data.py              # Insert one batch of random data
    python seed_test_data.py --loop       # Insert data every 30 seconds
    python seed_test_data.py --loop 60    # Insert data every 60 seconds

Requires: pywin32 (pip install pywin32)
"""

import sys
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────
MDB_PASSWORD = "RLM6808"

SEARCH_PATHS = [
    r"C:\Maxicom2\Database\Maxicom2.mdb",
    r"D:\Maxicom2\Database\Maxicom2.mdb",
    r"C:\Program Files (x86)\Rain Bird\Maxicom2\Database\Maxicom2.mdb",
    r"C:\Program Files\Rain Bird\Maxicom2\Database\Maxicom2.mdb",
]

_project_root = Path(__file__).resolve().parent.parent
SEARCH_PATHS.extend([
    str(_project_root / "Database" / "Maxicom2.mdb"),
    str(_project_root / "test_data" / "Maxicom2.mdb"),
    str(_project_root / "Maxicom2.mdb"),
])


def find_mdb():
    for p in SEARCH_PATHS:
        if os.path.exists(p):
            return p
    return None


def get_timestamp():
    return datetime.now().strftime("%Y%m%d%H%M%S")


def open_db(mdb_path):
    import win32com.client
    db_engine = win32com.client.Dispatch("DAO.DBEngine.120")
    db = db_engine.OpenDatabase(mdb_path, False, False, ";pwd=" + MDB_PASSWORD)
    return db


def _get_indices(db, table, field="IndexNumber"):
    rs = db.OpenRecordset(f"SELECT [{field}] FROM [{table}]")
    indices = []
    try:
        while not rs.EOF:
            indices.append(rs.Fields(field).Value)
            rs.MoveNext()
    finally:
        rs.Close()
    return indices


def insert_weather_data(db):
    stations = _get_indices(db, "WETHR_CF")
    if not stations:
        print("  No weather stations found - skipping")
        return 0
    count = 0
    ts = get_timestamp()
    for idx in random.sample(stations, min(3, len(stations))):
        rs = db.OpenRecordset("XA_WETHR")
        try:
            rs.AddNew()
            rs.Fields("XactStamp").Value = ts
            rs.Fields("XactIndex").Value = idx
            rs.Fields("Temperature").Value = round(random.uniform(15, 35), 1)
            rs.Fields("MaxTemp").Value = round(random.uniform(25, 40), 1)
            rs.Fields("MinTemp").Value = round(random.uniform(5, 20), 1)
            rs.Fields("SolarRadiation").Value = round(random.uniform(0, 30), 2)
            rs.Fields("RainFall").Value = round(random.uniform(0, 5), 1)
            rs.Fields("Humidity").Value = round(random.uniform(30, 90), 1)
            rs.Fields("WindRun").Value = round(random.uniform(0, 50), 1)
            rs.Fields("ET").Value = round(random.uniform(0, 8), 2)
            rs.Update()
            count += 1
        finally:
            rs.Close()
    print(f"  + Inserted {count} weather records ({ts})")
    return count


def insert_event_data(db):
    sites = _get_indices(db, "SITE_CF")
    if not sites:
        print("  No sites found - skipping events")
        return 0
    events = [
        ("A", "Communication successful"), ("A", "Schedule started"),
        ("A", "Irrigation completed"), ("W", "Low battery warning"),
        ("W", "Signal strength weak"), ("A", "Weather data received"),
        ("A", "ET calculated"), ("E", "Communication timeout"),
        ("A", "Station runtime completed"), ("W", "Flow rate exceeded threshold"),
        ("A", "Rain delay activated"), ("A", "Program download complete"),
        ("E", "Sensor malfunction"), ("A", "Flow zone reading updated"),
    ]
    count = 0
    ts = get_timestamp()
    for _ in range(random.randint(2, 6)):
        flag, text = random.choice(events)
        rs = db.OpenRecordset("XA_EVENT")
        try:
            rs.AddNew()
            rs.Fields("XactStamp").Value = ts
            rs.Fields("XactIndex").Value = random.choice(sites)
            rs.Fields("EventSource").Value = random.choice(["S", "W"])
            rs.Fields("EventNumber").Value = random.randint(1000, 9999)
            rs.Fields("EventFlag").Value = flag
            rs.Fields("EventTextQualifier").Value = text
            rs.Update()
            count += 1
        finally:
            rs.Close()
    print(f"  + Inserted {count} event records ({ts})")
    return count


def insert_flow_data(db):
    zones = _get_indices(db, "FLOZO_CF")
    if not zones:
        print("  No flow zones found - skipping")
        return 0
    count = 0
    ts = get_timestamp()
    for idx in random.sample(zones, min(3, len(zones))):
        rs = db.OpenRecordset("XA_FLOZO")
        try:
            rs.AddNew()
            rs.Fields("XactStamp").Value = ts
            rs.Fields("XactIndex").Value = idx
            rs.Fields("FlowZoneValue").Value = random.randint(50, 500)
            rs.Fields("FlowZoneMultiplier").Value = random.choice([1, 10, 100])
            rs.Fields("SiteID").Value = idx
            rs.Update()
            count += 1
        finally:
            rs.Close()
    print(f"  + Inserted {count} flow records ({ts})")
    return count


def insert_signal_data(db):
    controllers = _get_indices(db, "CTROL_CF")
    if not controllers:
        print("  No controllers found - skipping signals")
        return 0
    count = 0
    ts = get_timestamp()
    for _ in range(random.randint(2, 5)):
        rs = db.OpenRecordset("XA_LOG")
        try:
            rs.AddNew()
            rs.Fields("XactStamp").Value = ts
            rs.Fields("XactIndex").Value = random.choice(controllers)
            rs.Fields("ControllerChannel").Value = random.randint(1, 48)
            rs.Fields("SignalIndex").Value = random.randint(1, 200)
            rs.Fields("SignalTable").Value = random.choice(["P", "S", "D", "C"])
            rs.Fields("SignalType").Value = random.choice(["R", "S", "E"])
            rs.Fields("SignalValue").Value = random.randint(0, 255)
            rs.Fields("SignalMultiplier").Value = random.choice([1.0, 0.1, 10.0])
            rs.Update()
            count += 1
        finally:
            rs.Close()
    print(f"  + Inserted {count} signal records ({ts})")
    return count


def insert_et_checkbook(db):
    sites = _get_indices(db, "SITE_CF")
    if not sites:
        print("  No sites found - skipping ET checkbook")
        return 0
    count = 0
    ts = get_timestamp()
    for idx in random.sample(sites, min(3, len(sites))):
        rs = db.OpenRecordset("XA_ETCheckBook")
        try:
            rs.AddNew()
            rs.Fields("XactStamp").Value = ts
            rs.Fields("SiteID").Value = idx
            rs.Fields("SoilMoisture").Value = round(random.uniform(20, 80), 1)
            rs.Fields("Rainfall").Value = round(random.uniform(0, 3), 2)
            rs.Fields("ET").Value = round(random.uniform(1, 8), 2)
            rs.Fields("Irrigation").Value = round(random.uniform(0, 15), 2)
            rs.Fields("SoilMoistureHoldingCapacity").Value = round(random.uniform(50, 100), 1)
            rs.Fields("SoilRefillPercentage").Value = random.randint(40, 100)
            rs.Update()
            count += 1
        finally:
            rs.Close()
    print(f"  + Inserted {count} ET checkbook records ({ts})")
    return count


def insert_runtime_data(db):
    rs = db.OpenRecordset("SELECT IndexNumber, StationSiteNumber FROM STATN_CF")
    stations = []
    try:
        while not rs.EOF:
            stations.append({
                "idx": rs.Fields("IndexNumber").Value,
                "site": rs.Fields("StationSiteNumber").Value,
            })
            rs.MoveNext()
    finally:
        rs.Close()
    if not stations:
        print("  No stations found - skipping runtime")
        return 0
    count = 0
    ts = get_timestamp()
    for _ in range(random.randint(2, 6)):
        stn = random.choice(stations)
        rs = db.OpenRecordset("XA_RuntimeProject")
        try:
            rs.AddNew()
            rs.Fields("TimeStamps").Value = ts
            rs.Fields("StationID").Value = stn["idx"]
            rs.Fields("SiteID").Value = stn["site"]
            rs.Fields("RunTime").Value = random.randint(5, 120)
            rs.Update()
            count += 1
        finally:
            rs.Close()
    print(f"  + Inserted {count} runtime records ({ts})")
    return count


def run_once(mdb_path):
    print(f"\n{'='*50}")
    print(f"Seeding test data: {mdb_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    db = open_db(mdb_path)
    try:
        total = 0
        total += insert_weather_data(db)
        total += insert_event_data(db)
        total += insert_flow_data(db)
        total += insert_signal_data(db)
        total += insert_et_checkbook(db)
        total += insert_runtime_data(db)
        print(f"\n  Total inserted: {total}")
        return total
    finally:
        db.Close()


def main():
    mdb_path = find_mdb()
    if not mdb_path:
        print("=" * 50)
        print("ERROR: Maxicom2.mdb not found!")
        print("Searched in:")
        for p in SEARCH_PATHS:
            print(f"  - {p}")
        print("\nEdit SEARCH_PATHS in this script to add your MDB location.")
        print("=" * 50)
        sys.exit(1)

    print(f"Found MDB: {mdb_path}")

    loop = "--loop" in sys.argv
    interval = 30
    if loop:
        for arg in sys.argv[1:]:
            if arg.isdigit():
                interval = int(arg)
                break
        print(f"Loop mode: every {interval}s (Ctrl+C to stop)")
        try:
            import time
            while True:
                run_once(mdb_path)
                print(f"\n  Next insert in {interval}s...")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\nStopped.")
    else:
        run_once(mdb_path)


if __name__ == "__main__":
    main()