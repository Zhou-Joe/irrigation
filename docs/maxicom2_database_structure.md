# Maxicom2 Access Database Structure & Content

> **Database File**: `Database/Maxicom2.mdb`  
> **System**: Rain Bird Maxicom2 Central Control — Shanghai Disney Resort Irrigation System  
> **Password**: `RLM6808`  
> **Access Method**: DAO.DBEngine.120 (win32com)  
> **Total Tables**: 41 user tables (excluding MSys~/~ system tables)  
> **Product Version**: 4.4  
> **System ID**: 762029  
> **Preferred Units**: Liters | **Currency**: RMB  

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Entity-Relationship Diagram](#2-entity-relationship-diagram)
3. [Configuration Tables](#3-configuration-tables)
4. [Time-Series / Log Tables](#4-time-series--log-tables)
5. [Auxiliary Tables](#5-auxiliary-tables)
6. [Data Pipeline](#6-data-pipeline)
7. [Django Model Mapping](#7-django-model-mapping)
8. [SQLite Integrated Views](#8-sqlite-integrated-views)

---

## 1. System Overview

| Metric | Value |
|--------|-------|
| System Name | SHANGHAI DISNEY RESORT |
| Sites (SITE_CF) | 1,233 rows (includes historical/closed) |
| Controllers (CTROL_CF) | 168 |
| Stations (STATN_CF) | 3,802 |
| Schedules (SCHED_CF) | 11,205 |
| Weather Stations (WETHR_CF) | 26 |
| Weather Log Entries (XA_WETHR) | 82,720 |
| Flow Zone Readings (XA_FLOZO) | ~4,046,349 |
| Signal Logs (XA_LOG) | 432,056 |
| Events (XA_EVENT) | 1,214 |
| ET Checkbook (XA_ETCheckBook) | 9,131 |
| Runtime Records (XA_RuntimeProject) | 3,697 |
| Contact Logs (XA_ContactLog) | 25,254 |

---

## 2. Entity-Relationship Diagram

```
M_SYSTEM (System Config)
    │
    ├── SITE_CF (Irrigation Sites) ─────────────────────────────────┐
    │       │                                                        │
    │       ├── CTROL_CF (Controllers) ──┐                          │
    │       │       │                     │                          │
    │       │       └── STATN_CF (Stations) ── Station_Schedule     │
    │       │               │                                        │
    │       │               └── DCODE_CF (Decoders)                  │
    │       │                                                        │
    │       ├── SCHED_CF (Schedules)                                 │
    │       ├── FLOZO_CF (Flow Zones)                                │
    │       └── CNECT_CF (Connections)                               │
    │                                                                │
    ├── WETHR_CF (Weather Stations) ── XA_WETHR (Weather Logs)      │
    │                                                                │
    └── CTACT_CF (Contact Config) ── XA_ContactLog ─────────────────┘
                                    
Time-Series Tables (linked by XactStamp timestamps):
    XA_WETHR ─────── Weather readings (per weather station)
    XA_EVENT ─────── System events
    XA_ETCheckBook ─ Soil moisture balance (per site)
    XA_FLOZO ─────── Flow zone readings (~4M rows)
    XA_LOG ───────── Signal logs (per controller)
    XA_RuntimeProject ─ Runtime data (per station/site)
    XA_FlowProject ── Flow project aggregated data
    XA_ContactLog ─── Communication contact logs
```

### Foreign Key Relationships

| Parent Table | PK Column | Child Table | FK Column | Description |
|---|---|---|---|---|
| `SITE_CF` | `IndexNumber` | `CTROL_CF` | `ControllerSiteNumber` | Site → Controllers |
| `SITE_CF` | `IndexNumber` | `STATN_CF` | `StationSiteNumber` | Site → Stations |
| `SITE_CF` | `IndexNumber` | `SCHED_CF` | `ScheduleSiteNumber` | Site → Schedules |
| `SITE_CF` | `IndexNumber` | `FLOZO_CF` | `FlowZoneSiteNumber` | Site → Flow Zones |
| `SITE_CF` | `IndexNumber` | `CNECT_CF` | `ConnectSiteNumber` | Site → Connections |
| `SITE_CF` | `IndexNumber` | `DCODE_CF` | `DecoderSiteNumber` | Site → Decoders |
| `CTROL_CF` | `IndexNumber` | `STATN_CF` | `StationControllerNumber` | Controller → Stations |
| `CTROL_CF` | `IndexNumber` | `XA_LOG` | `XactIndex` | Controller → Signal Logs |
| `CTROL_TP` | `IndexNumber` | `CTROL_CF` | `TableIndexNumber` | Controller Type definition |
| `WETHR_CF` | `IndexNumber` | `XA_WETHR` | `XactIndex` | Weather Station → Readings |
| `FLOZO_CF` | `IndexNumber` | `XA_FLOZO` | `XactIndex` | Flow Zone → Readings |
| `SCHED_CF` | `IndexNumber` | `Station_Schedule` | `ScheduleNumber` | Schedule → Station assignments |
| `SITE_CF` | `IndexNumber` | `XA_ETCheckBook` | `SiteID` | Site → ET Checkbook |
| `SITE_CF` | `IndexNumber` | `XA_RuntimeProject` | `SiteID` | Site → Runtime |
| `STATN_CF` | `IndexNumber` | `XA_RuntimeProject` | `StationID` | Station → Runtime |

---

## 3. Configuration Tables

### 3.1 `M_SYSTEM` — System Configuration (1 row)

Global system settings for the Maxicom2 central control.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `IndexNumber` | INTEGER | Primary key | 1 |
| `SystemName` | TEXT | System name | SHANGHAI DISNEY RESORT |
| `SystemID` | TEXT | System identifier | 762029 |
| `ProductVersionNumber` | TEXT | Software version | 4.4 |
| `PreferredUnits` | TEXT | Unit system | Liters |
| `PreferredCurrency` | TEXT | Currency | RMB |
| `SystemWaterPrice` | REAL | Water price per unit | 0.0170325 |
| `TCPPort` | INTEGER | TCP communication port | 6789 |
| `UserName` | TEXT | Admin user name | |
| `UserCompany` | TEXT | Company name | |
| `UserTelephone` | TEXT | Contact phone | |
| `DataKeptTime` | INTEGER | Data retention period | |
| `AutoPurge` | TEXT | Auto purge enabled (Y/N) | |
| `FloManagerPriorityLevels` | TEXT | Flow manager priority config | |
| `ActivationKeycode` | TEXT | License key | |
| `BackupDefaultPath` | TEXT | Auto-backup path | |

> **Total**: 50+ columns covering system preferences, communication settings, backup configuration, and licensing.

---

### 3.2 `SITE_CF` — Irrigation Sites (1,233 rows)

Each row represents an irrigation site (zone/area). Rows with `DateClose` values are historically closed; only `DateClose = NULL` rows are active sites.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `IndexNumber` | INTEGER | **PK** — Unique site index | 5 |
| `DateOpen` | TEXT | Creation timestamp (YYYYMMDDHHmmSS) | 20250303084944 |
| `DateClose` | TEXT | Closure timestamp (NULL if active) | NULL |
| `IndexName` | TEXT | Site name | "1 Berm West Entrance" |
| `SiteNumber` | INTEGER | Site number | 1 |
| `SiteTimeZone` | TEXT | Time zone | "China" |
| `SiteWaterPricing` | REAL | Water cost rate | 0.01325 |
| `SiteCCUVersion` | TEXT | CCU firmware version | "6.30R" |
| `SiteWaterETCurrent` | REAL | Current ET value | 0.1 |
| `SiteWaterETDefault` | REAL | Default ET value | 0.0787 |
| `SiteWaterETMinimum` | REAL | Minimum ET | 0.1181 |
| `SiteWaterETMaximum` | REAL | Maximum ET | 0.3937 |
| `SiteWaterCropCoefficient` | REAL | Crop coefficient | 1.0 |
| `SiteSoilMoistureCapacity` | REAL | Soil moisture holding capacity | 1.18 |
| `SiteRainShutDownApplies` | TEXT | Rain shutdown enabled (Y/N) | "Y" |
| `SiteContactTelephone` | TEXT | CCU IP/contact address | "173.16.173.129:10001T" |
| `SiteContactPort` | INTEGER | Communication port | 31 |
| `SiteContactAutomatic` | TEXT | Auto-contact enabled (Y/N) | "Y" |
| `FMGroups` | TEXT | Flow manager group assignments | |

> **Note**: The `IndexNumber` serves as the foreign key for all child tables (controllers, stations, schedules, flow zones, connections).

---

### 3.3 `CTROL_CF` — Controllers (168 rows)

Irrigation controllers (CCU/SAT) that manage stations on a site.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `IndexNumber` | INTEGER | **PK** | 10 |
| `IndexName` | TEXT | Controller name | "CCU1 IRR" |
| `TableIndexNumber` | INTEGER | → `CTROL_TP.IndexNumber` (type def) | 5 |
| `ControllerSiteNumber` | INTEGER | → `SITE_CF.IndexNumber` (parent site) | 5 |
| `ControllerLinkNumber` | INTEGER | Communication link number | 1 |
| `ControllerLinkChannel` | INTEGER | Communication channel | 1 |
| `ControllerEnabled` | TEXT | Enabled status (Y/N) | "Y" |
| `DateOpen` | TEXT | Creation timestamp | |

---

### 3.4 `STATN_CF` — Irrigation Stations (3,802 rows)

Individual irrigation points (sprinklers/drip zones) connected to controllers.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `IndexNumber` | INTEGER | **PK** — Unique station index | 42 |
| `IndexName` | TEXT | Station name | "Station 1" |
| `StationSiteNumber` | INTEGER | → `SITE_CF.IndexNumber` | 5 |
| `StationControllerNumber` | INTEGER | → `CTROL_CF.IndexNumber` | 10 |
| `StationControllerChannel` | INTEGER | Controller channel number | 1 |
| `StationPrecipFactor` | REAL | Precipitation rate factor | 0.5 |
| `StationFlowFactor` | REAL | Flow rate factor | 12.5 |
| `StationMicroclimeFactor` | INTEGER | Microclimate factor | 100 |
| `StationCycleTime` | INTEGER | Cycle time (minutes) | 10 |
| `StationSoakTime` | INTEGER | Soak time (minutes) | 30 |
| `StationMemo` | TEXT | Memo/notes | |
| `Lockout` | INTEGER | Lockout status (0/1) | 0 |
| `FloManagerPriorityLevel` | INTEGER | Flow management priority | 5 |
| `StationConnection` | INTEGER | → Connection index | |

---

### 3.5 `SCHED_CF` — Irrigation Schedules (11,205 rows)

Irrigation programs/schedules assigned to sites.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `IndexNumber` | INTEGER | **PK** | 100 |
| `IndexName` | TEXT | Schedule name | "Schedule 1" |
| `ScheduleSiteNumber` | INTEGER | → `SITE_CF.IndexNumber` | 5 |
| `ScheduleSiteCounter` | INTEGER | Site counter | 0 |
| `ScheduleNominalET` | REAL | Nominal ET for schedule | 0.15 |
| `ScheduleWaterBudgetFactor` | INTEGER | Water budget percentage | 100 |
| `ScheduleFloManage` | TEXT | Flow management enabled (Y/N) | "N" |
| `ScheduleSendAutomatic` | TEXT | Auto-send enabled (Y/N) | "Y" |
| `ScheduleSendProtected` | TEXT | Protected send (Y/N) | "N" |
| `ScheduleInstructionFile` | TEXT | Instruction file reference | |
| `ScheduleSensitizedET` | TEXT | Sensitized ET (Y/N) | "Y" |
| `ScheduleInstructionDays` | TEXT | Watering day pattern | |
| `ScheduleInstructionTimes` | TEXT | Watering time pattern | |

---

### 3.6 `Station_Schedule` — Station-Schedule Assignments (1,285 rows)

Many-to-many linking stations to schedules.

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | Station index → `STATN_CF.IndexNumber` |
| `ScheduleNumber` | INTEGER | Schedule index → `SCHED_CF.IndexNumber` |
| `Type` | TEXT | Assignment type |
| `TimeProjected` | TEXT | Projected execution time |
| `SiteID` | INTEGER | → `SITE_CF.IndexNumber` |

---

### 3.7 `FLOZO_CF` — Flow Zones (93 rows)

Flow monitoring zones for leak detection and water management.

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | **PK** |
| `IndexName` | TEXT | Flow zone name |
| `FlowZoneSiteNumber` | INTEGER | → `SITE_CF.IndexNumber` |
| `FlowZoneSiteCounter` | INTEGER | Site counter |
| `FlowZoneJoinSite` | TEXT | Join site flag (Y/N) |

---

### 3.8 `WETHR_CF` — Weather Stations (26 rows)

Weather stations providing ET, temperature, and rainfall data.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `IndexNumber` | INTEGER | **PK** | 1 |
| `IndexName` | TEXT | Station name | "Weather Station 1" |
| `WeatherDefaultET` | REAL | Default ET value | 0.15 |
| `WeatherTimeZone` | TEXT | Time zone | "China" |
| `WeatherLocationLatitude` | REAL | Latitude | 31.14 |
| `WeatherLocationElevate` | REAL | Elevation | 5 |
| `WeatherContactAutomatic` | TEXT | Auto-contact (Y/N) | "Y" |
| `WeatherContactTelephone` | TEXT | Contact address | |

---

### 3.9 `CNECT_CF` — Connections (163 rows)

Communication connections between the central control and field devices.

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | **PK** |
| `IndexName` | TEXT | Connection name |
| `ConnectLinkNumber` | INTEGER | Link number |
| `ConnectSiteNumber` | INTEGER | → `SITE_CF.IndexNumber` |
| `ConnectSiteCounter` | INTEGER | Site counter |
| `ConnectCapacity` | REAL | Connection capacity |
| `ConnectStations` | INTEGER | Number of stations on connection |

---

### 3.10 `DCODE_CF` — Decoders (91 rows)

Two-wire decoders connected to controllers for station control.

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | **PK** |
| `IndexName` | TEXT | Decoder name |
| `DecoderSiteNumber` | INTEGER | → `SITE_CF.IndexNumber` |
| `DecoderControllerNumber` | INTEGER | → `CTROL_CF.IndexNumber` |
| `DecoderControllerChannel` | INTEGER | Controller channel |
| `DecoderSatelliteNumber` | INTEGER | Satellite number |
| `DecoderPulseValue` | REAL | Pulse value |
| `DecoderEnabled` | TEXT | Enabled (Y/N) |
| `SensorAorB` | TEXT | Sensor A or B |

---

### 3.11 `CTACT_CF` — Contact Configurations (4 rows)

Communication device configurations (modem/TCP).

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | **PK** |
| `IndexName` | TEXT | Contact name |
| `ContactDeviceManager` | INTEGER | Device type |
| `ContactPort` | INTEGER | Port number |
| `ModemVolume` | TEXT | Modem volume setting |

---

### 3.12 Type Definition Tables

Reference/lookup tables for categorizing entities:

| Table | Rows | Purpose |
|-------|------|---------|
| `CTROL_TP` | 228 | Controller type definitions |
| `WETHR_TP` | 7 | Weather station type definitions |
| `DCODE_TP` | 15 | Decoder type definitions |
| `CTACT_TP` | 7 | Contact device type definitions |

Each has `IndexNumber` (PK) referenced by the corresponding `_CF` table's `TableIndexNumber`.

---

### 3.13 Macro Tables

Reusable parameter presets for station configuration:

| Table | Rows | Purpose | Referenced By |
|-------|------|---------|---------------|
| `M_PRECRT` | 4 | Precipitation rate macros | `STATN_CF.StationPrecipMacro` |
| `M_FLOWRT` | 0 | Flow rate macros | `STATN_CF.StationFlowMacro` |
| `M_MICLIM` | 0 | Microclimate macros | `STATN_CF.StationMicroclimeMacro` |
| `M_CYCLE` | 0 | Cycle time macros | `STATN_CF.StationCycleMacro` |
| `M_SOAK` | 0 | Soak time macros | `STATN_CF.StationSoakMacro` |
| `M_WTRBGT` | 1 | Water budget macros | `SCHED_CF.ScheduleWaterBudgetMacro` |

---

### 3.14 `INDICES` — Index Registry (26 rows)

Master index table tracking all entity types in the system.

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | Index value |
| `IndexName` | TEXT | Entity name |
| `TableIndexNumber` | INTEGER | Type reference |

---

## 4. Time-Series / Log Tables

All time-series tables use `XactStamp` (or `TimeStamps`) as the timestamp, stored as text in `YYYYMMDDHHmmSS` format (14-digit string).

### 4.1 `XA_WETHR` — Weather Log (82,720 rows)

Hourly(ish) weather readings from each weather station.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `XactStamp` | TEXT | Timestamp YYYYMMDDHHmmSS | "20260403080000" |
| `XactIndex` | INTEGER | → `WETHR_CF.IndexNumber` | 1 |
| `Temperature` | REAL | Temperature (°C) | 18.5 |
| `MaxTemp` | REAL | Max temperature | 22.1 |
| `MinTemp` | REAL | Min temperature | 14.3 |
| `SolarRadiation` | REAL | Solar radiation | 245.6 |
| `RainFall` | REAL | Rainfall (mm) | 0.0 |
| `Humidity` | REAL | Relative humidity (%) | 72.5 |
| `WindRun` | REAL | Wind run (km/day) | 120.3 |
| `ET` | REAL | Evapotranspiration (mm) | 2.15 |

---

### 4.2 `XA_EVENT` — System Events (1,214 rows)

Event log with warnings, errors, and informational messages.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ID` | INTEGER | Auto-increment PK | 1214 |
| `XactStamp` | TEXT | Timestamp | "20260403090216" |
| `EventSource` | TEXT | Source type (S=Site, W=Weather) | "S" |
| `XactIndex` | INTEGER | Related entity index | 5 |
| `EventNumber` | INTEGER | Event code | 101 |
| `EventFlag` | TEXT | Severity: E=Error, W=Warning, I=Info | "E" |
| `EventTextQualifier` | TEXT | Event description | "Site Automatic Receive Contact was successful. (COM4)" |

---

### 4.3 `XA_ETCheckBook` — ET Water Balance (9,131 rows)

Soil moisture balance tracking using the ET checkbook method.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `XactStamp` | TEXT | Timestamp | "20260403000000" |
| `SiteID` | INTEGER | → `SITE_CF.IndexNumber` | 5 |
| `SoilMoisture` | REAL | Current soil moisture | 0.65 |
| `Rainfall` | REAL | Rainfall amount | 0.0 |
| `ET` | REAL | Evapotranspiration | 2.15 |
| `Irrigation` | REAL | Irrigation applied | 15.0 |
| `UserRainfall` | REAL | Manual rainfall entry | 0.0 |
| `UserET` | REAL | Manual ET entry | 0.0 |
| `Flag` | TEXT | Status flag | |
| `SoilMoistureHoldingCapacity` | REAL | Max soil capacity | 1.18 |
| `SoilRefillPercentage` | INTEGER | Refill threshold % | 70 |

---

### 4.4 `XA_FLOZO` — Flow Zone Readings (~4,046,349 rows)

**Largest table.** Time-series flow measurements for each flow monitoring zone. Used for leak detection and water usage tracking.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `XactStamp` | TEXT | Timestamp YYYYMMDDHHmmSS | "20260403080000" |
| `XactIndex` | INTEGER | → `FLOZO_CF.IndexNumber` | 1 |
| `FlowZoneValue` | INTEGER | Raw flow reading | 1250 |
| `FlowZoneMultiplier` | INTEGER | Scaling multiplier | 10 |
| `SiteID` | INTEGER | → `SITE_CF.IndexNumber` | 5 |

> **Size note**: ~4M rows. Import can be limited per zone using `--flow-limit` flag.

---

### 4.5 `XA_LOG` — Signal Logs (432,056 rows)

Controller signal logs tracking all communication signals sent/received.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `XactStamp` | TEXT | Timestamp | "20260403084500" |
| `XactIndex` | INTEGER | → `CTROL_CF.IndexNumber` | 10 |
| `ControllerChannel` | INTEGER | Controller channel | 1 |
| `SignalIndex` | INTEGER | Signal sequence index | 5 |
| `SignalTable` | TEXT | Signal table reference | "S" |
| `SignalType` | TEXT | Signal type code | "R" |
| `SignalValue` | INTEGER | Raw signal value | 100 |
| `SignalMultiplier` | REAL | Value multiplier | 1.0 |

---

### 4.6 `XA_RuntimeProject` — Runtime Data (3,697 rows)

Projected/planned runtime for stations, used for scheduling and reporting.

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `TimeStamps` | TEXT | Timestamp | "20260403060000" |
| `StationID` | INTEGER | → `STATN_CF.IndexNumber` | 42 |
| `SiteID` | INTEGER | → `SITE_CF.IndexNumber` | 5 |
| `RunTime` | INTEGER | Planned run time (minutes) | 30 |

---

### 4.7 `XA_FlowProject` — Flow Project Data (2,356 rows)

Aggregated flow data per site across all flow watch zones.

| Column | Type | Description |
|--------|------|-------------|
| `TimeStamps` | TEXT | Timestamp |
| `SiteID` | INTEGER | → `SITE_CF.IndexNumber` |
| `FlowWatchZone0..20` | REAL | Flow values for up to 21 zones |
| `StationNum0..20` | INTEGER | Active station counts per zone |

---

### 4.8 `XA_ContactLog` — Contact/Communication Log (25,254 rows)

Records of communication sessions with field devices.

| Column | Type | Description |
|--------|------|-------------|
| `SourceID` | INTEGER | Communication source |
| `Type` | TEXT | Contact type |
| `SiteRainShutDownActive` | TEXT | Rain shutdown at contact time (Y/N) |
| `SiteLastRetrieveTime` | TEXT | Last data retrieval time |
| `SiteLastSendTime` | TEXT | Last data send time |
| `ComDeviceLastAttempt` | TEXT | Last communication attempt |
| `ComDeviceLastSuccess` | TEXT | Last successful communication |
| `ComDeviceFailureCount` | INTEGER | Consecutive failure count |
| `ScheduleLastSendTime` | TEXT | Last schedule send time |
| `WeatherLastContact` | TEXT | Last weather station contact |

---

### 4.9 `XA_HIST` — Historical ET Data (1,819 rows)

Monthly historical ET reference values by location.

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | **PK** |
| `XactHistCountry` | TEXT | Country |
| `XactHistState` | TEXT | State/Province |
| `XactHistCity` | TEXT | City |
| `XactHist01..12` | REAL | Monthly ET values (Jan-Dec) |

---

### 4.10 `XA_ET` — ET Reference Values (24 rows)

Yearly ET reference entries.

| Column | Type | Description |
|--------|------|-------------|
| `IndexNumber` | INTEGER | **PK** |
| `XactET01..12` | REAL | Monthly ET values (Jan-Dec) |

---

### 4.11 Error/Export Tables

| Table | Rows | Description |
|-------|------|-------------|
| `XA_LOG_ExportErrors` | 402,846 | Signal log export errors |
| `XA_WETHR_ExportErrors` | 9,352 | Weather log export errors |

---

### 4.12 Empty Log Tables

| Table | Rows | Description |
|-------|------|-------------|
| `XA_CLNDR` | 0 | Calendar data |
| `XA_MEMO` | 0 | Memo entries |
| `XA_WirelessDiagnosis` | 0 | Wireless diagnostic data |
| `XA_WirelessDiagnosis_TMP` | 0 | Temp wireless diagnostics |
| `XA_FLOZO_TMP` | 0 | Temp flow zone data |

---

## 5. Auxiliary Tables

### 5.1 Security Tables

| Table | Rows | Description |
|-------|------|-------------|
| `M_PWORD` | 0 | User passwords |
| `M_PWFREE` | 0 | Free password entries |

---

## 6. Data Pipeline

The data flows from the Access MDB through a multi-step pipeline:

```
┌──────────────────────┐
│  Maxicom2.mdb        │  (Access 2000 format, password-protected)
│  ~36 MB              │  Read via DAO.DBEngine.120 (win32com)
└──────────┬───────────┘
           │  mdb_integration.py
           ▼
┌──────────────────────┐
│  mdb_export/         │
│  ├── csv/            │  41 CSV files (one per table)
│  ├── maxicom_integrated.db  │  SQLite with all tables + views
│  ├── relationships.json     │  FK relationship metadata
│  ├── table_categories.json  │  Table grouping metadata
│  └── integration_report.txt │  Data summary report
└──────────┬───────────┘
           │  import_maxicom.py management command
           ▼
┌──────────────────────┐
│  Django SQLite DB    │  12 Django models (core_maxicom*)
│  (db.sqlite3)        │  with proper FK relationships
└──────────┬───────────┘
           │  /api/maxicom-dashboard API endpoint
           ▼
┌──────────────────────┐
│  Dashboard UI        │  Charts, tables, hierarchy view
│  (HTML/JS)           │
└──────────────────────┘
```

### Pipeline Scripts

| Script | Purpose |
|--------|---------|
| `mdb_integration.py` | Reads MDB → exports CSV + SQLite with integrated views |
| `import_maxicom.py` | Django management command: SQLite → Django ORM models |
| `views.py::maxicom_dashboard_api()` | Django API: ORM → JSON for dashboard |

---

## 7. Django Model Mapping

| MDB Table | Django Model | Key Fields Imported |
|-----------|-------------|-------------------|
| `SITE_CF` | `MaxicomSite` | name, site_number, et_current, water_pricing, rain_shutdown |
| `CTROL_CF` | `MaxicomController` | name, site (FK), link_number, link_channel, enabled |
| `STATN_CF` | `MaxicomStation` | name, site (FK), controller (FK), channel, precip_rate, flow_rate, cycle_time, soak_time, lockout |
| `SCHED_CF` | `MaxicomSchedule` | name, site (FK), nominal_et, water_budget_factor, flo_manage |
| `FLOZO_CF` | `MaxicomFlowZone` | name, site (FK), join_site |
| `WETHR_CF` | `MaxicomWeatherStation` | name, default_et, time_zone |
| `XA_WETHR` | `MaxicomWeatherLog` | weather_station (FK), timestamp, temperature, humidity, rainfall, et |
| `XA_EVENT` | `MaxicomEvent` | timestamp, source, flag, text |
| `XA_ETCheckBook` | `MaxicomETCheckbook` | site (FK), timestamp, soil_moisture, rainfall, et, irrigation |
| `XA_RuntimeProject` | `MaxicomRuntime` | station (FK), site (FK), timestamp, run_time |
| `XA_LOG` | `MaxicomSignalLog` | timestamp, controller_channel, signal_index, signal_value |
| `XA_FLOZO` | `MaxicomFlowReading` | flow_zone (FK), timestamp, value, multiplier |

---

## 8. SQLite Integrated Views

The `mdb_integration.py` script creates these SQL views for easier querying:

| View Name | Description | Key Join |
|-----------|-------------|----------|
| `v_site_summary` | Sites with controller/station/schedule counts | SITE_CF + subqueries |
| `v_station_overview` | Stations with site + controller names | STATN_CF → SITE_CF → CTROL_CF |
| `v_weather_readings` | Weather logs with station names | XA_WETHR → WETHR_CF |
| `v_events` | System events ordered by time | XA_EVENT |
| `v_et_checkbook` | ET balance with site names | XA_ETCheckBook → SITE_CF |
| `v_runtime` | Runtime with station/site names | XA_RuntimeProject → STATN_CF → SITE_CF |
| `v_flow_zone_readings` | Flow readings with zone names | XA_FLOZO → FLOZO_CF |
| `v_schedule_overview` | Schedules with site names | SCHED_CF → SITE_CF |
| `v_connection_overview` | Connections with site names | CNECT_CF → SITE_CF |
| `v_irrigation_hierarchy` | Full Site→Controller→Station hierarchy | SITE_CF → CTROL_CF → STATN_CF → CNECT_CF |

---

## Timestamp Format

All timestamps in the Maxicom2 database use a compact text format:

```
YYYYMMDDHHmmSS    (14 characters)
```

| Example | Interpretation |
|---------|---------------|
| `20260403090216` | 2026-04-03 09:02:16 |
| `20250303084944` | 2025-03-03 08:49:44 |
| `20260403080000` | 2026-04-03 08:00:00 |

Parsed in JavaScript as:
```javascript
ts.slice(0,4) + '-' + ts.slice(4,6) + '-' + ts.slice(6,8) + ' ' + ts.slice(8,10) + ':' + ts.slice(10,12)
```

---

## Field Type Mapping (DAO → SQLite)

| DAO Type Code | DAO Type | SQLite Type |
|---------------|----------|-------------|
| 1 | Boolean/YesNo | INTEGER |
| 2 | Byte | TEXT |
| 3 | Integer | INTEGER |
| 4 | Long | INTEGER |
| 5 | Currency | REAL |
| 6 | Single | REAL |
| 7 | Double | REAL |
| 8 | Date/Time | TEXT |
| 10 | Text | TEXT |
| 12 | Memo | TEXT |

---

*Document generated from code analysis of `mdb_integration.py`, `import_maxicom.py`, and `models.py`. Data counts from integration report dated 2026-04-08.*