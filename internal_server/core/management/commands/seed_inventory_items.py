"""Seed the InventoryCategory catalog tree from 库存管理tree.md.

Idempotent: upserts by ``code``. Run after migration 0068:

    python manage.py seed_inventory_items
    python manage.py seed_inventory_items --file /path/to/库存管理tree.md --clear

Parsing lives in core.inventory_tree_parser (pure function, no Django).
Existing ``current_stock`` values are preserved on update (not overwritten).
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import InventoryCategory
from core.inventory_tree_parser import parse_inventory_tree


class Command(BaseCommand):
    help = 'Seed the InventoryCategory catalog tree from 库存管理tree.md'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            default=str(settings.BASE_DIR.parent / '库存管理tree.md'),
            help='Path to the markdown spec (default: <repo>/库存管理tree.md)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing InventoryCategory rows before seeding (dev only).',
        )

    def handle(self, *args, **options):
        path = options['file']
        if not os.path.exists(path):
            self.stderr.write(self.style.ERROR(f'Spec file not found: {path}'))
            return

        if options['clear']:
            # InventoryCategory is referenced by InventoryTransactionLine (PROTECTED).
            from core.models import InventoryTransactionLine
            if InventoryTransactionLine.objects.exists():
                self.stderr.write(self.style.ERROR(
                    'Refusing --clear: InventoryTransactionLine rows exist and '
                    'InventoryCategory is PROTECTED. Remove the transactions first.'
                ))
                return
            deleted, _ = InventoryCategory.objects.all().delete()
            self.stdout.write(f'Cleared {deleted} existing InventoryCategory rows.')

        text = open(path, encoding='utf-8').read()
        rows = parse_inventory_tree(text)

        created = updated = 0
        cache = {}  # code -> InventoryCategory

        # Rows are depth-first pre-order, so a parent is always seeded first.
        for row in rows:
            parent = cache.get(row['parent_code']) if row['parent_code'] else None
            obj, was_created = InventoryCategory.objects.update_or_create(
                code=row['code'],
                defaults={
                    'parent': parent,
                    'name_zh': row['name_zh'],
                    'order': row['order'],
                    'level': row['level'],
                    'active': True,
                    # NOTE: current_stock intentionally NOT in defaults —
                    # preserve manager-set values on re-seed.
                },
            )
            cache[row['code']] = obj
            if was_created:
                created += 1
            else:
                updated += 1

        # Leaf count (no children) = pickable items.
        leaves = sum(1 for c in InventoryCategory.objects.all()
                     if not c.children.exists())

        self.stdout.write(self.style.SUCCESS(
            f'InventoryCategory: {created} created, {updated} updated '
            f'({len(rows)} total, {leaves} pickable leaves).'
        ))
