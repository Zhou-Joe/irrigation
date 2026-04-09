"""
MDB Database Integration Script
================================
Reads all tables from the Maxicom2.mdb irrigation control database,
exports them to CSV files, and creates a unified SQLite database
with proper foreign key relationships.

Database: Maxicom2 (Rain Bird Maxicom2 Central Control)
System: Shanghai Disney Resort Irrigation System
"""

import win32com.client
import os
import csv
import sqlite3
import json
from datetime import datetime
from collections import defaultdict

# === Configuration ===
MDB_PATH = os.path.abspath(r'C:\Users\czhou7\PythonProjects\irrigation\Database\Maxicom2.mdb')
MDB_PASSWORD = 'RLM6808'
OUTPUT_DIR = os.path.abspath(r'C:\Users\czhou7\PythonProjects\irrigation\mdb_export')
SQLITE_PATH = os.path.join(OUTPUT_DIR, 'maxicom_integrated.db')

# DAO field type mapping
DAO_TYPE_MAP = {
    1: 'INTEGER',      # Boolean/YesNo
    2: 'TEXT',         # Byte
    3: 'INTEGER',      # Integer
    4: 'INTEGER',      # Long
    5: 'REAL',         # Currency
    6: 'REAL',         # Single
    7: 'REAL',         # Double
    8: 'TEXT',         # Date/Time (stored as text in Maxicom format)
    9: 'TEXT',         # Binary
    10: 'TEXT',        # Text/Memo
    11: 'TEXT',        # OLE
    12: 'TEXT',        # Memo/Hyperlink
}

# Table categories for organized output
TABLE_CATEGORIES = {
    'System': ['M_SYSTEM', 'M_PWORD', 'M_PWFREE', 'INDICES'],
    'Site Configuration': ['SITE_CF'],
    'Controller': ['CTROL_CF', 'CTROL_TP'],
    'Station': ['STATN_CF'],
    'Decoder': ['DCODE_CF', 'DCODE_TP'],
    'Connection': ['CNECT_CF'],
    'Contact': ['CTACT_CF', 'CTACT_TP'],
    'Schedule': ['SCHED_CF', 'Station_Schedule'],
    'Weather': ['WETHR_CF', 'WETHR_TP'],
    'Flow Zone': ['FLOZO_CF'],
    'Macros': ['M_CYCLE', 'M_FLOWRT', 'M_MICLIM', 'M_PRECRT', 'M_SOAK', 'M_WTRBGT'],
    'Weather Logs': ['XA_WETHR', 'XA_ET', 'XA_ETCheckBook'],
    'Signal Logs': ['XA_LOG'],
    'Events': ['XA_EVENT'],
    'Flow Logs': ['XA_FLOZO', 'XA_FLOZO_TMP', 'XA_FlowProject'],
    'Runtime': ['XA_RuntimeProject'],
    'Contact Logs': ['XA_ContactLog'],
    'Calendar': ['XA_CLNDR'],
    'Historical': ['XA_HIST'],
    'Memos': ['XA_MEMO'],
    'Diagnostics': ['XA_WirelessDiagnosis', 'XA_WirelessDiagnosis_TMP'],
    'Export Errors': ['XA_LOG_ExportErrors', 'XA_WETHR_ExportErrors'],
}

# Known foreign key relationships (parent -> child)
RELATIONSHIPS = [
    # Site hierarchy
    ('SITE_CF', 'IndexNumber', 'CTROL_CF', 'ControllerSiteNumber', 'A site has many controllers'),
    ('SITE_CF', 'IndexNumber', 'STATN_CF', 'StationSiteNumber', 'A site has many stations'),
    ('SITE_CF', 'IndexNumber', 'DCODE_CF', 'DecoderSiteNumber', 'A site has many decoders'),
    ('SITE_CF', 'IndexNumber', 'SCHED_CF', 'ScheduleSiteNumber', 'A site has many schedules'),
    ('SITE_CF', 'IndexNumber', 'CNECT_CF', 'ConnectSiteNumber', 'A site has many connections'),
    ('SITE_CF', 'IndexNumber', 'FLOZO_CF', 'FlowZoneSiteNumber', 'A site has many flow zones'),
    
    # Controller hierarchy
    ('CTROL_CF', 'IndexNumber', 'STATN_CF', 'StationControllerNumber', 'A controller has many stations'),
    ('CTROL_CF', 'IndexNumber', 'DCODE_CF', 'DecoderControllerNumber', 'A controller has many decoders'),
    ('CTROL_TP', 'IndexNumber', 'CTROL_CF', 'TableIndexNumber', 'Controller type definition'),
    
    # Station relationships
    ('M_PRECRT', 'IndexNumber', 'STATN_CF', 'StationPrecipMacro', 'Station precipitation rate'),
    ('M_FLOWRT', 'IndexNumber', 'STATN_CF', 'StationFlowMacro', 'Station flow rate'),
    ('M_MICLIM', 'IndexNumber', 'STATN_CF', 'StationMicroclimeMacro', 'Station microclimate'),
    ('M_CYCLE', 'IndexNumber', 'STATN_CF', 'StationCycleMacro', 'Station cycle time'),
    ('M_SOAK', 'IndexNumber', 'STATN_CF', 'StationSoakMacro', 'Station soak time'),
    
    # Decoder relationships
    ('DCODE_TP', 'IndexNumber', 'DCODE_CF', 'TableIndexNumber', 'Decoder type definition'),
    
    # Weather relationships
    ('WETHR_TP', 'IndexNumber', 'WETHR_CF', 'TableIndexNumber', 'Weather type definition'),
    ('WETHR_CF', 'IndexNumber', 'XA_WETHR', 'XactIndex', 'Weather readings per station'),
    
    # Schedule relationships
    ('SCHED_CF', 'IndexNumber', 'Station_Schedule', 'ScheduleNumber', 'Schedule assigned to stations'),
    
    # Contact relationships
    ('CTACT_TP', 'IndexNumber', 'CTACT_CF', 'TableIndexNumber', 'Contact type definition'),
    
    # Log relationships
    ('SITE_CF', 'IndexNumber', 'XA_ETCheckBook', 'SiteID', 'ET checkbook per site'),
    ('SITE_CF', 'IndexNumber', 'XA_RuntimeProject', 'SiteID', 'Runtime per site'),
    ('SITE_CF', 'IndexNumber', 'XA_FlowProject', 'SiteID', 'Flow project per site'),
    ('STATN_CF', 'IndexNumber', 'XA_RuntimeProject', 'StationID', 'Runtime per station'),
    ('CTROL_CF', 'IndexNumber', 'XA_LOG', 'XactIndex', 'Signal log per controller'),
    ('FLOZO_CF', 'IndexNumber', 'XA_FLOZO', 'XactIndex', 'Flow zone readings'),
    
    # Connection to Site
    ('CNECT_CF', 'IndexNumber', 'SITE_CF', 'SiteNumber', 'Connection linked to site'),
]


def open_mdb():
    """Open the MDB database using DAO.DBEngine.120"""
    print(f"Opening: {MDB_PATH}")
    print(f"File size: {os.path.getsize(MDB_PATH) / (1024*1024):.1f} MB")
    
    db_engine = win32com.client.Dispatch("DAO.DBEngine.120")
    db = db_engine.OpenDatabase(MDB_PATH, False, True, f";pwd={MDB_PASSWORD}")
    print(f"Database opened successfully! Tables: {db.TableDefs.Count}")
    return db


def get_user_tables(db):
    """Get all non-system table definitions"""
    tables = []
    for i in range(db.TableDefs.Count):
        table = db.TableDefs(i)
        if not table.Name.startswith('MSys') and not table.Name.startswith('~'):
            tables.append(table)
    return tables


def get_table_columns(table):
    """Get column names and types from a table definition"""
    columns = []
    for j in range(table.Fields.Count):
        field = table.Fields(j)
        col_type = DAO_TYPE_MAP.get(field.Type, 'TEXT')
        columns.append((field.Name, col_type))
    return columns


def read_table_rows(db, table_name, columns):
    """Read all rows from a table, returning list of dicts"""
    col_names = [c[0] for c in columns]
    rows = []
    
    try:
        rs = db.OpenRecordset(table_name)
        while not rs.EOF:
            row = {}
            for j, name in enumerate(col_names):
                val = rs.Fields(j).Value
                if val is None:
                    row[name] = None
                elif isinstance(val, (float, int, bool)):
                    row[name] = val
                elif isinstance(val, datetime):
                    row[name] = val.isoformat()
                else:
                    row[name] = str(val).strip()
            rows.append(row)
            rs.MoveNext()
        rs.Close()
    except Exception as e:
        print(f"    Error reading {table_name}: {e}")
    
    return rows


def export_table_to_csv(table_name, columns, rows, output_dir):
    """Export a table to CSV"""
    csv_path = os.path.join(output_dir, 'csv', f'{table_name}.csv')
    col_names = [c[0] for c in columns]
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=col_names, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    
    return csv_path


def create_sqlite_table(cursor, table_name, columns):
    """Create a table in SQLite"""
    col_defs = []
    for col_name, col_type in columns:
        col_defs.append(f'"{col_name}" {col_type}')
    
    sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
    cursor.execute(sql)


def insert_sqlite_rows(cursor, table_name, columns, rows):
    """Insert rows into SQLite table"""
    if not rows:
        return 0
    
    col_names = [c[0] for c in columns]
    placeholders = ', '.join(['?' for _ in col_names])
    col_str = ', '.join([f'"{c}"' for c in col_names])
    sql = f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})'
    
    inserted = 0
    for row in rows:
        values = []
        for col_name in col_names:
            val = row.get(col_name)
            # Truncate long strings to prevent issues
            if isinstance(val, str) and len(val) > 4000:
                val = val[:4000]
            values.append(val)
        try:
            cursor.execute(sql, values)
            inserted += 1
        except Exception as e:
            print(f"    Insert error in {table_name}: {e}")
    
    return inserted


def build_integrated_views(sqlite_conn):
    """Create integrated SQL views that join related tables"""
    cursor = sqlite_conn.cursor()
    
    # View: Full Station Overview (station + site + controller + macros)
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_station_overview AS
        SELECT 
            s.IndexNumber AS StationID,
            s.IndexName AS StationName,
            site.IndexName AS SiteName,
            site.SiteNumber AS SiteNumber,
            ctrl.IndexName AS ControllerName,
            ctrl.ControllerLinkChannel AS ControllerChannel,
            s.StationControllerChannel AS StationChannel,
            s.StationPrecipFactor AS PrecipRate,
            s.StationFlowFactor AS FlowRate,
            s.StationMicroclimeFactor AS MicroclimateFactor,
            s.StationCycleTime AS CycleTime,
            s.StationSoakTime AS SoakTime,
            s.StationMemo AS Memo,
            s.Lockout,
            s.FloManagerPriorityLevel
        FROM STATN_CF s
        LEFT JOIN SITE_CF site ON s.StationSiteNumber = site.IndexNumber
        LEFT JOIN CTROL_CF ctrl ON s.StationControllerNumber = ctrl.IndexNumber
    ''')
    
    # View: Site Summary with stats
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_site_summary AS
        SELECT 
            site.IndexNumber AS SiteID,
            site.IndexName AS SiteName,
            site.SiteNumber,
            site.SiteTimeZone,
            site.SiteWaterPricing,
            site.SiteWaterETCurrent,
            site.SiteWaterETDefault,
            (SELECT COUNT(*) FROM CTROL_CF c WHERE c.ControllerSiteNumber = site.IndexNumber) AS ControllerCount,
            (SELECT COUNT(*) FROM STATN_CF s WHERE s.StationSiteNumber = site.IndexNumber) AS StationCount,
            (SELECT COUNT(*) FROM SCHED_CF sc WHERE sc.ScheduleSiteNumber = site.IndexNumber) AS ScheduleCount
        FROM SITE_CF site
    ''')
    
    # View: Weather Readings with station info
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_weather_readings AS
        SELECT 
            w.XactStamp,
            w.XactIndex AS WeatherStationID,
            wc.IndexName AS WeatherStationName,
            w.Temperature,
            w.MaxTemp,
            w.MinTemp,
            w.SolarRadiation,
            w.RainFall,
            w.Humidity,
            w.WindRun,
            w.ET
        FROM XA_WETHR w
        LEFT JOIN WETHR_CF wc ON w.XactIndex = wc.IndexNumber
    ''')
    
    # View: Flow Zone Readings
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_flow_zone_readings AS
        SELECT 
            f.XactStamp,
            f.XactIndex AS FlowZoneID,
            fz.IndexName AS FlowZoneName,
            f.FlowZoneValue,
            f.FlowZoneMultiplier,
            f.SiteID
        FROM XA_FLOZO f
        LEFT JOIN FLOZO_CF fz ON f.XactIndex = fz.IndexNumber
    ''')
    
    # View: System Events
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_events AS
        SELECT 
            e.ID,
            e.XactStamp,
            e.EventSource,
            e.XactIndex,
            e.EventNumber,
            e.EventFlag,
            e.EventTextQualifier
        FROM XA_EVENT e
        ORDER BY e.XactStamp DESC
    ''')
    
    # View: Runtime per Station
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_runtime AS
        SELECT 
            r.TimeStamps,
            r.StationID,
            s.IndexName AS StationName,
            r.SiteID,
            site.IndexName AS SiteName,
            r.RunTime
        FROM XA_RuntimeProject r
        LEFT JOIN STATN_CF s ON r.StationID = s.IndexNumber
        LEFT JOIN SITE_CF site ON r.SiteID = site.IndexNumber
    ''')
    
    # View: ET Checkbook (soil moisture balance)
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_et_checkbook AS
        SELECT 
            e.XactStamp,
            e.SiteID,
            site.IndexName AS SiteName,
            e.SoilMoisture,
            e.Rainfall,
            e.ET,
            e.Irrigation,
            e.SoilMoistureHoldingCapacity,
            e.SoilRefillPercentage
        FROM XA_ETCheckBook e
        LEFT JOIN SITE_CF site ON e.SiteID = site.IndexNumber
    ''')
    
    # View: Schedule overview
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_schedule_overview AS
        SELECT 
            sc.IndexNumber AS ScheduleID,
            sc.IndexName AS ScheduleName,
            site.IndexName AS SiteName,
            sc.ScheduleNominalET,
            sc.ScheduleWaterBudgetFactor,
            sc.ScheduleSendAutomatic,
            sc.ScheduleSendProtected,
            sc.ScheduleInstructionFile,
            sc.ScheduleSensitizedET,
            sc.ScheduleFloManage
        FROM SCHED_CF sc
        LEFT JOIN SITE_CF site ON sc.ScheduleSiteNumber = site.IndexNumber
    ''')
    
    # View: Connection overview
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_connection_overview AS
        SELECT 
            c.IndexNumber AS ConnectionID,
            c.IndexName AS ConnectionName,
            c.ConnectCapacity,
            c.ConnectStations,
            site.IndexName AS SiteName
        FROM CNECT_CF c
        LEFT JOIN SITE_CF site ON c.ConnectSiteNumber = site.IndexNumber
    ''')
    
    # View: Full irrigation hierarchy
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_irrigation_hierarchy AS
        SELECT 
            site.IndexNumber AS SiteID,
            site.IndexName AS SiteName,
            ctrl.IndexNumber AS ControllerID,
            ctrl.IndexName AS ControllerName,
            ctrl.ControllerEnabled AS ControllerEnabled,
            st.IndexNumber AS StationID,
            st.IndexName AS StationName,
            st.StationControllerChannel AS Channel,
            st.StationPrecipFactor AS PrecipRate,
            st.StationFlowFactor AS FlowRate,
            st.Lockout AS StationLockout,
            st.FloManagerPriorityLevel AS PriorityLevel,
            conn.IndexName AS ConnectionName,
            conn.ConnectCapacity AS ConnectionCapacity
        FROM SITE_CF site
        LEFT JOIN CTROL_CF ctrl ON ctrl.ControllerSiteNumber = site.IndexNumber
        LEFT JOIN STATN_CF st ON st.StationControllerNumber = ctrl.IndexNumber 
            AND st.StationSiteNumber = site.IndexNumber
        LEFT JOIN CNECT_CF conn ON conn.ConnectSiteNumber = site.IndexNumber
            AND conn.ConnectSiteCounter = st.StationConnection
    ''')
    
    sqlite_conn.commit()
    print("  Created integrated views")


def generate_report(sqlite_conn):
    """Generate a summary report of the integrated database"""
    cursor = sqlite_conn.cursor()
    
    report = []
    report.append("=" * 80)
    report.append("MAXICOM2 DATABASE INTEGRATION REPORT")
    report.append("=" * 80)
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # System info
    try:
        cursor.execute("SELECT * FROM M_SYSTEM")
        sys_row = cursor.fetchone()
        if sys_row:
            cols = [desc[0] for desc in cursor.description]
            sys_data = dict(zip(cols, sys_row))
            report.append("SYSTEM INFORMATION")
            report.append("-" * 40)
            report.append(f"  System Name: {sys_data.get('SystemName', 'N/A')}")
            report.append(f"  System ID: {sys_data.get('SystemID', 'N/A')}")
            report.append(f"  Product Version: {sys_data.get('ProductVersionNumber', 'N/A')}")
            report.append(f"  Preferred Units: {sys_data.get('PreferredUnits', 'N/A')}")
            report.append(f"  Currency: {sys_data.get('PreferredCurrency', 'N/A')}")
            report.append(f"  Water Price: {sys_data.get('SystemWaterPrice', 'N/A')}")
            report.append(f"  TCP Port: {sys_data.get('TCPPort', 'N/A')}")
            report.append("")
    except Exception:
        pass
    
    # Site summary
    report.append("SITE SUMMARY")
    report.append("-" * 40)
    try:
        cursor.execute("SELECT * FROM v_site_summary")
        for row in cursor.fetchall():
            cols = [desc[0] for desc in cursor.description]
            data = dict(zip(cols, row))
            report.append(f"  Site: {data.get('SiteName', 'N/A')} (ID={data.get('SiteID', '?')})")
            report.append(f"    Controllers: {data.get('ControllerCount', 0)}, "
                         f"Stations: {data.get('StationCount', 0)}, "
                         f"Schedules: {data.get('ScheduleCount', 0)}")
            report.append(f"    Water Price: {data.get('SiteWaterPricing', 'N/A')}, "
                         f"ET Current: {data.get('SiteWaterETCurrent', 'N/A')}")
            report.append(f"    Rain Shutdown: {data.get('RainShutDownApplies', 'N/A')}")
            report.append("")
    except Exception as e:
        report.append(f"  Error: {e}")
        report.append("")
    
    # Table row counts
    report.append("TABLE ROW COUNTS")
    report.append("-" * 40)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for (table_name,) in cursor.fetchall():
        if table_name.startswith('sqlite_'):
            continue
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            count = cursor.fetchone()[0]
            report.append(f"  {table_name}: {count:,} rows")
        except Exception:
            pass
    report.append("")
    
    # View list
    report.append("INTEGRATED VIEWS")
    report.append("-" * 40)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
    for (view_name,) in cursor.fetchall():
        report.append(f"  {view_name}")
    report.append("")
    
    # Recent events
    report.append("RECENT EVENTS (Last 20)")
    report.append("-" * 40)
    try:
        cursor.execute("SELECT * FROM v_events LIMIT 20")
        for row in cursor.fetchall():
            cols = [desc[0] for desc in cursor.description]
            data = dict(zip(cols, row))
            report.append(f"  {data.get('XactStamp', '?')}: "
                         f"[{data.get('EventFlag', '?')}] {data.get('EventTextQualifier', '?')}")
    except Exception as e:
        report.append(f"  Error: {e}")
    report.append("")
    
    report.append("=" * 80)
    report.append(f"Output directory: {OUTPUT_DIR}")
    report.append(f"SQLite database: {SQLITE_PATH}")
    report.append(f"CSV files: {os.path.join(OUTPUT_DIR, 'csv')}")
    report.append("=" * 80)
    
    return "\n".join(report)


def main():
    start_time = datetime.now()
    print(f"\n{'='*60}")
    print("Maxicom2 MDB Database Integration Script")
    print(f"{'='*60}")
    
    # Create output directories
    os.makedirs(os.path.join(OUTPUT_DIR, 'csv'), exist_ok=True)
    
    # Remove existing SQLite database
    if os.path.exists(SQLITE_PATH):
        os.remove(SQLITE_PATH)
    
    # Open MDB
    db = open_mdb()
    
    # Get all user tables
    tables = get_user_tables(db)
    print(f"User tables: {len(tables)}")
    
    # Create SQLite database
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.execute("PRAGMA journal_mode=WAL")
    sqlite_conn.execute("PRAGMA synchronous=NORMAL")
    sqlite_cursor = sqlite_conn.cursor()
    
    # Process each table
    table_data = {}
    table_columns = {}
    
    for table in tables:
        table_name = table.Name
        columns = get_table_columns(table)
        table_columns[table_name] = columns
        
        # Get row count estimate
        try:
            rs = db.OpenRecordset(table_name)
            rs.MoveLast()
            row_count = rs.RecordCount
            rs.Close()
        except:
            row_count = "?"
        
        print(f"\n  Processing: {table_name} ({len(columns)} columns, ~{row_count} rows)")
        
        # Create SQLite table
        create_sqlite_table(sqlite_cursor, table_name, columns)
        
        # Read data
        print(f"    Reading data...")
        rows = read_table_rows(db, table_name, columns)
        table_data[table_name] = rows
        print(f"    Read {len(rows)} rows")
        
        # Insert into SQLite
        if rows:
            inserted = insert_sqlite_rows(sqlite_cursor, table_name, columns, rows)
            print(f"    Inserted {inserted} rows into SQLite")
        
        # Export to CSV
        csv_path = export_table_to_csv(table_name, columns, rows, OUTPUT_DIR)
        print(f"    Exported CSV: {os.path.basename(csv_path)}")
    
    sqlite_conn.commit()
    
    # Create relationships metadata
    print(f"\n{'='*60}")
    print("Creating integrated views...")
    build_integrated_views(sqlite_conn)
    
    # Save relationship info
    relations_path = os.path.join(OUTPUT_DIR, 'relationships.json')
    with open(relations_path, 'w', encoding='utf-8') as f:
        json.dump(RELATIONSHIPS, f, indent=2, ensure_ascii=False)
    print(f"Saved relationships to: {relations_path}")
    
    # Save table categories
    categories_path = os.path.join(OUTPUT_DIR, 'table_categories.json')
    with open(categories_path, 'w', encoding='utf-8') as f:
        json.dump(TABLE_CATEGORIES, f, indent=2, ensure_ascii=False)
    print(f"Saved table categories to: {categories_path}")
    
    # Generate report
    print(f"\n{'='*60}")
    print("Generating integration report...")
    report = generate_report(sqlite_conn)
    print(report)
    
    # Save report
    report_path = os.path.join(OUTPUT_DIR, 'integration_report.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    # Cleanup
    sqlite_conn.close()
    db.Close()
    
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\nIntegration complete in {elapsed:.1f} seconds!")
    print(f"Output: {OUTPUT_DIR}")
    print(f"  - CSV files: csv/")
    print(f"  - SQLite DB: {os.path.basename(SQLITE_PATH)}")
    print(f"  - Report: integration_report.txt")


if __name__ == '__main__':
    main()