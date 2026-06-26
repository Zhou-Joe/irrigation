"""
Import Maxicom2 irrigation data directly from Maxicom2.mdb into Django DB.

Replaces the obsolete import_maxicom.py (which read from a pre-exported SQLite and
silently mis-keyed sites 3/5/7 because it used IndexNumber where the MDB references
sites by SiteNumber).

KEY INSIGHT
-----------
The 22 existing Patch rows are keyed by code='CCU1'..'CCU45', where the number in the
code == the MDB SiteNumber. Every config + time-series table in the MDB, however,
references sites by IndexNumber (the SITE_CF primary key), NOT SiteNumber. The two
numbering schemes differ for most sites (e.g. CCU7/SiteNumber 7 -> IndexNumber 4).

So the importer:
  * Matches each CCU patch by parsing its SiteNumber from the code.
  * Stores IndexNumber (looked up from SITE_CF) as Patch.mdb_index — this is the value
    all *_CF.ControllerSiteNumber / XA_FLOZO.SiteID / etc. reference.
  * Builds site_map keyed by IndexNumber for FK resolution.

The importer:
  1. Reuses the existing 22 CCU patches (sets their mdb_index, never duplicates).
  2. Loads config tables (controllers, flow zones, weather stations, schedules, stations).
  3. Appends all time-series tables (weather, events, ET, runtime, signals, flow).

Usage:
    python manage.py import_maxicom_mdb                 # full import
    python manage.py import_maxicom_mdb --skip-large    # skip XA_FLOZO (4M) + XA_LOG (432K)
    python manage.py import_maxicom_mdb --clear         # wipe Maxicom tables first
    python manage.py import_maxicom_mdb --dry-run       # show plan, write nothing
"""

import os
import re
from datetime import datetime

from django.core.management.base import BaseCommand
from core.models import (
    Patch,
    MaxicomController, MaxicomSchedule,
    MaxicomFlowZone, MaxicomWeatherStation, MaxicomWeatherLog,
    MaxicomEvent, MaxicomFlowReading, MaxicomSignalLog,
    MaxicomETCheckbook, MaxicomRuntime,
)

DEFAULT_MDB = r"C:\Users\czhou7\PythonProjects\irrigation\Database\Maxicom2.mdb"
DEFAULT_PWD = "RLM6808"

CCU_CODE_RE = re.compile(r'^CCU(\d+)$', re.IGNORECASE)


class Command(BaseCommand):
    help = 'Import Maxicom2 irrigation data directly from Maxicom2.mdb into Django DB'

    def add_arguments(self, parser):
        parser.add_argument('--mdb', type=str, default=DEFAULT_MDB, help='Path to Maxicom2.mdb')
        parser.add_argument('--pwd', type=str, default=DEFAULT_PWD, help='MDB password')
        parser.add_argument('--skip-large', action='store_true',
                            help='Skip XA_FLOZO (4M rows) and XA_LOG (432K rows)')
        parser.add_argument('--clear', action='store_true',
                            help='Delete existing Maxicom data before import')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would happen, write nothing')

    def handle(self, *args, **options):
        mdb_path = options['mdb']
        mdb_pwd = options['pwd']
        skip_large = options['skip_large']
        clear = options['clear']
        dry_run = options['dry_run']

        if not os.path.exists(mdb_path):
            self.stderr.write(self.style.ERROR(f'MDB not found: {mdb_path}'))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be written'))

        self.stdout.write(f'Source MDB : {mdb_path}')
        start = datetime.now()

        # Open MDB via DAO (same engine as the sync agent)
        import win32com.client
        engine = win32com.client.Dispatch("DAO.DBEngine.120")
        self.db = engine.OpenDatabase(mdb_path, False, True, ";pwd=" + mdb_pwd)

        try:
            # Step 1: build the match map and wire up the 22 CCU patches
            self.stdout.write('\n=== Step 1: Match CCU patches to MDB sites ===')
            site_map, stats = self._match_ccu_patches(dry_run)
            for line in stats:
                self.stdout.write(line)
            # site_map: IndexNumber -> Patch (MDB config + time-series reference IndexNumber)

            if clear and not dry_run:
                self.stdout.write('\n=== Clearing existing Maxicom data (reverse FK order) ===')
                self._clear_all()

            # Step 2: config tables
            self.stdout.write('\n=== Step 2: Config tables ===')
            self._import_weather_stations(dry_run)
            self._import_controllers(site_map, dry_run)
            self._import_flow_zones(site_map, dry_run)
            self._import_schedules(site_map, dry_run)
            self._import_stations(site_map, dry_run)

            # Step 3: time-series tables
            self.stdout.write('\n=== Step 3: Time-series tables ===')
            self._import_weather_logs(dry_run)
            self._import_events(dry_run)
            self._import_et_checkbook(site_map, dry_run)
            self._import_runtime(site_map, dry_run)
            if not skip_large:
                self._import_signal_logs(dry_run)
                self._import_flow_readings(dry_run)
            else:
                self.stdout.write(self.style.WARNING(
                    '  Skipping XA_LOG + XA_FLOZO (--skip-large)'))

        finally:
            self.db.Close()

        elapsed = (datetime.now() - start).total_seconds()
        self.stdout.write(self.style.SUCCESS(f'\n=== Import complete in {elapsed:.1f}s ==='))

    # ─── MDB helpers ──────────────────────────────────────────────────

    def _q(self, sql):
        """Run a SELECT and return list of dict rows."""
        rs = self.db.OpenRecordset(sql)
        rows = []
        try:
            cols = [rs.Fields.Item(i).Name for i in range(rs.Fields.Count)]
            while not rs.EOF:
                rows.append({c: rs.Fields.Item(c).Value for c in cols})
                rs.MoveNext()
        finally:
            rs.Close()
        return rows

    def _q_count(self, table):
        rs = self.db.OpenRecordset(f"SELECT COUNT(*) AS n FROM [{table}]")
        n = rs.Fields.Item("n").Value
        rs.Close()
        return n

    # ─── Step 1: match the 22 CCU patches ─────────────────────────────

    def _match_ccu_patches(self, dry_run):
        # Load SITE_CF active rows. Build SiteNumber -> row so we can match CCU codes,
        # and IndexNumber -> row so we can populate mdb_index (the value all tables FK on).
        site_rows = self._q(
            "SELECT IndexNumber, SiteNumber, IndexName, SiteTimeZone, "
            "SiteWaterPricing, SiteCCUVersion, SiteWaterETCurrent, SiteWaterETDefault, "
            "SiteWaterETMinimum, SiteWaterETMaximum, SiteWaterCropCoefficient, "
            "SiteRainShutDownApplies, SiteContactTelephone, DateOpen "
            "FROM SITE_CF WHERE DateClose IS NULL")
        site_by_num = {r['SiteNumber']: r for r in site_rows}  # SiteNumber -> row

        ccu_patches = list(Patch.objects.filter(code__iregex=r'^CCU\d+$'))
        stats = [f'  Found {len(ccu_patches)} existing CCU patches',
                 f'  MDB active sites: {len(site_by_num)}']

        site_map = {}       # IndexNumber -> Patch (the FK value every table references)
        matched = 0
        for p in ccu_patches:
            m = CCU_CODE_RE.match(p.code)
            if not m:
                continue
            site_num = int(m.group(1))
            row = site_by_num.get(site_num)
            if not row:
                stats.append(f'  {p.code} ({p.name}): no MDB site #{site_num} (skipped)')
                continue
            idx = row['IndexNumber']  # IndexNumber != site_num for most sites; this is expected
            matched += 1
            site_map[idx] = p
            stats.append(
                f'  {p.code:<6} ({p.name:<10}) SiteNumber {site_num} -> mdb_index {idx}')

            if not dry_run:
                p.mdb_index = idx
                p.site_number = site_num
                p.time_zone = (row.get('SiteTimeZone') or 'China') or 'China'
                p.water_pricing = row.get('SiteWaterPricing')
                p.ccu_version = (row.get('SiteCCUVersion') or '') or ''
                p.et_current = row.get('SiteWaterETCurrent')
                p.et_default = row.get('SiteWaterETDefault')
                p.et_minimum = row.get('SiteWaterETMinimum')
                p.et_maximum = row.get('SiteWaterETMaximum')
                p.crop_coefficient = row.get('SiteWaterCropCoefficient')
                p.rain_shutdown = (row.get('SiteRainShutDownApplies') == 'Y')
                p.telephone = (row.get('SiteContactTelephone') or '') or ''
                p.date_open = (row.get('DateOpen') or '') or ''
                p.save()

        stats.append(f'  Matched {matched}/{len(ccu_patches)} patches to IndexNumber keys')
        stats.append('  Note: SiteNumber 99 (MC Bench Test) has no CCU patch — correctly excluded')
        return site_map, stats

    # ─── Step 2: config tables ────────────────────────────────────────

    def _import_weather_stations(self, dry_run):
        rows = self._q("SELECT * FROM WETHR_CF")
        created = updated = errors = 0
        for r in rows:
            if dry_run:
                created += 1
                continue
            try:
                _, c = MaxicomWeatherStation.objects.update_or_create(
                    mdb_index=r['IndexNumber'],
                    defaults={
                        'name': (r.get('IndexName') or '').strip(),
                        'default_et': r.get('WeatherDefaultET'),
                        'time_zone': (r.get('WeatherTimeZone') or 'China') or 'China',
                    })
                created += 1 if c else 0
                updated += 0 if c else 1
            except Exception:
                errors += 1
        self.stdout.write(f'  Weather stations: {len(rows)} ({created} new, {updated} updated, {errors} errors)')

    def _import_controllers(self, site_map, dry_run):
        rows = self._q("SELECT * FROM CTROL_CF")
        created = updated = errors = skipped = 0
        for r in rows:
            site = site_map.get(r.get('ControllerSiteNumber'))
            if not site:
                skipped += 1
                continue
            if dry_run:
                created += 1
                continue
            try:
                _, c = MaxicomController.objects.update_or_create(
                    mdb_index=r['IndexNumber'],
                    defaults={
                        'site': site,
                        'name': (r.get('IndexName') or '').strip(),
                        'controller_type': '',
                        'site_number': r.get('ControllerSiteNumber', 0) or 0,
                        'link_number': r.get('ControllerLinkNumber', 0) or 0,
                        'link_channel': r.get('ControllerLinkChannel', 0) or 0,
                        'enabled': (r.get('ControllerEnabled') == 'Y'),
                        'date_open': (r.get('DateOpen') or '') or '',
                    })
                created += 1 if c else 0
                updated += 0 if c else 1
            except Exception:
                errors += 1
        self.stdout.write(f'  Controllers: {len(rows)} ({created} new, {updated} updated, '
                          f'{errors} errors, {skipped} no-site)')

    def _import_flow_zones(self, site_map, dry_run):
        rows = self._q("SELECT * FROM FLOZO_CF")
        created = updated = errors = skipped = 0
        for r in rows:
            site = site_map.get(r.get('FlowZoneSiteNumber'))
            if not site:
                skipped += 1
                continue
            if dry_run:
                created += 1
                continue
            try:
                _, c = MaxicomFlowZone.objects.update_or_create(
                    mdb_index=r['IndexNumber'],
                    defaults={
                        'site': site,
                        'name': (r.get('IndexName') or '').strip(),
                        'join_site': (r.get('FlowZoneJoinSite') == 'Y'),
                    })
                created += 1 if c else 0
                updated += 0 if c else 1
            except Exception:
                errors += 1
        self.stdout.write(f'  Flow zones: {len(rows)} ({created} new, {updated} updated, '
                          f'{errors} errors, {skipped} no-site)')

    def _import_schedules(self, site_map, dry_run):
        rows = self._q("SELECT * FROM SCHED_CF")
        batch = []
        skipped = 0
        for r in rows:
            site = site_map.get(r.get('ScheduleSiteNumber'))
            if not site:
                skipped += 1
                continue
            if dry_run:
                continue
            batch.append(MaxicomSchedule(
                site=site,
                mdb_index=r['IndexNumber'],
                name=(r.get('IndexName') or '').strip(),
                nominal_et=r.get('ScheduleNominalET'),
                water_budget_factor=r.get('ScheduleWaterBudgetFactor'),
                flo_manage=(r.get('ScheduleFloManage') == 'Y'),
                send_automatic=(r.get('ScheduleSendAutomatic') == 'Y'),
                send_protected=(r.get('ScheduleSendProtected') == 'Y'),
                instruction_file=(r.get('ScheduleInstructionFile') or '') or '',
                sensitized_et=(r.get('ScheduleSensitizedET') == 'Y'),
                date_open=(r.get('DateOpen') or '') or '',
            ))
            if len(batch) >= 500:
                MaxicomSchedule.objects.bulk_create(batch, batch_size=500)
                batch = []
        if batch and not dry_run:
            MaxicomSchedule.objects.bulk_create(batch, batch_size=500)
        self.stdout.write(f'  Schedules: {len(rows)} ({skipped} no-site)')

    def _import_stations(self, site_map, dry_run):
        rows = self._q("SELECT * FROM STATN_CF")
        # Only active stations; dedup by IndexNumber
        seen = set()
        batch = []
        skipped = 0
        for r in rows:
            idx = r['IndexNumber']
            if idx in seen:
                continue
            seen.add(idx)
            site = site_map.get(r.get('StationSiteNumber'))
            if not site:
                skipped += 1
                continue
            if dry_run:
                continue
            batch.append(Patch(
                parent=site,
                site_number=r.get('StationSiteNumber'),
                mdb_index=idx,
                name=(r.get('IndexName') or '').strip(),
                code=f'station-{idx}',
                controller_number=r.get('StationControllerNumber'),
                controller_channel=r.get('StationControllerChannel', 0) or 0,
                precip_rate=r.get('StationPrecipFactor'),
                flow_rate=r.get('StationFlowFactor'),
                microclimate_factor=r.get('StationMicroclimeFactor'),
                cycle_time=r.get('StationCycleTime'),
                soak_time=r.get('StationSoakTime'),
                description=(r.get('StationMemo') or '') or '',
                lockout=bool(r.get('Lockout', 0)),
                flow_manager_priority=r.get('FloManagerPriorityLevel'),
                date_open=(r.get('DateOpen') or '') or '',
            ))
            if len(batch) >= 1000:
                Patch.objects.bulk_create(batch, batch_size=1000)
                batch = []
        if batch and not dry_run:
            Patch.objects.bulk_create(batch, batch_size=1000)
        self.stdout.write(f'  Stations: {len(seen)} unique ({skipped} no-site)')

    # ─── Step 3: time-series tables ───────────────────────────────────

    def _import_weather_logs(self, dry_run):
        # XactIndex -> weather station mdb_index
        ws_map = {ws.mdb_index: ws for ws in MaxicomWeatherStation.objects.all()}
        total = self._q_count("XA_WETHR")
        self.stdout.write(f'  Weather logs: {total:,} rows in MDB, reading...')
        rs = self.db.OpenRecordset(
            "SELECT XactStamp, XactIndex, Temperature, MaxTemp, MinTemp, SolarRadiation, "
            "RainFall, Humidity, WindRun, ET FROM XA_WETHR ORDER BY XactStamp")
        batch = []
        count = inserted = skipped = 0
        try:
            while not rs.EOF:
                r = {f.Name: f.Value for f in (rs.Fields.Item(i) for i in range(rs.Fields.Count))}
                ws = ws_map.get(r.get('XactIndex'))
                if ws:
                    batch.append(MaxicomWeatherLog(
                        weather_station=ws,
                        timestamp=(r.get('XactStamp') or '') or '',
                        temperature=r.get('Temperature'),
                        max_temp=r.get('MaxTemp'),
                        min_temp=r.get('MinTemp'),
                        solar_radiation=r.get('SolarRadiation'),
                        rainfall=r.get('RainFall'),
                        humidity=r.get('Humidity'),
                        wind_run=r.get('WindRun'),
                        et=r.get('ET'),
                    ))
                else:
                    skipped += 1
                count += 1
                if len(batch) >= 1000:
                    if not dry_run:
                        MaxicomWeatherLog.objects.bulk_create(batch, batch_size=1000,
                                                              ignore_conflicts=True)
                    inserted += len(batch)
                    batch = []
                    if count % 20000 == 0:
                        self.stdout.write(f'    {count:,}/{total:,} weather logs...')
                rs.MoveNext()
            if batch:
                if not dry_run:
                    MaxicomWeatherLog.objects.bulk_create(batch, batch_size=1000,
                                                          ignore_conflicts=True)
                inserted += len(batch)
        finally:
            rs.Close()
        self.stdout.write(f'  Weather logs: {inserted:,} inserted, {skipped:,} skipped (no station)')

    def _import_events(self, dry_run):
        total = self._q_count("XA_EVENT")
        rs = self.db.OpenRecordset(
            "SELECT XactStamp, XactIndex, EventSource, EventNumber, EventFlag, "
            "EventTextQualifier FROM XA_EVENT ORDER BY XactStamp")
        batch = []
        count = 0
        try:
            while not rs.EOF:
                r = {f.Name: f.Value for f in (rs.Fields.Item(i) for i in range(rs.Fields.Count))}
                batch.append(MaxicomEvent(
                    timestamp=(r.get('XactStamp') or '') or '',
                    source=(r.get('EventSource') or '') or '',
                    index=r.get('XactIndex'),
                    event_number=r.get('EventNumber'),
                    flag=(r.get('EventFlag') or '') or '',
                    text=(r.get('EventTextQualifier') or '') or '',
                ))
                count += 1
                if len(batch) >= 500:
                    if not dry_run:
                        MaxicomEvent.objects.bulk_create(batch, batch_size=500,
                                                         ignore_conflicts=True)
                    batch = []
                rs.MoveNext()
            if batch:
                if not dry_run:
                    MaxicomEvent.objects.bulk_create(batch, batch_size=500,
                                                     ignore_conflicts=True)
        finally:
            rs.Close()
        self.stdout.write(f'  Events: {count:,} inserted')

    def _import_et_checkbook(self, site_map, dry_run):
        total = self._q_count("XA_ETCheckBook")
        rs = self.db.OpenRecordset(
            "SELECT XactStamp, SiteID, SoilMoisture, Rainfall, ET, Irrigation, "
            "SoilMoistureHoldingCapacity, SoilRefillPercentage FROM XA_ETCheckBook")
        batch = []
        count = inserted = skipped = 0
        try:
            while not rs.EOF:
                r = {f.Name: f.Value for f in (rs.Fields.Item(i) for i in range(rs.Fields.Count))}
                site = site_map.get(r.get('SiteID'))
                if site:
                    batch.append(MaxicomETCheckbook(
                        timestamp=(r.get('XactStamp') or '') or '',
                        site=site,
                        soil_moisture=r.get('SoilMoisture'),
                        rainfall=r.get('Rainfall'),
                        et=r.get('ET'),
                        irrigation=r.get('Irrigation'),
                        soil_moisture_capacity=r.get('SoilMoistureHoldingCapacity'),
                        soil_refill_pct=r.get('SoilRefillPercentage'),
                    ))
                else:
                    skipped += 1
                count += 1
                if len(batch) >= 1000:
                    if not dry_run:
                        MaxicomETCheckbook.objects.bulk_create(batch, batch_size=1000,
                                                               ignore_conflicts=True)
                    inserted += len(batch)
                    batch = []
                    if count % 9000 == 0:
                        self.stdout.write(f'    {count}/{total} ET entries...')
                rs.MoveNext()
            if batch:
                if not dry_run:
                    MaxicomETCheckbook.objects.bulk_create(batch, batch_size=1000,
                                                           ignore_conflicts=True)
                inserted += len(batch)
        finally:
            rs.Close()
        self.stdout.write(f'  ET checkbook: {inserted:,} inserted, {skipped:,} skipped (no site)')

    def _import_runtime(self, site_map, dry_run):
        total = self._q_count("XA_RuntimeProject")
        rs = self.db.OpenRecordset(
            "SELECT TimeStamps, SiteID, StationID, RunTime FROM XA_RuntimeProject")
        # station lookup by mdb_index
        stn_map = {p.mdb_index: p for p in Patch.objects.filter(parent__isnull=False)}
        batch = []
        count = inserted = skipped = 0
        try:
            while not rs.EOF:
                r = {f.Name: f.Value for f in (rs.Fields.Item(i) for i in range(rs.Fields.Count))}
                site = site_map.get(r.get('SiteID'))
                if site:
                    stn = stn_map.get(r.get('StationID'))
                    batch.append(MaxicomRuntime(
                        timestamp=(r.get('TimeStamps') or '') or '',
                        station=stn,
                        site=site,
                        station_id_raw=r.get('StationID', 0) or 0,
                        run_time=r.get('RunTime'),
                    ))
                else:
                    skipped += 1
                count += 1
                if len(batch) >= 1000:
                    if not dry_run:
                        MaxicomRuntime.objects.bulk_create(batch, batch_size=1000,
                                                           ignore_conflicts=True)
                    inserted += len(batch)
                    batch = []
                rs.MoveNext()
            if batch:
                if not dry_run:
                    MaxicomRuntime.objects.bulk_create(batch, batch_size=1000,
                                                       ignore_conflicts=True)
                inserted += len(batch)
        finally:
            rs.Close()
        self.stdout.write(f'  Runtime: {inserted:,} inserted, {skipped:,} skipped (no site)')

    def _import_signal_logs(self, dry_run):
        total = self._q_count("XA_LOG")
        self.stdout.write(f'  Signal logs: {total:,} rows in MDB, reading...')
        rs = self.db.OpenRecordset(
            "SELECT XactStamp, XactIndex, ControllerChannel, SignalIndex, "
            "SignalTable, SignalType, SignalValue, SignalMultiplier FROM XA_LOG")
        batch = []
        count = 0
        try:
            while not rs.EOF:
                r = {f.Name: f.Value for f in (rs.Fields.Item(i) for i in range(rs.Fields.Count))}
                batch.append(MaxicomSignalLog(
                    timestamp=(r.get('XactStamp') or '') or '',
                    index=r.get('XactIndex'),
                    controller_channel=r.get('ControllerChannel'),
                    signal_index=r.get('SignalIndex'),
                    signal_table=(r.get('SignalTable') or '') or '',
                    signal_type=(r.get('SignalType') or '') or '',
                    signal_value=r.get('SignalValue'),
                    signal_multiplier=r.get('SignalMultiplier'),
                ))
                count += 1
                if len(batch) >= 5000:
                    if not dry_run:
                        MaxicomSignalLog.objects.bulk_create(batch, batch_size=5000,
                                                             ignore_conflicts=True)
                    batch = []
                    if count % 50000 == 0:
                        self.stdout.write(f'    {count:,}/{total:,} signal logs...')
                rs.MoveNext()
            if batch:
                if not dry_run:
                    MaxicomSignalLog.objects.bulk_create(batch, batch_size=5000,
                                                         ignore_conflicts=True)
        finally:
            rs.Close()
        self.stdout.write(f'  Signal logs: {count:,} inserted')

    def _import_flow_readings(self, dry_run):
        total = self._q_count("XA_FLOZO")
        self.stdout.write(f'  Flow readings: {total:,} rows in MDB, reading...')
        # flow_zone lookup by mdb_index
        fz_map = {fz.mdb_index: fz for fz in MaxicomFlowZone.objects.all()}
        rs = self.db.OpenRecordset(
            "SELECT XactStamp, XactIndex, FlowZoneValue, FlowZoneMultiplier, SiteID "
            "FROM XA_FLOZO ORDER BY XactStamp")
        batch = []
        count = inserted = skipped = 0
        try:
            while not rs.EOF:
                r = {f.Name: f.Value for f in (rs.Fields.Item(i) for i in range(rs.Fields.Count))}
                fz = fz_map.get(r.get('XactIndex'))
                if fz:
                    batch.append(MaxicomFlowReading(
                        flow_zone=fz,
                        timestamp=(r.get('XactStamp') or '') or '',
                        value=r.get('FlowZoneValue'),
                        multiplier=r.get('FlowZoneMultiplier'),
                        site_id=r.get('SiteID'),
                    ))
                else:
                    skipped += 1
                count += 1
                if len(batch) >= 5000:
                    if not dry_run:
                        MaxicomFlowReading.objects.bulk_create(batch, batch_size=5000,
                                                               ignore_conflicts=True)
                    inserted += len(batch)
                    batch = []
                    if count % 200000 == 0:
                        self.stdout.write(f'    {count:,}/{total:,} flow readings...')
                rs.MoveNext()
            if batch:
                if not dry_run:
                    MaxicomFlowReading.objects.bulk_create(batch, batch_size=5000,
                                                           ignore_conflicts=True)
                inserted += len(batch)
        finally:
            rs.Close()
        self.stdout.write(f'  Flow readings: {inserted:,} inserted, {skipped:,} skipped (no flow zone)')

    # ─── Clear ────────────────────────────────────────────────────────

    def _clear_all(self):
        """Delete all Maxicom data in reverse FK order (keeps the 22 CCU patches)."""
        MaxicomRuntime.objects.all().delete()
        MaxicomETCheckbook.objects.all().delete()
        MaxicomSignalLog.objects.all().delete()
        MaxicomFlowReading.objects.all().delete()
        MaxicomEvent.objects.all().delete()
        MaxicomWeatherLog.objects.all().delete()
        MaxicomSchedule.objects.all().delete()
        # Station-type patches (children); CCU sites have parent=NULL so are kept
        Patch.objects.filter(parent__isnull=False).delete()
        MaxicomController.objects.all().delete()
        MaxicomFlowZone.objects.all().delete()
        MaxicomWeatherStation.objects.all().delete()
        self.stdout.write('  Cleared Maxicom tables (22 CCU site patches preserved)')
