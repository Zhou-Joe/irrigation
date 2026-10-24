"""Import Maxicom actual controller/station logs from a Linux MDB export.

XA_LOG station M readings are actual runtime minutes with UTC timestamps.
XA_RuntimeProject is projected schedule data and must never be merged into
Actual Log totals. UI and report boundaries convert local time to UTC through
core.irrig_time; the stored original timestamps remain unchanged.

CCU grouping follows controller name prefixes because historical SiteNumber
renumbering does not follow the geographic CCU labels. Existing CCU safety
snapshots remain in force. Flow days are assigned after converting UTC readings
to the application's local timezone.
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
from core.models import MaxicomFlowZone, MaxicomFlowDaily, MaxicomStationFlowFactor
from core.irrig_time import irrigation_day_for_utc

CCU_RE = re.compile(r'^CCU(\d+)$', re.IGNORECASE)
BATCH = 1000


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
            return
        self.stdout.write(self.style.SUCCESS(
            f'Runtime (XA_LOG actual M readings, UTC): {MaxicomRuntime.objects.count()} rows, '
            f'{skipped_no_site} no-CCU-skipped'
        ))

        # ── 4. FLOZO_CF + XA_FLOZO → 流量区字典 + 灌溉日浇水量 ──────────
        # XA_FLOZO 每次轮询一行：XactIndex→FLOZO_CF.IndexNumber，
        # FlowZoneValue × FlowZoneMultiplier = 该次轮询内的升数，SiteID 为
        # FLOZO 站点号。聚合按灌溉日 [D-1 22:00 → D 21:59]（时间戳 ≥22:00
        # 归次日），与灌溉数据页/导出的日窗口一致，页面按天求和即可。
        # Maxicom 桌面端的「浇水量」= 本流量计聚合 + 站点运行估算
        # （run_time × 站点系数）；系数快照存 MaxicomStationFlowFactor
        # （MV 等未配置站 = 0，与桌面端口径一致，已验证 site 8 吻合 98.8%）。

        # 4a. 字典（FLOZO_CF）→ MaxicomFlowZone
        zone_objs, zone_site_id, skipped_zones = [], {}, 0
        for r in _mdb_rows(mdb_path, 'FLOZO_CF'):
            try:
                idx = int(r.get('IndexNumber') or 0)
                site_no = int(r.get('FlowZoneSiteNumber') or 0)
            except (TypeError, ValueError):
                continue
            if not idx:
                continue
            site = site_map.get(site_no)
            if site is None:
                skipped_zones += 1     # 无 CCU 补丁的站点（twatch 等测试区）
                continue
            zone_objs.append(MaxicomFlowZone(
                site=site, mdb_index=idx,
                name=_sq(r.get('IndexName')) or f'Zone {idx}',
                join_site=_sq(r.get('FlowZoneJoinSite')).strip().upper() == 'Y'))
            zone_site_id[idx] = site.id

        # 4b. XA_FLOZO 流式聚合 (day, zone) → [liters, minutes]
        # ~400 万行：不能走 _mdb_rows（capture_output 会把整表读进内存），
        # 改 Pipe 流式逐行读；-Q -d '|' 无引号且列全为数字/时间戳，split 即可。
        agg = defaultdict(lambda: [0, 0])
        day_by_hour = {}
        proc = subprocess.Popen(
            ['mdb-export', '-Q', '-d', '|', mdb_path, 'XA_FLOZO'],
            stdout=subprocess.PIPE, text=True)
        header = proc.stdout.readline().rstrip('\n').split('|')
        ci = {c: i for i, c in enumerate(header)}
        i_stamp, i_idx = ci['XactStamp'], ci['XactIndex']
        i_val, i_mult, i_site = ci['FlowZoneValue'], ci['FlowZoneMultiplier'], ci['SiteID']
        for line in proc.stdout:
            f = line.rstrip('\n').split('|')
            try:
                ts = f[i_stamp]
                idx = int(f[i_idx])
                val = int(f[i_val] or 0)
                mult = int(f[i_mult] or 1)
            except (IndexError, ValueError):
                continue
            if not ts or len(ts) < 8 or not idx:
                continue
            # China has an integral-hour UTC offset. Cache the local day per UTC
            # hour rather than parsing millions of readings' timestamps twice.
            hour = ts[:10]
            if hour not in day_by_hour:
                try:
                    day_by_hour[hour] = irrigation_day_for_utc(hour).strftime('%Y%m%d')
                except ValueError:
                    continue
            day = day_by_hour[hour]
            a = agg[(day, idx)]
            a[0] += val * mult
            if val > 0:
                a[1] += 1
        proc.stdout.close()
        if proc.wait() != 0:
            raise CommandError('XA_FLOZO export failed; previous flow data was preserved')

        # 4c. 站点流量系数快照（STATN_CF.StationFlowFactor，L/min）
        # STATN_CF 的 IndexNumber 会重复——同号站改动后留历史行（DateClose
        # 非空）。只取有效行（DateClose 为空）；仍重复时保留 DateOpen 最新。
        factor_map = {}
        for r in _mdb_rows(mdb_path, 'STATN_CF'):
            try:
                idx = int(r.get('IndexNumber') or 0)
                fac = float(r.get('StationFlowFactor') or 0)
            except (TypeError, ValueError):
                continue
            if not idx or _sq(r.get('DateClose')):
                continue
            opened = _sq(r.get('DateOpen'))
            if idx not in factor_map or opened > factor_map[idx][0]:
                factor_map[idx] = (opened, max(fac, 0.0))
        factor_rows = [MaxicomStationFlowFactor(station_raw=i, factor=f[1])
                       for i, f in factor_map.items()]

        # 4d. 全量重建（字典 → 日聚合 → 系数），一个事务
        daily_objs = []
        with transaction.atomic():
            MaxicomFlowDaily.objects.all().delete()
            MaxicomFlowZone.objects.all().delete()
            MaxicomFlowZone.objects.bulk_create(zone_objs)
            zid_map = dict(MaxicomFlowZone.objects.values_list('mdb_index', 'id'))
            for (day, idx), (liters, minutes) in agg.items():
                zid = zid_map.get(idx)
                if zid is None:
                    continue           # 无 CCU 站点的 zone 数据不入库
                daily_objs.append(MaxicomFlowDaily(
                    flow_day=day, zone_id=zid, site_id=zone_site_id.get(idx),
                    liters=liters, minutes=minutes))
            MaxicomFlowDaily.objects.bulk_create(daily_objs, batch_size=BATCH)
            MaxicomStationFlowFactor.objects.all().delete()
            MaxicomStationFlowFactor.objects.bulk_create(factor_rows, batch_size=BATCH)

        self.stdout.write(self.style.SUCCESS(
            f'Flow: {MaxicomFlowZone.objects.count()} zones '
            f'({skipped_zones} no-CCU-skipped), '
            f'{MaxicomFlowDaily.objects.count()} zone-days, '
            f'{MaxicomStationFlowFactor.objects.count()} station factors'
        ))
        self.stdout.write(self.style.SUCCESS(
            f'Done: {Patch.objects.count()} patches, '
            f'{MaxicomRuntime.objects.count()} runtime rows'
        ))
