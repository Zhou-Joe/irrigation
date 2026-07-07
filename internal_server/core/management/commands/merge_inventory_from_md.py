"""Incrementally merge inventory categories from 库存备件架构.md into the DB.

Unlike seed_inventory_from_xlsx (which clears + rebuilds the whole tree), this
command **adds only new nodes** — existing parts/categories are left untouched
so current_stock, transactions, and edit history are all preserved. Existing
parts get their min_stock / is_main_material / unit refreshed from the MD, but
current_stock is never reset.

The MD uses Markdown headings to encode the hierarchy:
    ## wrapper-root                 (skipped — single wrapper)
    ### top-level section
    #### sub-section
    ##### leaf-or-sub
    ###### deeper leaf

Each leaf may carry an annotation suffix:
    "主材最小库存300个"  → is_main=True, min_stock=300, unit='个'
    "主材 按需备货"      → is_main=True, min_stock=0, unit=''
    "主材 最小备货50个"  → is_main=True, min_stock=50, unit='个'
    (no annotation)      → is_main=False, min_stock=0, unit=''

Usage:
    python manage.py merge_inventory_from_md
    python manage.py merge_inventory_from_md --file /path/to/库存备件架构.md
"""

import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from core.models import InventoryCategory


# Annotation patterns. Order matters: try the numeric forms first, then bare.
_MAIN_MIN_RE = re.compile(
    r'主材\s*(?:主材)?\s*(?:最小(?:库存|备货))?\s*(\d+)\s*(个|m|米|瓶|套|根|件|盒|包|箱)?'
)
_MAIN_ONDEMAND_RE = re.compile(r'主材\s*按需备货')
_MAIN_BARE_RE = re.compile(r'主材')

# Documentation-noise headings attached at the bottom of the MD (column-header
# template under 法兰闸阀 6" — 入库/出库/去向/订单号/借用方 etc.). These are NOT
# inventory parts; skip them so they don't become junk nodes.
_DOC_NOISE_NAMES = {
    '现有库存数量', '盘库数量', '入库', '入库时间', '订单号', '借用归还', '拆回利旧',
    '预计用量', '出库', '出库时间', '去向', '日常维护', '项目', '借用', '借用方',
    '下拉选择项目名称',
}


def parse_annotation(heading_text):
    """Parse a heading's annotation suffix → (is_main_material, min_stock, unit, clean_name)."""
    text = heading_text
    is_main = False
    min_stock = 0
    unit = ''

    if '按需' in text and '主材' in text:
        is_main = True
        text = _MAIN_ONDEMAND_RE.sub('', text)
    else:
        m = _MAIN_MIN_RE.search(text)
        if m:
            is_main = True
            min_stock = int(m.group(1))
            u = m.group(2) or ''
            if u == '米':
                u = 'm'
            unit = u
            text = text[:m.start()] + text[m.end():]
        elif _MAIN_BARE_RE.search(text):
            is_main = True
            text = _MAIN_BARE_RE.sub('', text)

    name = re.sub(r'\s+', ' ', text).strip().rstrip('—-').strip()
    return is_main, min_stock, unit, name


class Command(BaseCommand):
    help = 'Incrementally merge inventory categories from 库存备件架构.md (adds new nodes only)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            default=str(settings.BASE_DIR.parent / '库存备件架构.md'),
            help='Path to 库存备件架构.md (default: <repo>/库存备件架构.md)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be added without writing to the DB.',
        )

    def handle(self, *args, **options):
        path = options['file']
        if not os.path.exists(path):
            raise CommandError(f'MD file not found: {path}')

        # ── 1. Parse the MD into a nested tree ──
        md_tree = self._parse_md(path)
        # Flatten into a list of (path_tuple, node_dict) where path is the chain
        # of names from a real top-level root down to the node.
        flat = []
        self._flatten(md_tree, (), flat)
        self.stdout.write(f'Parsed {len(flat)} nodes from MD ({len(md_tree)} top-level roots).')

        # ── 2. Build a lookup of existing DB nodes by full name-path ──
        # Keyed on the tuple of ancestor names + the node's own name, so two
        # parts with the same name under different parents don't collide.
        existing_by_path = {}
        roots = list(InventoryCategory.objects.filter(parent__isnull=True))
        def walk(node, trail):
            key = tuple(trail + [node.name_zh])
            existing_by_path.setdefault(key, node)
            for c in node.children.all():
                walk(c, trail + [node.name_zh])
        for r in roots:
            walk(r, [])

        # ── 3. Merge: add missing nodes, refresh metadata on existing parts ──
        before_count = InventoryCategory.objects.count()
        next_code = self._max_code_suffix() + 1
        added_cats = added_parts = refreshed = 0
        # path_tuple -> InventoryCategory (newly created or pre-existing), so
        # children can resolve their parent even if the parent was just added.
        path_to_obj = dict(existing_by_path)

        with db_transaction.atomic():
            for path, node in flat:
                if path in path_to_obj:
                    # Exists: refresh part metadata only (never touch current_stock).
                    obj = path_to_obj[path]
                    if obj.node_type == 'part' and not node['children']:
                        changed = False
                        if obj.min_stock != node['min']:
                            obj.min_stock = node['min']; changed = True
                        if obj.unit != node['unit']:
                            obj.unit = node['unit']; changed = True
                        if obj.is_main_material != node['is_main']:
                            obj.is_main_material = node['is_main']; changed = True
                        if changed:
                            if not options['dry_run']:
                                obj.save(update_fields=['min_stock', 'unit', 'is_main_material'])
                            refreshed += 1
                    continue
                # New node. Determine its parent from the path (all ancestors
                # must already exist or have been created earlier in this loop —
                # they do, because the MD is parsed top-down).
                parent_path = path[:-1]
                parent = path_to_obj.get(parent_path) if parent_path else None
                # If the parent path isn't in the DB but this is a top-level
                # node (parent_path empty), parent stays None. A missing
                # non-empty parent path would indicate out-of-order MD — skip.
                if parent_path and parent is None:
                    self.stdout.write(self.style.WARNING(
                        f'Skipping {node["name"]!r}: parent path {parent_path} not found.'
                    ))
                    continue
                level = len(path) - 1
                is_leaf = not node['children']
                if options['dry_run']:
                    # Use a non-None sentinel so children can still resolve this
                    # path as "exists" (a real None here would make every
                    # descendant skip with a spurious "parent not found").
                    obj = {'_dry': True, 'node_type': 'part' if is_leaf else 'category'}
                else:
                    obj = InventoryCategory.objects.create(
                        code=f'n{next_code}', parent=parent, name_zh=node['name'],
                        level=level, node_type='part' if is_leaf else 'category',
                        is_main_material=node['is_main'],
                        min_stock=node['min'] if is_leaf else 0,
                        unit=node['unit'] if is_leaf else '',
                        current_stock=0,
                    )
                next_code += 1
                # Register under the full path so subsequent children resolve.
                path_to_obj[path] = obj
                if is_leaf:
                    added_parts += 1
                else:
                    added_cats += 1

        after_count = InventoryCategory.objects.count()
        verb = 'Would add' if options['dry_run'] else 'Added'
        self.stdout.write(self.style.SUCCESS(
            f'{verb}: {added_cats} categories + {added_parts} parts; '
            f'refreshed metadata on {refreshed} existing parts. '
            f'(before={before_count}, after={after_count})'
        ))

    # ── parsing helpers ──────────────────────────────────────────────────

    def _parse_md(self, path):
        """Parse the MD into a nested tree (list of root dicts)."""
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        # Collect (depth, raw_text) for every heading. ## = depth 0.
        heads = []
        for ln in lines:
            m = re.match(r'^(#{2,6})\s+(.+?)\s*$', ln.rstrip())
            if not m:
                continue
            depth = len(m.group(1)) - 2
            heads.append((depth, m.group(2).strip()))

        # Drop a single wrapper root if present (e.g. "库存材料和工具").
        if heads and heads[0][0] == 0:
            wrapper_name = heads[0][1]
            # If the first L0 heading wraps everything (all others are deeper),
            # drop it so its children become the real top-level roots.
            if all(d > 0 for d, _ in heads[1:]):
                heads = heads[1:]

        tree, stack = [], []
        for depth, raw_text in heads:
            is_main, min_q, unit, name = parse_annotation(raw_text)
            if not name:
                continue   # skip empty headings (trailing "#### " in the MD)
            if name in _DOC_NOISE_NAMES:
                # Documentation column-headers (入库/出库/去向/订单号…) are not
                # parts — drop them and their descendants.
                continue
            node = {'name': name, 'is_main': is_main, 'min': min_q, 'unit': unit, 'children': []}
            while stack and stack[-1][0] >= depth:
                stack.pop()
            if stack:
                stack[-1][1]['children'].append(node)
            else:
                tree.append(node)
            stack.append((depth, node))
        return tree

    def _flatten(self, nodes, trail, out):
        """DFS the parsed tree into a list of (path_tuple, node_dict)."""
        for n in nodes:
            path = trail + (n['name'],)
            out.append((path, n))
            if n['children']:
                self._flatten(n['children'], path, out)

    def _max_code_suffix(self):
        """Largest numeric suffix among existing codes (n1, n2, …) — new nodes
        continue from here so codes stay globally unique."""
        mx = 0
        for code in InventoryCategory.objects.values_list('code', flat=True):
            m = re.match(r'n(\d+)$', code or '')
            if m:
                mx = max(mx, int(m.group(1)))
        return mx
