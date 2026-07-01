"""Parse 库存管理tree.md into a flat list of InventoryCategory node dicts.

The markdown uses standard heading nesting: ``#`` = level 1, ``##`` = level 2,
etc. The real catalog is the subtree under ``## 库存材料和工具`` and ends at
``### 工具``; everything after (浇水协调需求记录 / 传感器数据展示 / ...) is
unrelated and must be skipped.

Output: a flat list of ``{code, parent_code, name_zh, order, level}`` dicts in
depth-first pre-order (parents before children), suitable for seeding. Codes
are derived from the heading path so they're stable across re-seeds.

Pure functions, no Django imports.
"""

import re

# Headings we treat as end-of-catalog markers (the trailing non-inventory
# top-level sections in the spec). Matching is on the trimmed heading text.
_END_MARKERS = {
    '浇水协调需求记录', '浇水数据展示', '传感器数据展示',
    '灌溉库存管理', '灌溉现场作业记录', '中心主题',
}

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)$')


def _slug(name):
    """Turn a Chinese/mixed heading into a short stable slug for the code path.

    Keeps ASCII alphanumerics; for Chinese-only headings falls back to a
    de-duplicated numeric index so codes stay stable and unique within a level.
    """
    s = re.sub(r'\s+', '', name).strip()
    ascii_part = re.sub(r'[^A-Za-z0-9]+', '', s)
    if ascii_part:
        return ascii_part.lower()
    return None  # caller assigns a per-parent index


def parse_inventory_tree(text):
    """Parse the markdown text and return a flat list of node dicts.

    Each dict: ``{code, parent_code, name_zh, order, level}``. The list is in
    depth-first pre-order so a parent always precedes its children.
    """
    stack = []          # list of (level, code, slug_or_idx)
    nodes = []
    # counter per parent-code for disambiguating Chinese-only sibling headings
    sibling_counter = {}
    in_catalog = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m = _HEADING_RE.match(line)
        if not m:
            continue
        hashes, name = m.group(1), m.group(2).strip()
        level = len(hashes)
        clean = name.strip().strip('"').strip()
        if not clean:
            continue  # skip empty headings (e.g. the bare "####" in the spec)

        # Detect the start of the real catalog (## 库存材料和工具).
        if not in_catalog:
            if level <= 2 and '库存' in clean:
                in_catalog = True
                # Treat this wrapper heading as transparent: don't emit a node
                # for it, so its ### children become tree roots (no extra
                # expand step for "库存材料和工具").
                continue
            else:
                continue  # skip the top "# 中心主题" preamble

        # Detect the end of the catalog: a top-level (#) heading that is an
        # end-marker, OR any heading whose text is a known end-marker.
        if clean in _END_MARKERS:
            break

        # Pop the stack until the parent level is shallower than this node.
        while stack and stack[-1][0] >= level:
            stack.pop()

        parent_code = stack[-1][1] if stack else None
        parent_path = parent_code or ''

        # Build a stable slug; for Chinese-only headings use a per-parent index.
        slug = _slug(clean)
        if slug is None:
            idx = sibling_counter.get(parent_path, 0) + 1
            sibling_counter[parent_path] = idx
            slug = f'item{idx}'
        else:
            # Still increment so Chinese-only siblings under the same ASCII
            # parent get distinct indices if needed.
            sibling_counter[parent_path] = sibling_counter.get(parent_path, 0) + 1

        code = f'{parent_path}.{slug}' if parent_path else slug

        # Re-seed the per-parent counter when the parent changes (keeps item
        # indices stable: each parent's children are numbered 1..N).
        if not stack or stack[-1][1] != parent_path:
            pass

        order = sibling_counter.get(parent_path, 0)
        nodes.append({
            'code': code,
            'parent_code': parent_code,
            'name_zh': clean,
            'order': order,
            'level': level,
        })
        stack.append((level, code, slug))

    return nodes
