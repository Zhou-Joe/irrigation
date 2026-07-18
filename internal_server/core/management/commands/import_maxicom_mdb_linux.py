"""Import CTROL_CF (controllers) + STATN_CF (stations) + XA_LOG (runtime)
from a Maxicom2.mdb into the Django DB — Linux (mdbtools), CCU-safe.

CCU grouping: satellites are grouped into CCUs by the "<N>-<x>" prefix in the
controller IndexName (e.g. "SAT 3-5" -> CCU3), NOT by Maxicom's SiteNumber. The
sites were renumbered in Maxicom so SiteNumber no longer matches the CCU number,
while the satellite names are stable. This map is re-derived from CTROL_CF every
run and re-applied to controllers/stations/runtime, so a future renumbering
self-heals on the next import.

Runtime: read from XA_LOG (SignalType 'M') — the authoritative raw controller
poll log, NOT XA_RuntimeProject (an incomplete derivative that drops long runs).
Each 'M' reading (XactIndex = station, SignalValue = minutes) is stored with an
"irrigation day" timestamp: a poll at >= 22:00 is attributed to the next date
(overnight irrigation runs into the following day), so daily totals match the
Maxicom UI. MaxicomRuntime is fully rebuilt from XA_LOG each run (XA_LOG is the
cumulative source), which also clears any stale XA_RuntimeProject data.

CCU safety: snapshots every CCU patch's (code, name, parent_id, mdb_index)
before writing, verifies them unchanged after. If anything drifts, restores
from the snapshot and aborts — the earlier corruption (CCU parent/name wiped)
cannot recur.

Usage:
    python manage.py import_maxicom_mdb_linux --mdb /path/to/Maxicom2.mdb
"""
import csv
import datetime
import os
import re
import subprocess
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Patch, MaxicomRuntime, MaxicomController

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
    help = 'Import CTROL_CF controllers + STATN_CF stations + XA_LOG runtime (SignalType M, irrigation-day rolled @22:00) from a Maxicom2.mdb (Linux/mdbtools, CCU-safe)'

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

        # ── 1b. Controller IndexNumber -> CCU (by satellite NAME prefix) ───
        # Maxicom's SiteNumber is NOT a reliable CCU key: the sites were
        # renumbered, so e.g. the satellites named "SAT 3-x" now sit under
        # Maxicom site 5 (and "SAT 5-x" under site 3), and the offset is
        # different again for other sites. The satellite NAME prefix is the
        # stable CCU identity — it matches the original setup (every CCU's
        # satellites were "SAT <ccu>-x") and what operators expect. So we group
        # controllers/stations/runtime by the "<N>-<x>" prefix in the controller
        # IndexName, not by SiteNumber. Re-derived from CTROL_CF every run, so a
        # future Maxicom renumbering self-heals on the next import.
        SAT_PREFIX_RE = re.compile(r'(\d+)\s*-\s*\d+')
        ctrl_to_ccu = {}          # CTROL_CF IndexNumber -> CCU Patch
        no_prefix_ctrl = 0
        for r in _mdb_rows(mdb_path, 'CTROL_CF'):
            idx = (r.get('IndexNumber') or '').strip()
            nm = _sq(r.get('IndexName'))
            if not idx or nm == 'Site CCU':
                continue
            m = SAT_PREFIX_RE.search(nm or '')
            if not m:
                no_prefix_ctrl += 1
                continue
            ccu = site_map.get(int(m.group(1)))
            if ccu is not None:
                ctrl_to_ccu[int(idx)] = ccu
        self.stdout.write(f'Controller->CCU by name prefix: {len(ctrl_to_ccu)} mapped, '
                          f'{no_prefix_ctrl} no-prefix/skipped')

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
            ctrl_num = int((r.get('StationControllerNumber') or '0') or 0) or None
            parent_ccu = ctrl_to_ccu.get(ctrl_num) if ctrl_num else None
            if not parent_ccu:
                # SiteID fallback: some sites (e.g. Maxicom 15/16/17) name their
                # satellites "SAT1"/"SAT2" with no "<N>-x" prefix, so the name map
                # can't place them — fall back to StationSiteNumber so they land on
                # the CCU patch matching their site number (CCU15/16/17).
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
                controller_number=ctrl_num,
                controller_channel=int((r.get('StationControllerChannel') or '0') or 0) or None,
            ))
            if len(to_create) >= BATCH:
                Patch.objects.bulk_create(to_create)
                to_create = []
        if to_create:
            Patch.objects.bulk_create(to_create)

        # Re-parent existing stations to their name-prefix CCU (self-healing: a
        # station imported under the old scrambled SiteNumber moves to the CCU its
        # satellite name actually denotes on the next run).
        by_ccu = defaultdict(list)
        for st in Patch.objects.filter(code__startswith='station-'):
            ccu = ctrl_to_ccu.get(st.controller_number) if st.controller_number else None
            if ccu is not None and ccu.id != st.parent_id:
                by_ccu[ccu.id].append(st.id)
        reparented = 0
        for ccu_id, ids in by_ccu.items():
            Patch.objects.filter(id__in=ids).update(parent_id=ccu_id)
            reparented += len(ids)
        self.stdout.write(self.style.SUCCESS(
            f'Stations: {len(existing_station_codes)} existed, '
            f'{Patch.objects.filter(code__startswith="station-").count() - len(existing_station_codes)} new, '
            f'{no_site} no-CCU-skipped, {reparented} re-parented to name-prefix CCU'
        ))

        drifted = verify_ccus()
        if drifted:
            self.stderr.write(self.style.ERROR(
                f'CCU corruption after stations ({len(drifted)} drifted) — restoring + aborting'))
            restore_ccus()
            return

        # ── 2b. CTROL_CF -> MaxicomController (full rebuild) ──────────────
        # The dashboard pivots runtime by satellite using ctrl_map keyed by
        # mdb_index, joined to each station via controller_number
        # (== CTROL_CF IndexNumber). If this table drifts from the mdb, that join
        # misses and the dashboard silently shows 0 — which happened because the
        # nightly job never refreshed MaxicomController. Rebuild it every run.
        # site follows the satellite NAME prefix (ctrl_to_ccu) so the controller
        # lines up with where its stations/runtime actually live; SiteNumber is
        # only a fallback for controllers with no parseable prefix. No model FKs
        # into MaxicomController, so delete+rebuild cascades nothing.
        new_ctrls = []
        for r in _mdb_rows(mdb_path, 'CTROL_CF'):
            idx = (r.get('IndexNumber') or '').strip()
            if not idx:
                continue
            site_number = int((r.get('ControllerSiteNumber') or '0') or 0)
            site = ctrl_to_ccu.get(int(idx)) or site_map.get(site_number)
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

        # ── 3. XA_LOG (SignalType 'M') -> MaxicomRuntime ────────────────────
        # The authoritative runtime source is XA_LOG (the raw controller poll
        # log), NOT XA_RuntimeProject (an incomplete derivative that silently
        # drops long runs — e.g. a 538-min cycle was entirely absent there). Each
        # 'M' signal: XactIndex = station IndexNumber, SignalValue = runtime
        # minutes accumulated since the previous poll.
        # Irrigation-day roll: landscape irrigation runs overnight and the nightly
        # poll (~22:30) STARTS the next day's cycle, so a reading timestamped
        # >= 22:00 is attributed to date+1. Daily totals then match the Maxicom
        # UI exactly (verified across CCU9 SAT 9-1..9-4: 10/20/10/538/899…).
        stn_map = {p.mdb_index: p for p in
                   Patch.objects.filter(code__startswith='station-').exclude(mdb_index__isnull=True)}

        def _irrig_ts(xactstamp):
            s = (xactstamp or '').strip()
            d = s[:8]
            if len(d) != 8:
                return s
            hh = int(s[8:10]) if len(s) >= 10 and s[8:10].isdigit() else 0
            if hh >= 22:
                d = (datetime.datetime.strptime(d, '%Y%m%d')
                     + datetime.timedelta(days=1)).strftime('%Y%m%d')
            return d + s[8:]

        # Atomic full rebuild — XA_LOG is the cumulative source, so re-derive
        # every run (also clears the old XA_RuntimeProject data). Streamed in
        # batches so memory stays bounded; the transaction makes a failure leave
        # the previous data intact.
        to_create = []
        skipped_no_site = 0
        with transaction.atomic():
            MaxicomRuntime.objects.all().delete()
            for r in _mdb_rows(mdb_path, 'XA_LOG'):
                if (r.get('SignalType') or '').strip() != 'M':
                    continue
                xi = int((r.get('XactIndex') or '0') or 0)
                st = stn_map.get(xi)
                if st is None or st.parent_id is None:
                    skipped_no_site += 1
                    continue
                to_create.append(MaxicomRuntime(
                    timestamp=_irrig_ts(_sq(r.get('XactStamp'))),
                    site_id=st.parent_id,
                    station_id=st.id,
                    station_id_raw=xi,
                    run_time=int((r.get('SignalValue') or '0') or 0),
                ))
                if len(to_create) >= BATCH:
                    MaxicomRuntime.objects.bulk_create(to_create)
                    to_create = []
            if to_create:
                MaxicomRuntime.objects.bulk_create(to_create)
        created_rt = MaxicomRuntime.objects.count()

        drifted = verify_ccus()
        if drifted:
            self.stderr.write(self.style.ERROR(
                f'CCU corruption after runtime ({len(drifted)} drifted) — restoring'))
            restore_ccus()
            return

        self.stdout.write(self.style.SUCCESS(
            f'Runtime (XA_LOG M, irrigation-day rolled @22:00): {created_rt} rows, '
            f'{skipped_no_site} no-CCU-skipped'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Done: {Patch.objects.count()} patches, '
            f'{MaxicomRuntime.objects.count()} runtime rows'
        ))
