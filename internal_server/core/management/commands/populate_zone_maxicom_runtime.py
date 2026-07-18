"""Populate Zone.maxicom_runtime — derive the station Patch id(s) that irrigate
each landscape zone from its A-B-C code, and cache them on the zone.

Mapping (mirrors the import_maxicom_mdb_linux CCU/SAT/channel derivation):
    Zone code "A-B-C":
      A -> CCU Patch (code='CCU'+A)
      B -> MaxicomController under that CCU with link_channel=B
           (excluding the "Site CCU" hub row) → its mdb_index
      C -> controller_channel (1-24 valve)
    Resolved station Patch:
      parent=CCU, controller_number=<mdb_index above>, controller_channel=C

This is the same join the irrigation dashboard's _build_ccu_matrix uses to
pivot runtime by (satellite, channel); here we just key it off zone codes.

The CCU→satellite→controller chain must already be in place (rebuilt nightly by
import_maxicom_mdb_linux). Re-run this command after each nightly import so
zones stay linked if Maxicom's controller numbering shifts.

Usage:
    python manage.py populate_zone_maxicom_runtime
"""
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Patch, MaxicomController, Zone

ZONE_CODE_RE = re.compile(r'^(\d+)-(\d+)-(\d+)$')


class Command(BaseCommand):
    help = 'Derive Zone.maxicom_runtime (station Patch IDs) from each zone A-B-C code'

    def handle(self, *args, **options):
        # ── CCU patch lookup: CCU number → Patch ─────────────────────────
        ccu_by_num = {}
        for p in Patch.objects.filter(code__iregex=r'^CCU\d+$'):
            m = re.match(r'^CCU(\d+)$', p.code, re.IGNORECASE)
            if m:
                ccu_by_num[int(m.group(1))] = p

        # ── Satellite controller lookup: (ccu_id, link_channel) → mdb_index
        # Excludes the "Site CCU" hub row (link_channel=0 / name contains CCU),
        # same rule as Zone.maxicom_controller and the dashboard's ctrl_map.
        ctrl_map = {}  # (ccu_id, link_channel) -> mdb_index
        for c in (MaxicomController.objects
                  .exclude(name__icontains='CCU')
                  .exclude(link_channel__isnull=True)):
            ctrl_map[(c.site_id, c.link_channel)] = c.mdb_index

        # ── Station patch lookup: (ccu_id, controller_number, channel) -> id
        # Pull every station patch once and bucket by the compound key for an
        # O(stations) build instead of O(zones × stations).
        stn_index = {}  # (parent_id, ctrl_num, channel) -> [patch_id, ...]
        for st in (Patch.objects
                   .filter(code__startswith='station-',
                           controller_channel__isnull=False)
                   .only('id', 'parent_id', 'controller_number',
                         'controller_channel')):
            key = (st.parent_id, st.controller_number, st.controller_channel)
            stn_index.setdefault(key, []).append(st.id)

        # ── Resolve each zone ─────────────────────────────────────────────
        total = 0
        mapped = 0
        unmapped_codes = []
        to_update = []

        zones = list(Zone.objects.only('id', 'code'))
        for z in zones:
            total += 1
            m = ZONE_CODE_RE.match((z.code or '').strip())
            if not m:
                # Code doesn't follow A-B-C (e.g. legacy or manually-named);
                # leave whatever's already stored untouched.
                continue
            ccu_num = int(m.group(1))
            sat_link = int(m.group(2))
            channel = int(m.group(3))

            ccu = ccu_by_num.get(ccu_num)
            if ccu is None:
                unmapped_codes.append(z.code)
                continue
            ctrl_num = ctrl_map.get((ccu.id, sat_link))
            if ctrl_num is None:
                unmapped_codes.append(z.code)
                continue
            stn_ids = stn_index.get((ccu.id, ctrl_num, channel))
            if not stn_ids:
                unmapped_codes.append(z.code)
                continue

            z.maxicom_runtime = list(stn_ids)
            to_update.append(z)
            mapped += 1

        # ── Persist (idempotent — overwrites prior values) ────────────────
        with transaction.atomic():
            if to_update:
                Zone.objects.bulk_update(
                    to_update, ['maxicom_runtime'], batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f'Zones: {total} total · {mapped} mapped · '
            f'{total - mapped} unmapped ({len(unmapped_codes)} with no station)'
        ))
        if unmapped_codes:
            sample = ', '.join(sorted(set(unmapped_codes))[:15])
            self.stdout.write(self.style.WARNING(
                f'Sample unmapped codes: {sample}'
                f'{" …" if len(set(unmapped_codes)) > 15 else ""}'
            ))
