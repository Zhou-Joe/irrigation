"""Import Maxicom actual controller/station logs from a Linux MDB export.

XA_LOG station M readings are actual runtime minutes with UTC timestamps.
XA_RuntimeProject is projected schedule data and must never be merged into
Actual Log totals. UI and report boundaries convert local time to UTC through
core.irrig_time; the stored original timestamps remain unchanged.

CCU grouping resolves the controller's source Site key through SITE_CF to its
display number. Controller names are labels, and may name a different area
(LR37-4 is connected to Site 14). A name prefix is only a fallback when the
source Site cannot be resolved. Existing CCU safety snapshots remain in force.
Flow days are assigned after converting UTC readings to the local timezone.
"""
import csv
import datetime
import os
import re
import subprocess
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import Patch, MaxicomRuntime, MaxicomController
from core.import_status import record_import

CCU_RE = re.compile(r'^CCU(\d+)$', re.IGNORECASE)
BATCH = 1000


def controller_ccus(rows, source_to_ccu, ccus_by_number):
    """Resolve physical Site membership before considering descriptive names."""
    resolved = {}
    for row in rows:
        index = int(row.get('IndexNumber') or 0)
        source = int(row.get('ControllerSiteNumber') or 0)
        ccu = source_to_ccu.get(source)
        if ccu is None:
            match = re.search(r'(\d+)\s*-\s*\d+', _sq(row.get('IndexName')))
            ccu = ccus_by_number.get(int(match.group(1))) if match else None
        if index and ccu is not None:
            resolved[index] = ccu
    return resolved


def actual_runtime_values(rows):
    """Yield (UTC timestamp, raw station ID, actual minutes) from station logs."""
    for row in rows:
        if _sq(row.get('SignalType')) != 'M' or _sq(row.get('SignalTable')) != 'S':
            continue
        try:
            station = int(row.get('XactIndex') or 0)
            minutes = int(row.get('SignalValue') or 0)
            stamp = _sq(row.get('XactStamp'))
            datetime.datetime.strptime(stamp, '%Y%m%d%H%M%S')
        except (TypeError, ValueError):
            continue
        if station > 0 and minutes > 0:
            yield stamp, station, minutes


def _sq(v):
    if v is None:
        return ''
    s = str(v).strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s


def _mdb_rows(mdb_path, table):
    proc = subprocess.run(['mdb-export', mdb_path, table],
                          capture_output=True, text=True, check=True)
    for row in csv.DictReader(proc.stdout.splitlines()):
        yield row


class Command(BaseCommand):
    help = 'Import Maxicom actual runtime (XA_LOG M, UTC) and local irrigation-day flow data (CCU-safe)'

    def add_arguments(self, parser):
        parser.add_argument('--source-archive', default='', help='Source backup name for the sync indicator')
        parser.add_argument('--flow-only', action='store_true',
                            help='Import flow records without changing station runtime')
        parser.add_argument('--sensors-only', action='store_true',
                            help='Import physical flow sensors without changing runtime or FLO WATCH')
        parser.add_argument('--mdb', type=str, required=True,
                            help='Path to Maxicom2.mdb')

    @record_import
    def handle(self, *args, **options):
        mdb_path = options['mdb']
        if not os.path.exists(mdb_path):
            raise CommandError(f'MDB not found: {mdb_path}')

        if options.get('sensors_only'):
            from core.sensor_flow import import_sensor_flow
            import_sensor_flow(mdb_path, _mdb_rows, subprocess.Popen, self.stdout)
            return

        if options.get('flow_only'):
            self._import_flow(mdb_path)
            return

        # ── 0. Snapshot CCU patches (safety net) ───────────────────────────
        ccu_snapshot = {}
        for p in Patch.objects.filter(code__iregex=r'^CCU\d+$'):
            ccu_snapshot[p.id] = (p.code, p.name, p.parent_id, p.mdb_index)
        self.stdout.write(f'CCU safety snapshot: {len(ccu_snapshot)} patches')

        def verify_ccus():
            drifted = []
            for p in Patch.objects.filter(code__iregex=r'^CCU\d+$'):
                snap = ccu_snapshot.get(p.id)
                if snap is None or (p.code, p.name, p.parent_id, p.mdb_index) != snap:
                    drifted.append(p.id)
            return drifted

        def restore_ccus():
            for pid, (code, name, parent_id, mdb_index) in ccu_snapshot.items():
                Patch.objects.filter(id=pid).update(
                    name=name, parent_id=parent_id, mdb_index=mdb_index)

        # ── 1. SiteNumber -> CCU Patch map ─────────────────────────────────
        site_map = {}
        for p in Patch.objects.filter(code__iregex=r'^CCU\d+$'):
            m = CCU_RE.match(p.code)
            site_map[int(m.group(1))] = p

        from core.flow_import import latest_config
        source_sites = latest_config(list(_mdb_rows(mdb_path, 'SITE_CF')))
        source_to_ccu = {}
        for source_index, row in source_sites.items():
            try:
                number = int(row.get('SiteNumber') or 0)
                if number in site_map: source_to_ccu[int(source_index)] = site_map[number]
            except (ValueError, TypeError):
                continue

        # ── 1b. Controller IndexNumber -> actual Site's display CCU ────────
        # ControllerSiteNumber is an internal key, NOT the displayed number:
        # key 5 displays CCU3, while key 12 displays CCU14. Resolve SITE_CF
        # first. A label such as LR37-4 must not override its real Site 14
        # connection. Cache the selected controller config for the rebuild.
        controller_rows = list(latest_config(list(_mdb_rows(mdb_path, 'CTROL_CF'))).values())
        ctrl_to_ccu = controller_ccus(controller_rows, source_to_ccu, site_map)
        self.stdout.write(f'Controller->CCU by resolved Site: {len(ctrl_to_ccu)} mapped')

        # ── 2. STATN_CF -> station Patches (idempotent) ────────────────────
        existing_station_codes = set(
            Patch.objects.filter(code__startswith='station-').values_list('code', flat=True))
        rows = list(latest_config(list(_mdb_rows(mdb_path, 'STATN_CF'))).values())
        seen_idx = set()
        to_create = []
        no_site = 0
        for r in rows:
            idx = (r.get('IndexNumber') or '').strip()
            if not idx or idx in seen_idx:
                continue
            seen_idx.add(idx)
            code = 'station-' + idx
            if code in existing_station_codes:
                continue
            site_number = int((r.get('StationSiteNumber') or '0') or 0)
            ctrl_num = int((r.get('StationControllerNumber') or '0') or 0) or None
            parent_ccu = ctrl_to_ccu.get(ctrl_num) if ctrl_num else None
            if not parent_ccu:
                # StationSiteNumber is a SITE_CF internal IndexNumber. Resolve
                # its current SiteNumber before looking up the display CCU.
                parent_ccu = source_to_ccu.get(site_number)
            if not parent_ccu:
                no_site += 1
                continue
            to_create.append(Patch(
                code=code,
                mdb_index=int(idx),
                name=_sq(r.get('IndexName')) or ('Station ' + idx),
                parent=parent_ccu,
                site_number=site_number,
                controller_number=ctrl_num,
                controller_channel=int((r.get('StationControllerChannel') or '0') or 0) or None,
            ))
            if len(to_create) >= BATCH:
                Patch.objects.bulk_create(to_create)
                to_create = []
        if to_create:
            Patch.objects.bulk_create(to_create)

        # Re-parent existing stations to the controller's actual Site CCU.
        # Patch IDs remain stable, preserving all station/zone references.
        by_ccu = defaultdict(list)
        changed_metadata = []
        current_stations = {int(r['IndexNumber']): r for r in rows if str(r.get('IndexNumber','')).isdigit()}
        for st in Patch.objects.filter(code__startswith='station-'):
            current = current_stations.get(st.mdb_index)
            if current:
                previous = (st.controller_number, st.controller_channel, st.site_number)
                st.controller_number = int(current.get('StationControllerNumber') or 0) or None
                st.controller_channel = int(current.get('StationControllerChannel') or 0) or None
                st.site_number = int(current.get('StationSiteNumber') or 0)
                if previous != (st.controller_number, st.controller_channel, st.site_number):
                    changed_metadata.append(st)
            ccu = (ctrl_to_ccu.get(st.controller_number) if st.controller_number else None) or source_to_ccu.get(st.site_number)
            if ccu is not None and ccu.id != st.parent_id:
                by_ccu[ccu.id].append(st.id)
        if changed_metadata:
            Patch.objects.bulk_update(changed_metadata, ['controller_number','controller_channel','site_number'], batch_size=500)
        reparented = 0
        for ccu_id, ids in by_ccu.items():
            Patch.objects.filter(id__in=ids).update(parent_id=ccu_id)
            reparented += len(ids)
        self.stdout.write(self.style.SUCCESS(
            f'Stations: {len(existing_station_codes)} existed, '
            f'{Patch.objects.filter(code__startswith="station-").count() - len(existing_station_codes)} new, '
            f'{no_site} no-CCU-skipped, {reparented} re-parented to resolved Site CCU'
        ))

        drifted = verify_ccus()
        if drifted:
            self.stderr.write(self.style.ERROR(
                f'CCU corruption after stations ({len(drifted)} drifted) — restoring + aborting'))
            restore_ccus()
            raise CommandError('CCU safety verification failed after station import')

        # ── 2b. CTROL_CF -> MaxicomController (full rebuild) ──────────────
        # The dashboard pivots runtime by satellite using ctrl_map keyed by
        # mdb_index, joined to each station via controller_number
        # (== CTROL_CF IndexNumber). If this table drifts from the mdb, that join
        # misses and the dashboard silently shows 0 — which happened because the
        # nightly job never refreshed MaxicomController. Rebuild it every run.
        # Controllers, stations and runtime share the same resolved source Site.
        # No model FKs into MaxicomController, so delete+rebuild cascades nothing.
        new_ctrls = []
        for r in controller_rows:
            idx = (r.get('IndexNumber') or '').strip()
            if not idx:
                continue
            site_number = int((r.get('ControllerSiteNumber') or '0') or 0)
            site = ctrl_to_ccu.get(int(idx)) or source_to_ccu.get(site_number)
            if site is None:
                continue
            new_ctrls.append(MaxicomController(
                site=site,
                mdb_index=int(idx),
                name=_sq(r.get('IndexName')) or ('Controller ' + idx),
                controller_type='',
                site_number=site_number,
                link_number=int((r.get('ControllerLinkNumber') or '0') or 0),
                link_channel=int((r.get('ControllerLinkChannel') or '0') or 0),
                enabled=(str(r.get('ControllerEnabled') or '').strip().upper() == 'Y'),
                date_open=_sq(r.get('DateOpen')),
            ))
        with transaction.atomic():
            MaxicomController.objects.all().delete()
            MaxicomController.objects.bulk_create(new_ctrls)
        self.stdout.write(self.style.SUCCESS(
            f'Controllers rebuilt: {len(new_ctrls)} ({MaxicomController.objects.count()} total)'
        ))

        # Actual runtime only. Reading the original UTC poll timestamps keeps
        # historical values stable when projected schedules are regenerated.
        stn_map = {p.mdb_index: p for p in
                   Patch.objects.filter(code__startswith='station-').exclude(mdb_index__isnull=True)}
        to_create = []
        skipped_no_site = 0
        previous_runtime_count = MaxicomRuntime.objects.count()
        with transaction.atomic():
            MaxicomRuntime.objects.all().delete()
            for raw_stamp, xi, minutes in actual_runtime_values(_mdb_rows(mdb_path, 'XA_LOG')):
                st = stn_map.get(xi)
                if st is None or st.parent_id is None:
                    skipped_no_site += 1
                    continue
                to_create.append(MaxicomRuntime(
                    timestamp=raw_stamp, site_id=st.parent_id,
                    station_id=st.id, station_id_raw=xi, run_time=minutes))
                if len(to_create) >= BATCH:
                    MaxicomRuntime.objects.bulk_create(to_create)
                    to_create.clear()
            if to_create:
                MaxicomRuntime.objects.bulk_create(to_create)
            if previous_runtime_count and not MaxicomRuntime.objects.exists():
                raise CommandError('No mapped actual runtime readings; previous runtime data was preserved')
        drifted = verify_ccus()
        if drifted:
            self.stderr.write(self.style.ERROR(
                f'CCU corruption after runtime ({len(drifted)} drifted) — restoring'))
            restore_ccus()
            raise CommandError('CCU safety verification failed after runtime import')
        self.stdout.write(self.style.SUCCESS(
            f'Runtime (XA_LOG actual M readings, UTC): {MaxicomRuntime.objects.count()} rows, '
            f'{skipped_no_site} no-CCU-skipped'
        ))

        self._import_flow(mdb_path)
        self.stdout.write(self.style.SUCCESS(
            f'Done: {Patch.objects.count()} patches, '
            f'{MaxicomRuntime.objects.count()} runtime rows'
        ))

    def _import_flow(self, mdb_path):
        from core.flow_import import import_flow
        from core.sensor_flow import import_sensor_flow
        with transaction.atomic():
            import_flow(mdb_path, _mdb_rows, subprocess.Popen, self.stdout)
            import_sensor_flow(mdb_path, _mdb_rows, subprocess.Popen, self.stdout)
