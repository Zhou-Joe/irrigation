"""Seed WorkItem template tree from 工单记录格式.md.

Idempotent: upserts by ``code``. Run after the new models are migrated:

    python manage.py seed_work_items
    python manage.py seed_work_items --file /path/to/工单记录格式.md --clear

Parsing lives in core.workorder_tree_parser (pure function, no Django).
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import WorkItem
from core.workorder_tree_parser import parse_workorder_tree


class Command(BaseCommand):
    help = 'Seed the WorkItem work-content template tree from 工单记录格式.md'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            default=str(settings.BASE_DIR.parent / '现场作业记录.md'),
            help='Path to the markdown spec (default: <repo>/现场作业记录.md)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing WorkItem rows before seeding (dev only).',
        )

    def handle(self, *args, **options):
        path = options['file']
        if not os.path.exists(path):
            self.stderr.write(self.style.ERROR(f'Spec file not found: {path}'))
            return

        if options['clear']:
            from core.models import WorkReportEntry
            if WorkReportEntry.objects.exists():
                self.stderr.write(self.style.ERROR(
                    'Refusing --clear: WorkReportEntry rows exist and WorkItem '
                    'is PROTECTED. Remove the report entries first.'
                ))
                return
            deleted, _ = WorkItem.objects.all().delete()
            self.stdout.write(f'Cleared {deleted} existing WorkItem rows.')

        text = open(path, encoding='utf-8').read()
        rows = parse_workorder_tree(text)

        created = updated = 0
        cache = {}  # code -> WorkItem

        # Rows are depth-first pre-order, so a parent is always seeded first.
        for row in rows:
            parent = cache.get(row['parent_code']) if row['parent_code'] else None
            obj, was_created = WorkItem.objects.update_or_create(
                code=row['code'],
                defaults={
                    'parent': parent,
                    'name_zh': row['name_zh'],
                    'order': row['order'],
                    'level': row['level'],
                    'section': row['section'],
                    'value_type': row['value_type'],
                    'unit': row['unit'],
                    'is_project_scoped': row['is_project_scoped'],
                    'active': True,
                },
            )
            cache[row['code']] = obj
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'WorkItem: {created} created, {updated} updated ({len(rows)} total).'
        ))
        self._print_breakdown()

    def _print_breakdown(self):
        from django.db.models import Count

        def _hist(field):
            qs = WorkItem.objects.values(field).annotate(n=Count('id'))
            return {r[field]: r['n'] for r in qs}

        sec = _hist('section')
        vt = _hist('value_type')
        self.stdout.write('By section: ' + ', '.join(f'{k}={v}' for k, v in sorted(sec.items())))
        self.stdout.write('By value_type: ' + ', '.join(f'{k}={v}' for k, v in sorted(vt.items())))
