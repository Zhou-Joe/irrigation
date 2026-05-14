"""
Normalize maintenance note dates to yyyy-mm-dd format.

Handles: yy/mm/dd → 20yy-mm-dd, mm/dd → current year-mm-dd
Unparseable dates → "日期格式错误"
"""

import json
import re

from django.core.management.base import BaseCommand
from core.models import Zone
from django.utils import timezone

DATE_YYMMDD = re.compile(r'^(\d{1,2})/(\d{1,2})/(\d{1,2})$')
DATE_MMDD = re.compile(r'^(\d{1,2})/(\d{1,2})$')
DATE_YYYYMMDD = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def normalize_date(date_str):
    """Convert date string to yyyy-mm-dd or return '日期格式错误'."""
    if not date_str:
        return ''

    date_str = date_str.strip()

    # Already normalized
    if DATE_YYYYMMDD.match(date_str):
        return date_str

    # yy/mm/dd → 20yy-mm-dd
    m = DATE_YYMMDD.match(date_str)
    if m:
        yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mm <= 12 and 1 <= dd <= 31 and 0 <= yy <= 99:
            return f'20{yy:02d}-{mm:02d}-{dd:02d}'

    # mm/dd → assume current year
    m = DATE_MMDD.match(date_str)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            year = timezone.now().year
            return f'{year}-{mm:02d}-{dd:02d}'

    return '日期格式错误'


class Command(BaseCommand):
    help = 'Normalize maintenance note dates to yyyy-mm-dd format'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        updated = 0
        errors = 0

        for zone in Zone.objects.all():
            changed = False
            for field in ('equipment_maintenance_notes', 'irrigation_management_notes'):
                raw = getattr(zone, field, '') or ''
                if not raw:
                    continue
                try:
                    entries = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(entries, list):
                    continue

                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    old_date = entry.get('date', '')
                    new_date = normalize_date(old_date)
                    if new_date != old_date:
                        entry['date'] = new_date
                        changed = True
                        if new_date == '日期格式错误':
                            errors += 1
                        if dry_run:
                            self.stdout.write(f'  [{zone.code}] "{old_date}" → "{new_date}"')

                if changed:
                    new_json = json.dumps(entries, ensure_ascii=False)
                    if new_json != raw:
                        setattr(zone, field, new_json)

            if changed:
                updated += 1
                if not dry_run:
                    zone.save(update_fields=['equipment_maintenance_notes', 'irrigation_management_notes'])

        if dry_run:
            self.stdout.write(self.style.WARNING(f'\nDRY RUN: {updated} zones, {errors} date errors'))
        else:
            self.stdout.write(self.style.SUCCESS(f'{updated} zones updated, {errors} date errors'))
