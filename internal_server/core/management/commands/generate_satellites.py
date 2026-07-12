"""Generate Satellite records from existing Zone.code prefixes.

A Satellite (SAT) corresponds to the first two segments of a zone's code
(``CCU-CTRL``, e.g. ``35-2``). This command scans all zones, extracts unique
SAT codes, creates ``Satellite`` rows, and links each zone's ``satellite`` FK.
Idempotent: re-running only creates missing SATs and fills unlinked zones.

Usage:
    python manage.py generate_satellites
"""

from django.core.management.base import BaseCommand
from core.models import Zone, Satellite, Patch


class Command(BaseCommand):
    help = 'Generate Satellite records from Zone.code prefixes and link zones.'

    def handle(self, *args, **options):
        # 1. Collect all unique SAT codes (first 2 segments of zone.code).
        sat_codes = {}   # sat_code → {ccu_num, first_zone}
        for z in Zone.objects.exclude(code__isnull=True).exclude(code=''):
            parts = z.code.strip().split('-')
            if len(parts) < 2:
                continue
            sat_code = parts[0] + '-' + parts[1]
            if sat_code not in sat_codes:
                sat_codes[sat_code] = {'ccu_num': parts[0], 'zone': z}

        self.stdout.write(f'Found {len(sat_codes)} unique SAT codes from zone data.')

        # 2. Create missing Satellite records.
        created = 0
        sat_map = {}   # sat_code → Satellite instance
        for sat_code, info in sat_codes.items():
            obj, was_created = Satellite.objects.get_or_create(
                code=sat_code,
                defaults={'patch': self._find_patch(info['ccu_num'])},
            )
            sat_map[sat_code] = obj
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Created {created} new Satellite records ('
                      f'{len(sat_map)} total).'))

        # 3. Link unlinked zones to their SAT.
        linked = 0
        zones_to_update = []
        for z in Zone.objects.filter(satellite__isnull=True).exclude(code__isnull=True).exclude(code=''):
            parts = z.code.strip().split('-')
            if len(parts) < 2:
                continue
            sat_code = parts[0] + '-' + parts[1]
            sat = sat_map.get(sat_code)
            if sat:
                z.satellite = sat
                zones_to_update.append(z)
                linked += 1
        if zones_to_update:
            Zone.objects.bulk_update(zones_to_update, ['satellite'])
        self.stdout.write(self.style.SUCCESS(f'Linked {linked} zones to their SAT.'))

    def _find_patch(self, ccu_num):
        """Find the Patch (CCU) matching a CCU number, e.g. '35' → CCU35."""
        return Patch.objects.filter(code__iexact=f'CCU{ccu_num}').first()
