"""Import STATN_CF (stations) + XA_RuntimeProject (runtime) from a Maxicom2.mdb
into the Django DB — Linux (mdbtools), idempotent, CCU-safe.

Idempotent: re-running with the same .mdb adds nothing; a newer .mdb only adds
new runtime rows (deduped by (timestamp, site, station_id_raw)) and any newly
appearing valves.

CCU safety: snapshots every CCU patch's (code, name, parent_id, mdb_index)
before writing, verifies them unchanged after. If anything drifts, restores
from the snapshot and aborts — the earlier corruption (CCU parent/name wiped)
cannot recur.

Usage:
    python manage.py import_maxicom_mdb_linux --mdb /path/to/Maxicom2.mdb
"""
import csv
import os
import re
import subprocess
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Patch, MaxicomRuntime

CCU_RE = re.compile(r'^CCU(\d+)$', re.IGNORECASE)
BATCH = 1000


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
    help = 'Import STATN_CF stations + XA_RuntimeProject runtime from a Maxicom2.mdb (Linux/mdbtools, idempotent, CCU-safe)'

    def add_arguments(self, parser):
        parser.add_argument('--mdb', type=str, required=True,
                            help='Path to Maxicom2.mdb')

    def handle(self, *args, **options):
        mdb_path = options['mdb']
        if not os.path.exists(mdb_path):
            self.stderr.write(self.style.ERROR(f'MDB not found: {mdb_path}'))
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

        # ── 2. STATN_CF -> station Patches (idempotent) ────────────────────
        existing_station_codes = set(
            Patch.objects.filter(code__startswith='station-').values_list('code', flat=True))
        rows = list(_mdb_rows(mdb_path, 'STATN_CF'))
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
            parent_ccu = site_map.get(site_number)
            if not parent_ccu:
                no_site += 1
                continue
            to_create.append(Patch(
                code=code,
                mdb_index=int(idx),
                name=_sq(r.get('IndexName')) or ('Station ' + idx),
                parent=parent_ccu,
                site_number=site_number,
                controller_number=int((r.get('StationControllerNumber') or '0') or 0) or None,
                controller_channel=int((r.get('StationControllerChannel') or '0') or 0) or None,
            ))
            if len(to_create) >= BATCH:
                Patch.objects.bulk_create(to_create)
                to_create = []
        if to_create:
            Patch.objects.bulk_create(to_create)
        self.stdout.write(self.style.SUCCESS(
            f'Stations: {len(existing_station_codes)} existed, '
            f'{len(Patch.objects.filter(code__startswith="station-")) - len(existing_station_codes)} new, '
            f'{no_site} no-CCU-skipped'
        ))

        drifted = verify_ccus()
        if drifted:
            self.stderr.write(self.style.ERROR(
                f'CCU corruption after stations ({len(drifted)} drifted) — restoring + aborting'))
            restore_ccus()
            return

        # ── 3. XA_RuntimeProject -> MaxicomRuntime (dedup by natural key) ──
        stn_map = {p.mdb_index: p for p in
                   Patch.objects.filter(code__startswith='station-').exclude(mdb_index__isnull=True)}
        existing_keys = set()
        for row in MaxicomRuntime.objects.values('timestamp', 'site_id', 'station_id_raw'):
            existing_keys.add((row['timestamp'], row['site_id'], row['station_id_raw']))

        rt_rows = list(_mdb_rows(mdb_path, 'XA_RuntimeProject'))
        to_create = []
        created_rt = skipped_dup = skipped_no_site = 0
        for r in rt_rows:
            ts = _sq(r.get('TimeStamps'))
            site_id_raw = int((r.get('SiteID') or '0') or 0)
            station_id_raw = int((r.get('StationID') or '0') or 0)
            site = site_map.get(site_id_raw)
            if site is None:
                skipped_no_site += 1
                continue
            key = (ts, site.id, station_id_raw)
            if key in existing_keys:
                skipped_dup += 1
                continue
            existing_keys.add(key)
            to_create.append(MaxicomRuntime(
                timestamp=ts, site=site,
                station=stn_map.get(station_id_raw),
                station_id_raw=station_id_raw,
                run_time=int((r.get('RunTime') or '0') or 0),
            ))
            if len(to_create) >= BATCH:
                MaxicomRuntime.objects.bulk_create(to_create)
                created_rt += len(to_create)
                to_create = []
        if to_create:
            MaxicomRuntime.objects.bulk_create(to_create)
            created_rt += len(to_create)

        drifted = verify_ccus()
        if drifted:
            self.stderr.write(self.style.ERROR(
                f'CCU corruption after runtime ({len(drifted)} drifted) — restoring'))
            restore_ccus()
            return

        self.stdout.write(self.style.SUCCESS(
            f'Runtime: {created_rt} new, {skipped_dup} dup-skipped, {skipped_no_site} no-site-skipped'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Done: {Patch.objects.count()} patches, '
            f'{MaxicomRuntime.objects.count()} runtime rows'
        ))
