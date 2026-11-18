"""Seed WorkItem template tree from 工单记录格式.md.

Idempotent: upserts by ``code``. Run after the new models are migrated:

    python manage.py seed_work_items
    python manage.py seed_work_items --file /path/to/工单记录格式.md --clear

Parsing lives in core.workorder_tree_parser (pure function, no Django).
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import WorkItem
from core.workorder_tree_parser import parse_workorder_tree


class Command(BaseCommand):
    help = 'Seed the WorkItem work-content template tree from 工单记录格式.md'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            help='Path to the markdown spec (default: <repo>/现场作业记录.md)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing WorkItem rows before seeding (dev only).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options['file'] or settings.BASE_DIR.parent / '现场作业记录.md')
        if not path.is_file():
            if not options['file'] and not options['clear'] and self._ensure_pm_item():
                self.stdout.write('已核对现有目录中的 PM 作业项。完整导入需提供现场作业记录.md。')
                return
            raise CommandError(f'Spec file not found: {path}')

        rows = parse_workorder_tree(path.read_text(encoding='utf-8'))
        if not rows:
            raise CommandError(f'No work items found in {path}')

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
                    # level is auto-managed by MPTT now (removed manual field);
                    # save() recomputes it from the parent chain.
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

        self._ensure_pm_item()
        self.stdout.write(self.style.SUCCESS(
            f'WorkItem: {created} created, {updated} updated ({len(rows)} total).'
        ))
        self._print_breakdown()

    def _ensure_pm_item(self):
        parent = WorkItem.objects.filter(code='1.2').first()
        if parent is None:
            return False
        WorkItem.objects.update_or_create(code='1.2.pm', defaults={
            'parent': parent, 'name_zh': 'PM作业计划', 'name_en': 'PM Job Plan',
            'order': 999, 'section': 'routine_maint', 'value_type': 'text',
            'is_project_scoped': False, 'active': True,
        })
        return True

    def _print_breakdown(self):
        from django.db.models import Count

        def _hist(field):
            qs = WorkItem.objects.values(field).annotate(n=Count('id'))
            return {r[field]: r['n'] for r in qs}

        sec = _hist('section')
        vt = _hist('value_type')
        self.stdout.write('By section: ' + ', '.join(f'{k}={v}' for k, v in sorted(sec.items())))
        self.stdout.write('By value_type: ' + ', '.join(f'{k}={v}' for k, v in sorted(vt.items())))
