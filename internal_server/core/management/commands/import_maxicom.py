"""Import Maxicom2 data from integrated SQLite into Django database."""

import sqlite3
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from core.models import (
    MaxicomSite, MaxicomController, MaxicomStation, MaxicomSchedule,
    MaxicomFlowZone, MaxicomWeatherStation, MaxicomWeatherLog,
    MaxicomEvent, MaxicomFlowReading, MaxicomSignalLog,
    MaxicomETCheckbook, MaxicomRuntime,
)

# Default path: project_root/mdb_export/maxicom_integrated.db
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..'))
SQLITE_PATH = os.path.join(_PROJECT_ROOT, 'mdb_export', 'maxicom_integrated.db')


class Command(BaseCommand):
    help = 'Import Maxicom2 irrigation data from integrated SQLite into Django database'

    def add_arguments(self, parser):
        parser.add_argument('--db', type=str, default=None, help='Path to maxicom_integrated.db')
        parser.add_argument('--skip-large', action='store_true', help='Skip large tables (XA_FLOZO, XA_LOG, XA_LOG_ExportErrors)')
        parser.add_argument('--flow-limit', type=int, default=0, help='Limit flow readings per zone (0=all)')

    def handle(self, *args, **options):
        db_path = options['db'] or SQLITE_PATH
        skip_large = options['skip_large']
        flow_limit = options['flow_limit']

        if not os.path.exists(db_path):
            self.stderr.write(self.style.ERROR(f'Database not found: {db_path}'))
            self.stderr.write(self.style.ERROR('Run mdb_integration.py first to create it.'))
            return

        self.stdout.write(f'Reading from: {db_path}')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        start = datetime.now()

        # Import order matters due to FK relationships
        self.stdout.write('\n=== Clearing existing Maxicom data ===')
        self._clear_all()

        self.stdout.write('\n=== Importing Sites (SITE_CF) ===')
        site_map = self._import_sites(conn)
        self.stdout.write(self.style.SUCCESS(f'  Imported {len(site_map)} sites'))

        self.stdout.write('\n=== Importing Weather Stations (WETHR_CF) ===')
        ws_map = self._import_weather_stations(conn)
        self.stdout.write(self.style.SUCCESS(f'  Imported {len(ws_map)} weather stations'))

        self.stdout.write('\n=== Importing Controllers (CTROL_CF) ===')
        ctrl_map = self._import_controllers(conn, site_map)
        self.stdout.write(self.style.SUCCESS(f'  Imported {len(ctrl_map)} controllers'))

        self.stdout.write('\n=== Importing Flow Zones (FLOZO_CF) ===')
        fz_map = self._import_flow_zones(conn, site_map)
        self.stdout.write(self.style.SUCCESS(f'  Imported {len(fz_map)} flow zones'))

        self.stdout.write('\n=== Importing Stations (STATN_CF) ===')
        stn_map = self._import_stations(conn, site_map, ctrl_map)
        self.stdout.write(self.style.SUCCESS(f'  Imported {len(stn_map)} stations'))

        self.stdout.write('\n=== Importing Schedules (SCHED_CF) ===')
        sched_count = self._import_schedules(conn, site_map)
        self.stdout.write(self.style.SUCCESS(f'  Imported {sched_count} schedules'))

        self.stdout.write('\n=== Importing Weather Logs (XA_WETHR) ===')
        wl_count = self._import_weather_logs(conn, ws_map)
        self.stdout.write(self.style.SUCCESS(f'  Imported {wl_count} weather readings'))

        self.stdout.write('\n=== Importing Events (XA_EVENT) ===')
        ev_count = self._import_events(conn)
        self.stdout.write(self.style.SUCCESS(f'  Imported {ev_count} events'))

        self.stdout.write('\n=== Importing ET Checkbook (XA_ETCheckBook) ===')
        et_count = self._import_et_checkbook(conn, site_map)
        self.stdout.write(self.style.SUCCESS(f'  Imported {et_count} ET checkbook entries'))

        self.stdout.write('\n=== Importing Runtime (XA_RuntimeProject) ===')
        rt_count = self._import_runtime(conn, site_map, stn_map)
        self.stdout.write(self.style.SUCCESS(f'  Imported {rt_count} runtime entries'))

        if not skip_large:
            self.stdout.write('\n=== Importing Signal Logs (XA_LOG) ===')
            sl_count = self._import_signal_logs(conn)
            self.stdout.write(self.style.SUCCESS(f'  Imported {sl_count} signal log entries'))

            self.stdout.write('\n=== Importing Flow Readings (XA_FLOZO) ===')
            fr_count = self._import_flow_readings(conn, fz_map, flow_limit)
            self.stdout.write(self.style.SUCCESS(f'  Imported {fr_count} flow readings'))
        else:
            self.stdout.write(self.style.WARNING('\n  Skipping large tables (XA_FLOZO, XA_LOG)'))

        conn.close()
        elapsed = (datetime.now() - start).total_seconds()
        self.stdout.write(f'\n=== Import complete in {elapsed:.1f}s ===')

    def _clear_all(self):
        """Clear all Maxicom data in reverse FK order."""
        MaxicomRuntime.objects.all().delete()
        MaxicomETCheckbook.objects.all().delete()
        MaxicomSignalLog.objects.all().delete()
        MaxicomFlowReading.objects.all().delete()
        MaxicomEvent.objects.all().delete()
        MaxicomWeatherLog.objects.all().delete()
        MaxicomRuntime.objects.all().delete()
        MaxicomSchedule.objects.all().delete()
        MaxicomStation.objects.all().delete()
        MaxicomController.objects.all().delete()
        MaxicomFlowZone.objects.all().delete()
        MaxicomWeatherStation.objects.all().delete()
        MaxicomSite.objects.all().delete()

    def _import_sites(self, conn):
        """Import SITE_CF -> MaxicomSite"""
        cursor = conn.execute('SELECT * FROM SITE_CF')
        site_map = {}  # mdb_index -> MaxicomSite
        for row in cursor.fetchall():
            r = dict(row)
            idx = r['IndexNumber']
            # Only take rows with DateClose = None (currently active)
            if r.get('DateClose'):
                continue
            site = MaxicomSite.objects.create(
                mdb_index=idx,
                name=(r.get('IndexName') or '').strip(),
                site_number=r.get('SiteNumber', 0) or 0,
                time_zone=r.get('SiteTimeZone', 'China') or 'China',
                water_pricing=r.get('SiteWaterPricing'),
                ccu_version=r.get('SiteCCUVersion', '') or '',
                et_current=r.get('SiteWaterETCurrent'),
                et_default=r.get('SiteWaterETDefault'),
                et_minimum=r.get('SiteWaterETMinimum'),
                et_maximum=r.get('SiteWaterETMaximum'),
                crop_coefficient=r.get('SiteWaterCropCoefficient'),
                rain_shutdown=(r.get('SiteRainShutDownApplies') == 'Y'),
                telephone=r.get('SiteContactTelephone', '') or '',
                date_open=r.get('DateOpen', '') or '',
                date_close=r.get('DateClose', '') or '',
            )
            if idx not in site_map:
                site_map[idx] = site
        return site_map

    def _import_weather_stations(self, conn):
        """Import WETHR_CF -> MaxicomWeatherStation"""
        cursor = conn.execute('SELECT * FROM WETHR_CF')
        ws_map = {}
        for row in cursor.fetchall():
            r = dict(row)
            idx = r['IndexNumber']
            ws, _ = MaxicomWeatherStation.objects.get_or_create(
                mdb_index=idx,
                defaults={
                    'name': (r.get('IndexName') or '').strip(),
                    'default_et': r.get('WeatherDefaultET'),
                    'time_zone': r.get('WeatherTimeZone', 'China') or 'China',
                }
            )
            ws_map[idx] = ws
        return ws_map

    def _import_controllers(self, conn, site_map):
        """Import CTROL_CF -> MaxicomController"""
        cursor = conn.execute('SELECT * FROM CTROL_CF')
        ctrl_map = {}
        for row in cursor.fetchall():
            r = dict(row)
            idx = r['IndexNumber']
            site_idx = r.get('ControllerSiteNumber')
            site = site_map.get(site_idx)
            if not site:
                continue
            ctrl = MaxicomController.objects.create(
                site=site,
                mdb_index=idx,
                name=(r.get('IndexName') or '').strip(),
                controller_type='',
                site_number=r.get('ControllerSiteNumber', 0) or 0,
                link_number=r.get('ControllerLinkNumber', 0) or 0,
                link_channel=r.get('ControllerLinkChannel', 0) or 0,
                enabled=(r.get('ControllerEnabled') == 'Y'),
                date_open=r.get('DateOpen', '') or '',
            )
            ctrl_map[idx] = ctrl
        return ctrl_map

    def _import_flow_zones(self, conn, site_map):
        """Import FLOZO_CF -> MaxicomFlowZone"""
        cursor = conn.execute('SELECT * FROM FLOZO_CF')
        fz_map = {}
        for row in cursor.fetchall():
            r = dict(row)
            idx = r['IndexNumber']
            site_idx = r.get('FlowZoneSiteNumber')
            site = site_map.get(site_idx)
            if not site:
                continue
            fz = MaxicomFlowZone.objects.create(
                site=site,
                mdb_index=idx,
                name=(r.get('IndexName') or '').strip(),
                join_site=(r.get('FlowZoneJoinSite') == 'Y'),
            )
            fz_map[idx] = fz
        return fz_map

    def _import_stations(self, conn, site_map, ctrl_map):
        """Import STATN_CF -> MaxicomStation"""
        cursor = conn.execute('SELECT * FROM STATN_CF')
        stn_map = {}
        for row in cursor.fetchall():
            r = dict(row)
            idx = r['IndexNumber']
            site_idx = r.get('StationSiteNumber')
            ctrl_idx = r.get('StationControllerNumber')
            site = site_map.get(site_idx)
            if not site:
                continue
            ctrl = ctrl_map.get(ctrl_idx)

            lockout_val = r.get('Lockout', 0)
            if idx in stn_map:
                continue  # Skip duplicate mdb_index
            stn = MaxicomStation.objects.create(
                site=site,
                controller=ctrl,
                mdb_index=idx,
                name=(r.get('IndexName') or '').strip(),
                controller_channel=r.get('StationControllerChannel', 0) or 0,
                precip_rate=r.get('StationPrecipFactor'),
                flow_rate=r.get('StationFlowFactor'),
                microclimate_factor=r.get('StationMicroclimeFactor'),
                cycle_time=r.get('StationCycleTime'),
                soak_time=r.get('StationSoakTime'),
                memo=r.get('StationMemo', '') or '',
                lockout=bool(lockout_val),
                flow_manager_priority=r.get('FloManagerPriorityLevel'),
                date_open=r.get('DateOpen', '') or '',
            )
            stn_map[idx] = stn
        return stn_map

    def _import_schedules(self, conn, site_map):
        """Import SCHED_CF -> MaxicomSchedule"""
        cursor = conn.execute('SELECT * FROM SCHED_CF')
        count = 0
        batch = []
        for row in cursor.fetchall():
            r = dict(row)
            site_idx = r.get('ScheduleSiteNumber')
            site = site_map.get(site_idx)
            if not site:
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
                instruction_file=r.get('ScheduleInstructionFile', '') or '',
                sensitized_et=(r.get('ScheduleSensitizedET') == 'Y'),
                date_open=r.get('DateOpen', '') or '',
            ))
            count += 1
        MaxicomSchedule.objects.bulk_create(batch, batch_size=500)
        return count

    def _import_weather_logs(self, conn, ws_map):
        """Import XA_WETHR -> MaxicomWeatherLog"""
        cursor = conn.execute('SELECT * FROM XA_WETHR')
        batch = []
        count = 0
        for row in cursor.fetchall():
            r = dict(row)
            ws_idx = r.get('XactIndex')
            ws = ws_map.get(ws_idx)
            if not ws:
                continue
            batch.append(MaxicomWeatherLog(
                weather_station=ws,
                timestamp=r.get('XactStamp', '') or '',
                temperature=r.get('Temperature'),
                max_temp=r.get('MaxTemp'),
                min_temp=r.get('MinTemp'),
                solar_radiation=r.get('SolarRadiation'),
                rainfall=r.get('RainFall'),
                humidity=r.get('Humidity'),
                wind_run=r.get('WindRun'),
                et=r.get('ET'),
            ))
            count += 1
            if len(batch) >= 1000:
                MaxicomWeatherLog.objects.bulk_create(batch, batch_size=1000)
                batch = []
                self.stdout.write(f'    {count} weather logs...')
        if batch:
            MaxicomWeatherLog.objects.bulk_create(batch, batch_size=1000)
        return count

    def _import_events(self, conn):
        """Import XA_EVENT -> MaxicomEvent"""
        cursor = conn.execute('SELECT * FROM XA_EVENT')
        batch = []
        for row in cursor.fetchall():
            r = dict(row)
            batch.append(MaxicomEvent(
                timestamp=r.get('XactStamp', '') or '',
                source=r.get('EventSource', '') or '',
                index=r.get('XactIndex'),
                event_number=r.get('EventNumber'),
                flag=r.get('EventFlag', '') or '',
                text=r.get('EventTextQualifier', '') or '',
            ))
        MaxicomEvent.objects.bulk_create(batch, batch_size=500)
        return len(batch)

    def _import_et_checkbook(self, conn, site_map):
        """Import XA_ETCheckBook -> MaxicomETCheckbook"""
        cursor = conn.execute('SELECT * FROM XA_ETCheckBook')
        batch = []
        count = 0
        for row in cursor.fetchall():
            r = dict(row)
            site = site_map.get(r.get('SiteID'))
            if not site:
                continue
            batch.append(MaxicomETCheckbook(
                timestamp=r.get('XactStamp', '') or '',
                site=site,
                soil_moisture=r.get('SoilMoisture'),
                rainfall=r.get('Rainfall'),
                et=r.get('ET'),
                irrigation=r.get('Irrigation'),
                soil_moisture_capacity=r.get('SoilMoistureHoldingCapacity'),
                soil_refill_pct=r.get('SoilRefillPercentage'),
            ))
            count += 1
        MaxicomETCheckbook.objects.bulk_create(batch, batch_size=1000)
        return count

    def _import_runtime(self, conn, site_map, stn_map):
        """Import XA_RuntimeProject -> MaxicomRuntime"""
        cursor = conn.execute('SELECT * FROM XA_RuntimeProject')
        batch = []
        count = 0
        for row in cursor.fetchall():
            r = dict(row)
            site = site_map.get(r.get('SiteID'))
            if not site:
                continue
            stn = stn_map.get(r.get('StationID'))
            batch.append(MaxicomRuntime(
                timestamp=r.get('TimeStamps', '') or '',
                station=stn,
                site=site,
                station_id_raw=r.get('StationID', 0) or 0,
                run_time=r.get('RunTime'),
            ))
            count += 1
        MaxicomRuntime.objects.bulk_create(batch, batch_size=1000)
        return count

    def _import_signal_logs(self, conn):
        """Import XA_LOG -> MaxicomSignalLog"""
        cursor = conn.execute('SELECT * FROM XA_LOG')
        batch = []
        count = 0
        for row in cursor.fetchall():
            r = dict(row)
            batch.append(MaxicomSignalLog(
                timestamp=r.get('XactStamp', '') or '',
                index=r.get('XactIndex'),
                controller_channel=r.get('ControllerChannel'),
                signal_index=r.get('SignalIndex'),
                signal_table=r.get('SignalTable', '') or '',
                signal_type=r.get('SignalType', '') or '',
                signal_value=r.get('SignalValue'),
                signal_multiplier=r.get('SignalMultiplier'),
            ))
            count += 1
            if len(batch) >= 5000:
                MaxicomSignalLog.objects.bulk_create(batch, batch_size=5000)
                batch = []
                self.stdout.write(f'    {count} signal logs...')
        if batch:
            MaxicomSignalLog.objects.bulk_create(batch, batch_size=5000)
        return count

    def _import_flow_readings(self, conn, fz_map, flow_limit=0):
        """Import XA_FLOZO -> MaxicomFlowReading"""
        # This table has ~4M rows, import in batches
        total = 0
        for fz_idx, fz_obj in fz_map.items():
            if flow_limit > 0:
                cursor = conn.execute(
                    'SELECT * FROM XA_FLOZO WHERE XactIndex = ? LIMIT ?',
                    [fz_idx, flow_limit]
                )
            else:
                cursor = conn.execute(
                    'SELECT * FROM XA_FLOZO WHERE XactIndex = ?',
                    [fz_idx]
                )
            batch = []
            for row in cursor.fetchall():
                r = dict(row)
                batch.append(MaxicomFlowReading(
                    flow_zone=fz_obj,
                    timestamp=r.get('XactStamp', '') or '',
                    value=r.get('FlowZoneValue'),
                    multiplier=r.get('FlowZoneMultiplier'),
                    site_id=r.get('SiteID'),
                ))
                if len(batch) >= 5000:
                    MaxicomFlowReading.objects.bulk_create(batch, batch_size=5000)
                    batch = []
            if batch:
                MaxicomFlowReading.objects.bulk_create(batch, batch_size=5000)
            total += len(batch)  # approximate
            self.stdout.write(f'    Flow zone {fz_obj.name}: done')
        return total