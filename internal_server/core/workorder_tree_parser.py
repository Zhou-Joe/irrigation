"""Parser: 工单记录格式.md → flat list of WorkItem template nodes.

Produces the work-content tree (现场作业记录 · 工作内容) per
docs/superpowers/specs/2026-06-16-workorder-form-refactor-design.md.

Transformations applied (see module docstring of design §4):
  * Keep only nodes under 1.1.13.* (10 sections) + 1.1.14 / 1.1.15.
    Header fields 1.1.1–1.1.12 map to WorkReport columns, not the tree.
  * Collapse 灌溉项目 (1.1.13.2): keep ONE shared project template (项目1 under
    FAM) re-parented under 灌溉项目; drop FAM/WDI headers and extra 项目N
    subtrees — projects are admin-managed instances, not fixed tree nodes.
  * Absorb count indicators (弹出数量 / 下拉数量, optionally '单位X') into their
    owning leaf — whether the indicator is a child (BOM style) or the following
    sibling (maintenance style).
  * Infer value_type: group / count / text_photo. Status / text are left for
    admin refinement (model supports them).
"""

import re

HEADER_RE = re.compile(r'^(?P<indent>\s*)-\s+\*\*(?P<code>\d+(?:\.\d+)*)\s+(?P<name>.+?)\*\*\s*$')
LEAF_RE = re.compile(r'^(?P<indent>\s*)-\s+(?P<name>.+?)\s*$')

# Top-level section dotted-code → WorkItem.section key.
SECTION_BY_PREFIX = [
    ('1.1.13.1', 'routine_maint'),
    ('1.1.13.2', 'irrigation_project'),
    ('1.1.13.3', 'routine_support'),
    ('1.1.13.4', 'greenhouse_nursery'),
    ('1.1.13.5', 'warehouse'),
    ('1.1.13.6', 'meeting_training'),
    ('1.1.13.7', 'repair_emergency'),
    ('1.1.13.8', 'other_project'),
    ('1.1.13.9', 'drainage_project'),
    ('1.1.13.10', 'typhoon_emergency'),
    ('1.1.14', 'safety_incident'),
    ('1.1.15', 'good_deed'),
]
SECTION_ROOT_CODES = {prefix for prefix, _ in SECTION_BY_PREFIX}
SECTION_KEY_BY_CODE = {prefix: key for prefix, key in SECTION_BY_PREFIX}

COUNT_INDICATOR_RE = re.compile(r'^(?:弹出|下拉)数量(?:\s+单位(?P<unit>\S+))?$')
MEMO_LEAF = '需自行填写 上传做备忘'


class _Node:
    __slots__ = ('name', 'code', 'indent', 'section', 'parent', 'children',
                 'order', 'value_type', 'unit', 'is_project_scoped')

    def __init__(self, name, code, indent, section):
        self.name = name
        self.code = code            # original dotted code (headers) or None (leaves)
        self.indent = indent
        self.section = section
        self.parent = None
        self.children = []
        self.order = 0
        self.value_type = 'count'   # default; refined later
        self.unit = ''
        self.is_project_scoped = False


def _section_for_code(code):
    for prefix, key in SECTION_BY_PREFIX:
        if code == prefix or code.startswith(prefix + '.'):
            return key
    return None


def _parse_count_indicator(name):
    """Return (is_indicator, unit) for a count-indicator leaf name."""
    m = COUNT_INDICATOR_RE.match(name.strip())
    if not m:
        return False, ''
    return True, (m.group('unit') or '')


def _build_raw_tree(text):
    """Parse lines into an indent-based tree. Returns synthetic root _Node."""
    root = _Node('__root__', None, -1, None)
    stack = [root]

    for line in text.splitlines():
        if not line.strip():
            continue
        # Skip stray **bold** lines that aren't valid headers (else LEAF_RE
        # would treat '**foo**' as a leaf name).
        if '**' in line and not HEADER_RE.match(line):
            continue
        m = HEADER_RE.match(line)
        is_header = bool(m)
        if not m:
            m = LEAF_RE.match(line)
            if not m:
                continue
        indent = len(m.group('indent'))
        code = m.group('code') if is_header else None
        name = m.group('name').strip()

        # Pop stack until parent indent < current.
        while len(stack) > 1 and stack[-1].indent >= indent:
            stack.pop()
        parent = stack[-1]

        own_section = _section_for_code(code) if is_header else None
        section = own_section or parent.section

        node = _Node(name, code, indent, section)
        node.parent = parent
        parent.children.append(node)
        stack.append(node)

    return root


def _prune_outside_sections(root):
    """Re-root onto the 12 section-root nodes; drop everything above them
    (中心主题, header fields 1.1.1–1.1.12, metadata, 1.2 分支主题3)."""
    section_roots = []

    def _collect(node):
        for ch in node.children:
            if ch.code in SECTION_ROOT_CODES:
                section_roots.append(ch)
            else:
                _collect(ch)

    _collect(root)
    for sr in section_roots:
        sr.parent = None
    root.children = section_roots


def _collapse_irrigation_projects(root):
    """Collapse 灌溉项目 duplicate project templates into one shared template."""
    irrigation = None
    for c in root.children:
        if c.section == 'irrigation_project':
            irrigation = c
            break
    if irrigation is None:
        return

    # Find first descendant node whose name starts with 项目 (项目1 under FAM).
    first_proj = None
    for fam_wdi in irrigation.children:           # FAM项目 / WDI项目
        for proj in fam_wdi.children:             # 项目1 / 项目2 / 项目...
            if proj.name.startswith('项目'):
                first_proj = proj
                break
        if first_proj:
            break

    # Re-parent 项目1's template children onto 灌溉项目; drop everything else.
    irrigation.children = list(first_proj.children) if first_proj else []

    def _mark(node):
        node.is_project_scoped = True
        for ch in node.children:
            _mark(ch)
    _mark(irrigation)


def _absorb_count_indicators(root):
    """Absorb 弹出数量/下拉数量 into owning leaf (child-style and sibling-style)."""
    def _walk(node):
        if node.children:
            kept = []
            kids = node.children
            i = 0
            while i < len(kids):
                child = kids[i]
                # Child-style: child's own children are all count indicators.
                if child.children and all(_parse_count_indicator(c.name)[0] for c in child.children):
                    child.value_type = 'count'
                    child.unit = _parse_count_indicator(child.children[0].name)[1]
                    child.children = []
                    kept.append(child)
                    i += 1
                    continue
                # Sibling-style: next sibling is this child's count indicator.
                if i + 1 < len(kids) and _parse_count_indicator(kids[i + 1].name)[0]:
                    child.value_type = 'count'
                    child.unit = _parse_count_indicator(kids[i + 1].name)[1]
                    kept.append(child)
                    i += 2  # drop the indicator sibling
                    continue
                kept.append(child)
                i += 1
            # Drop any orphan count indicators that survived (no preceding leaf).
            node.children = [k for k in kept if not _parse_count_indicator(k.name)[0]]
        for ch in node.children:
            _walk(ch)

    for top in root.children:
        _walk(top)


def _assign_value_types(root):
    for top in root.children:
        _assign_subtree(top, is_root=True)


def _assign_subtree(node, is_root):
    if is_root:
        node.value_type = 'group'  # section roots are always containers
    elif node.name == MEMO_LEAF:
        node.value_type = 'text_photo'
    elif node.children:
        node.value_type = 'group'
    else:
        node.value_type = 'count'
    for i, ch in enumerate(node.children):
        ch.order = i + 1
        _assign_subtree(ch, is_root=False)


def _emit(root):
    rows = []

    def _walk(node, parent_code, level):
        for ch in node.children:
            code = ch.code if ch.code else f'{parent_code}.{ch.order}'
            rows.append({
                'code': code,
                'parent_code': parent_code,
                'name_zh': ch.name,
                'order': ch.order,
                'level': level,
                'section': ch.section,
                'value_type': ch.value_type,
                'unit': ch.unit,
                'is_project_scoped': ch.is_project_scoped,
            })
            _walk(ch, code, level + 1)

    _walk(root, None, 0)
    return rows


def parse_workorder_tree(text):
    """Parse the markdown text and return a flat list of WorkItem node dicts."""
    root = _build_raw_tree(text)
    _prune_outside_sections(root)
    _collapse_irrigation_projects(root)
    _absorb_count_indicators(root)
    _assign_value_types(root)
    return _emit(root)
