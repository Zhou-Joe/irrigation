"""
Parse free-text maintenance notes into structured JSON lists.

Format: "25/8/21报干金丝桃重浇3天24/5/施肥5/9施肥"
  → [{"date":"25/8/21","content":"报干金丝桃重浇3天"},{"date":"24/5/2","content":"施肥"}, ...]

Date patterns matched: yy/mm/dd, yy/m/d, mm/dd, m/d
"""

import json
import re

from django.core.management.base import BaseCommand
from core.models import Zone

# Match date patterns: yy/mm/dd or mm/dd (with optional leading zeros)
DATE_PATTERN = re.compile(
    r'('
    r'\d{1,2}/\d{1,2}/\d{1,2}'   # yy/mm/dd or yy/m/d
    r'|'
    r'\d{1,2}/\d{1,2}'            # mm/dd or m/d
    r')'
)


def parse_notes(text):
    """Parse free-text notes into a list of {date, content} dicts."""
    if not text or not text.strip():
        return []

    text = text.strip()

    # Check if already JSON list
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return val
    except (json.JSONDecodeError, TypeError):
        pass

    # Find all date positions
    matches = list(DATE_PATTERN.finditer(text))
    if not matches:
        # No dates found — treat entire text as one undated entry
        return [{"date": "", "content": text.strip()}]

    entries = []
    for i, match in enumerate(matches):
        date_str = match.group(1)
        content_start = match.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()
        entries.append({"date": date_str, "content": content})

    return entries


class Command(BaseCommand):
    help = 'Parse free-text maintenance notes into structured JSON lists'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without saving',
        )
        parser.add_argument(
            '--field', choices=['equipment', 'irrigation', 'both'],
            default='both', help='Which field(s) to parse',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        field = options['field']
        zones = Zone.objects.all()
        updated = 0

        for zone in zones:
            changed = False
            equip = zone.equipment_maintenance_notes or ''
            irrig = zone.irrigation_management_notes or ''

            if field in ('equipment', 'both') and equip:
                parsed = parse_notes(equip)
                if parsed and json.dumps(parsed, ensure_ascii=False) != equip:
                    zone.equipment_maintenance_notes = json.dumps(parsed, ensure_ascii=False)
                    changed = True
                    if dry_run:
                        self.stdout.write(f'[{zone.code}] equip: {equip!r}')
                        self.stdout.write(f'  → {parsed}')

            if field in ('irrigation', 'both') and irrig:
                parsed = parse_notes(irrig)
                if parsed and json.dumps(parsed, ensure_ascii=False) != irrig:
                    zone.irrigation_management_notes = json.dumps(parsed, ensure_ascii=False)
                    changed = True
                    if dry_run:
                        self.stdout.write(f'[{zone.code}] irrig: {irrig!r}')
                        self.stdout.write(f'  → {parsed}')

            if changed:
                updated += 1
                if not dry_run:
                    zone.save(update_fields=['equipment_maintenance_notes', 'irrigation_management_notes'])

        if dry_run:
            self.stdout.write(self.style.WARNING(f'\nDRY RUN: {updated} zones would be updated'))
        else:
            self.stdout.write(self.style.SUCCESS(f'{updated} zones updated'))
