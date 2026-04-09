# Maxicom2 → Django Data Sync Plan

## Context

- **Win7 (Old PC)**: Runs Rain Bird Maxicom2 software, continuously writes to `Maxicom2.mdb`
- **Win11 (New PC)**: Hosts Django irrigation dashboard project
- **No existing network** between the two machines
- **Goal**: Frequently pull latest data from the Access database into Django

---

## Recommended Architecture: Agent-Based Sync over Direct Ethernet

```
┌─────────────────────┐         Ethernet          ┌─────────────────────┐
│  Win7 (Old PC)      │ ◄══════════════════════► │  Win11 (Django PC)  │
│                     │    192.168.1.10           │    192.168.1.20     │
│  Maxicom2 Software  │                          │                     │
│  Maxicom2.mdb       │   HTTP POST (JSON)       │  Django Server      │
│  MaxicomSync.exe ───┼─────────────────────────►│  /api/sync/receive  │
│  (PyQt5 GUI, tray)  │                          │  → Django ORM DB    │
└─────────────────────┘                          └─────────────────────┘
```

### Why This Approach

1. **No MDB file locking issues** — Agent runs on same machine as Maxicom2, reads via DAO in shared/read-only mode
2. **Incremental sync** — Only sends new/changed records based on timestamps
3. **Small payload** — JSON over HTTP, no full file copies needed
4. **Configurable interval** — Every 1–15 minutes as needed
5. **Resilient** — Agent retries on failure, Django API is idempotent
6. **Non-technical friendly** — PyQt5 GUI with traffic-light status, visible to irrigation staff

### Why File Locking Is Not an Issue

When Maxicom2 opens `Maxicom2.mdb`, it creates a `.ldb` lock file. But Access/Jet databases are designed for **multi-user shared access** — multiple processes can read simultaneously.

```python
db = db_engine.OpenDatabase(mdb_path, Exclusive=False, ReadOnly=True, ";pwd=RLM6808")
#                                   ↑ Not exclusive    ↑ Read-only
```

- `Exclusive=False` → Opens in **shared mode**, coexists with Maxicom2's read-write session
- `ReadOnly=True` → No write intent, so no lock conflicts

This works reliably **on the same machine** because the Jet/ACE engine handles local shared access natively.

**Why remote reading over network is risky**: DAO over SMB requires creating `.ldb` files across the network, which can cause stale locks and MDB corruption. The agent approach decouples file access (local) from data transfer (HTTP over network):

```
Win7 (local):                          Win11 (network):
Maxicom2 writes ──┐                    
                   ├──→ Maxicom2.mdb   ← no network access to file
Agent reads ──────┘        │
                    Extract JSON
                         │
                    HTTP POST ──────────→ Django API
                    (stateless,          (just receives data,
                     no file locks        no MDB involvement)
                     during transfer)
```

---

## Alternative Options Considered

| Option | Pros | Cons |
|--------|------|------|
| **A. SMB Share + Remote Read** | No agent needed | DAO over network may have locking issues; Win7 SMB can be flaky |
| **B. VSS Snapshot + Copy** | No Python on Win7 needed | VSS setup is complex; may not work reliably on old Win7 |
| **C. USB Manual Copy** | Simplest setup | Not automated, requires manual intervention |
| **D. Shared Folder + Polling** | Easy to set up | File locking conflicts with Maxicom2 software |
| **E. tkinter GUI** | Built-in Python | Ugly, looks outdated on Win7 |
| **✅ PyQt5 GUI EXE** | Professional look, no install needed | ~50MB EXE size |

---

## Implementation Plan

### Step 1: Physical Network Setup

Connect the two machines with a direct Ethernet cable (or through a small switch).

**On Win7 (Old PC):**
```
IP: 192.168.1.10
Subnet: 255.255.255.0
Gateway: (leave blank)
```

**On Win11 (Django PC):**
```
IP: 192.168.1.20
Subnet: 255.255.255.0
Gateway: (leave blank)
```

Verify connectivity: `ping 192.168.1.10` from Win11 and vice versa.

---

### Step 2: Django Sync API Endpoint

Create a new API endpoint on the Django server:

**URL**: `POST /api/sync/receive`
**Auth**: API key in header (`X-Sync-Key: <secret>`)
**Content-Type**: `application/json`

**Request body structure**:
```json
{
  "sync_timestamp": "20260408153000",
  "config": {
    "sites": [...],
    "controllers": [...],
    "stations": [...],
    "schedules": [...],
    "flow_zones": [...],
    "weather_stations": [...]
  },
  "time_series": {
    "weather_logs": [...],
    "events": [...],
    "et_checkbook": [...],
    "runtime": [...],
    "signal_logs": [...],
    "flow_readings": [...]
  },
  "last_event_timestamp": "20260408152500",
  "last_weather_timestamp": "20260408150000"
}
```

**Sync strategy**:
- **Config tables** (sites, controllers, stations, schedules, flow zones, weather stations): Full replace (upsert by `mdb_index`)
- **Time-series tables** (weather logs, events, flow readings, signal logs, runtime, ET checkbook): Append-only, using timestamp + index as dedup key

---

### Step 3: Sync Agent — PyQt5 GUI EXE (Win7)

A **PyQt5 desktop application** (`sync_agent.py`) bundled as a standalone EXE via PyInstaller.

**Why a GUI instead of cron/Task Scheduler**:
- Irrigation staff are non-technical — a visible GUI shows sync health at a glance
- Color-coded status (🟢/🔴) makes problems immediately obvious
- System tray icon with balloon notifications on errors
- Manual "Sync Now" button for on-demand sync
- No need to train staff on Task Scheduler or log files

**GUI Layout**:
```
┌─────────────────────────────────────────────────┐
│  ● Maxicom2 Sync Agent                    — □ ✕ │
├─────────────────────────────────────────────────┤
│                                                 │
│  ● Connected  Server: 192.168.1.20:8888        │
│                                                 │
│  Last Sync: 2026-04-08 20:45:00  ✓ Success     │
│  Next Sync: 2026-04-08 20:50:00                │
│                                                 │
│  Records Synced This Session:                   │
│    Sites: 45  Stations: 180  Weather: 12       │
│    Events: 5   Flow: 1,200                     │
│                                                 │
│  ┌─ Sync Log ────────────────────────────────┐  │
│  │ 20:45:00  ✓ Synced 1,432 records          │  │
│  │ 20:40:00  ✓ Synced 89 records             │  │
│  │ 20:35:00  ✓ Synced 156 records            │  │
│  │ 20:30:00  ⚠ Warning - 0 new records       │  │
│  │ 20:25:00  ✓ Synced 2,103 records          │  │
│  │ 20:20:00  ✗ ERROR: Connection failed       │  │
│  │ 20:15:00  ✓ Synced 45 records             │  │
│  └────────────────────────────────────────────┘  │
│                                                 │
│  [ ▶ Sync Now ]   [ ⚙ Settings ]               │
└─────────────────────────────────────────────────┘
```

**GUI Features**:
- Dark-themed PyQt5 window with connection status, last/next sync time, record counts
- Scrolling sync log with ✓/⚠/✗ indicators
- System tray minimize (runs in background)
- Auto-start with Windows (via Startup folder or registry)
- Error popup alerts with sound
- Settings dialog (server URL, API key, sync interval, MDB path)

**Dependencies on Win7**:
- **None for end user** — bundled as single `MaxicomSync.exe` via PyInstaller
- Build environment needs: Python 3.8 (last official Win7 support), pywin32, PyQt5

**Agent logic** (runs on a QTimer, e.g., every 5 minutes):
```
1. Load last_sync.json → get last_timestamp
2. Open MDB via DAO.DBEngine.120 (read-only, shared mode)
3. Read config tables → always send full (small data)
4. Read time-series tables → filter by XactStamp > last_timestamp
5. POST JSON to Django /api/sync/receive
6. On 200 OK → update last_sync.json, show ✓ in log
7. On error → show ✗ in log, system tray balloon notification
```

**Build command**:
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=sync.ico sync_agent.py
# Output: dist/MaxicomSync.exe  (single file, ~50MB)
```

---

### Step 4: Auto-Start Configuration

The EXE auto-starts with Windows via either:
- **Startup folder**: Place shortcut in `shell:startup`
- **Registry**: Add to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`

No Task Scheduler needed — the app runs continuously with its own internal QTimer.

---

### Step 5: Sync Status Monitoring (Django Dashboard)

Add to Django dashboard:
- Last sync timestamp
- Record counts per table
- Sync health status (green/red based on freshness)
- Error log viewer

---

### Step 6: Deployment Checklist

**Win7 (Old PC)**:
- [ ] Copy `MaxicomSync.exe` to `C:\MaxicomSync\`
- [ ] Double-click to launch — verify GUI appears and connection is green
- [ ] Configure static IP: 192.168.1.10
- [ ] Add shortcut to Startup folder for auto-start
- [ ] Test: Click "Sync Now" → verify ✓ appears in log

**Win11 (Django PC)**:
- [ ] Configure static IP: 192.168.1.20
- [ ] Deploy Django with `ALLOWED_HOSTS` including 192.168.1.20
- [ ] Run migrations for sync tracking models
- [ ] Set `SYNC_API_KEY` in environment variables
- [ ] Verify endpoint: `curl http://192.168.1.20:8888/api/sync/receive`

---

## Files to Create

| File | Location | Purpose |
|------|----------|---------|
| `sync_agent.py` | `sync_agent/` | PyQt5 GUI agent for Win7 |
| `sync_agent.spec` | `sync_agent/` | PyInstaller build spec |
| `sync_views.py` | `internal_server/core/` | Django sync API views |
| `last_sync.json` | Agent directory on Win7 | Tracks last sync timestamp |
| `setup_guide.md` | `docs/` | Deployment instructions |

---

## Data Integrity & Dedup Strategy

### Two Categories, Two Strategies

#### Strategy 1: Config Tables — Full Replace (Upsert)

**Tables**: SITE_CF, CTROL_CF, STATN_CF, SCHED_CF, FLOZO_CF, WETHR_CF

These have unique `IndexNumber` (stored as `mdb_index` in Django) and are small (~5,000 total rows combined).

- Agent sends **all** active config records every sync cycle
- Django uses `update_or_create(mdb_index=...)` for each record:
  - If `mdb_index` exists → **update** with latest values
  - If `mdb_index` doesn't exist → **create** new record
- Closed/deleted records are identified by `DateClose` field
- **No duplicates possible** — `mdb_index` has a **unique constraint** in Django

#### Strategy 2: Time-Series Tables — Timestamp Cursor (Append)

**Tables**: XA_WETHR, XA_EVENT, XA_FLOZO, XA_LOG, XA_RuntimeProject, XA_ETCheckBook

These are append-only log data (no old records are ever modified by Maxicom2).

**Watermark approach** — Agent stores a local cursor file:

```json
// last_sync.json (on Win7)
{
  "last_weather_timestamp": "20260408150000",
  "last_event_timestamp": "20260408152500",
  "last_flow_timestamp": "20260408153000",
  "last_signal_timestamp": "20260408152500",
  "last_runtime_timestamp": "20260408150000",
  "last_etcheckbook_timestamp": "20260408150000"
}
```

**Each sync cycle**:
```
1. Agent reads last_sync.json → gets last timestamps
2. Queries MDB: WHERE XactStamp > '20260408150000'
3. Sends only new records to Django
4. Django uses get_or_create(dedup_key) to prevent edge-case duplicates
5. On success → agent updates last_sync.json with max timestamp received
```

### Guarantees

- ✅ **No missing data**: Query uses `>` (strictly greater than), and `last_sync.json` is only updated after Django confirms success
- ✅ **No duplicates**: Django has unique constraints on dedup keys, and uses `get_or_create` or `bulk_create(ignore_conflicts=True)`
- ✅ **Crash-safe**: If agent crashes mid-sync, `last_sync.json` is NOT updated → next run re-fetches the same window (Django's dedup safely ignores re-inserted records)

### Edge Case: Late-Committed Records

If Maxicom2 writes a record at `T=95` that wasn't fully committed when the agent queried at `T=100`:

```
Sync 1 at 10:00 → reads up to timestamp 09:55 → saves watermark 09:55
   ... but a record at 09:53 was being written during the query
Sync 2 at 10:05 → reads > 09:55 → might miss that 09:53 record
```

**Solution**: Use a 2-minute overlap buffer:

```python
# Subtract 2 minutes from watermark to catch late-committed records
query_timestamp = last_sync - 20000  # 2 minutes in MMSS format
```

Django's dedup (`get_or_create` or `ignore_conflicts`) safely handles the re-inserted overlap records.

### Dedup Key Summary

| Data Type | Strategy | Django Dedup Key | Miss Risk | Duplicate Risk |
|-----------|----------|-----------------|-----------|----------------|
| Config (sites, stations, etc.) | Full upsert | `mdb_index` (unique) | None | None (upsert) |
| Weather logs | Timestamp cursor | `(timestamp, weather_station)` unique | None (overlap buffer) | None (dedup) |
| Events | Timestamp cursor | `(timestamp, source, index)` unique | None | None (dedup) |
| Flow readings | Timestamp cursor | `(timestamp, flow_zone)` unique | None | None (dedup) |
| Signal logs | Timestamp cursor | `(timestamp, index, channel)` unique | None | None (dedup) |
| Runtime | Timestamp cursor | `(timestamp, station, site)` unique | None | None (dedup) |
| ET Checkbook | Timestamp cursor | `(timestamp, site)` unique | None | None (dedup) |

---

## Security Considerations

- API key authentication for sync endpoint
- Django `ALLOWED_HOSTS` restricted to known IPs
- Agent only has read access to MDB (no writes)
- No exposure to external network (direct Ethernet only)

---

## Open Questions

1. **Sync interval**: How fresh does data need to be? (5 min recommended for weather/events; config changes are rare)
2. **Python on Win7**: Can Python be installed, or should we use a portable/embedded distribution?
3. **Bidirectional sync**: Do you need to send irrigation commands back to Maxicom2, or is read-only sufficient?
4. **Data retention**: Should the Django DB archive historical data even after Maxicom2 purges it?

---

*Plan created: 2026-04-08 · Updated with PyQt5 GUI approach*