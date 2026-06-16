"""Parser: 现场作业记录.md → flat list of WorkItem template nodes.

Parses the ``--|__ <name>`` indentation tree (the canonical 现场作业记录 spec).
Value rules (per requirements):
  * A node whose child is ``弹出数量`` / ``下拉数量`` is a **count** leaf (fill a number).
  * A node with other children is a **group** (container, drill down).
  * A bare leaf (no children, no 弹出数量) is a **toggle** leaf (selectable, no number) —
    e.g. 待修 / 功能正常 / 断.
灌溉项目 (FAM项目/WDI项目 → 项目1/项目2 → template) is collapsed into ONE shared
project template re-parented under 灌溉项目 (is_project_scoped=True); project instances
are admin-managed via the Project model.
"""

import re

LINE_RE = re.compile(r'^(?P<indent>\s*)--\|__\s+(?P<name>.+?)\s*$')

SECTION_KEY_BY_NAME = {
    '常规维护': 'routine_maint',
    '灌溉项目': 'irrigation_project',
    '常规配合': 'routine_support',
    '温室和苗圃维护': 'greenhouse_nursery',
    '仓库整理': 'warehouse',
    '会议和培训': 'meeting_training',
    '报修应急': 'repair_emergency',
    '其他项目': 'other_project',
    '排水项目': 'drainage_project',
    '台风应急': 'typhoon_emergency',
    '安全事件记录': 'safety_incident',
    '优秀事迹记录': 'good_deed',
}
COUNT_MARKERS = ('弹出数量', '下拉数量')
COUNT_MARKER_RE = re.compile(r'^(?:弹出|下拉)数量(?:\s+单位(?P<unit>\S+))?$')


class _Node:
    __slots__ = ('name', 'indent', 'section', 'parent', 'children', 'order',
                 'value_type', 'unit', 'is_project_scoped', 'is_count')

    def __init__(self, name, indent, section):
        self.name = name
        self.indent = indent
        self.section = section
        self.parent = None
        self.children = []
        self.order = 0
        self.value_type = 'toggle'   # default; refined later
        self.unit = ''
        self.is_project_scoped = False
        self.is_count = False


def _build_raw_tree(text):
    """Parse ``--|__`` lines into an indent-based tree. Returns synthetic root."""
    root = _Node('__root__', -1, None)
    stack = [root]
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        indent = len(m.group('indent'))
        name = m.group('name').strip()
        while len(stack) > 1 and stack[-1].indent >= indent:
            stack.pop()
        parent = stack[-1]
        node = _Node(name, indent, parent.section)
        node.parent = parent
        parent.children.append(node)
        stack.append(node)
    return root


def _collect_sections(root):
    """工作内容's direct children are the section roots."""
    work_content = next((c for c in root.children if c.name == '工作内容'), None)
    return list(work_content.children) if work_content else []


def _prune_and_assign_sections(sections):
    """Keep only recognized section roots; tag every descendant with its section key."""
    kept = []
    for s in sections:
        key = SECTION_KEY_BY_NAME.get(s.name)
        if not key:
            continue

        def _tag(n):
            n.section = key
            for c in n.children:
                _tag(c)

        _tag(s)
        s.parent = None
        kept.append(s)
    return kept


def _collapse_irrigation_projects(sections):
    """Collapse 灌溉项目 → FAM/WDI → 项目1/项目2 duplication into one shared template."""
    irrigation = next((s for s in sections if s.section == 'irrigation_project'), None)
    if irrigation is None:
        return
    first_proj = None
    for fam_wdi in irrigation.children:          # FAM项目 / WDI项目
        for proj in fam_wdi.children:            # 项目1 / 项目2
            if proj.name.startswith('项目'):
                first_proj = proj
                break
        if first_proj:
            break
    irrigation.children = list(first_proj.children) if first_proj else []

    def _mark(n):
        n.is_project_scoped = True
        for c in n.children:
            _mark(c)
    _mark(irrigation)


def _clone_subtree(node, section):
    """Deep-copy a template _Node subtree, re-tagged to the destination section."""
    c = _Node(node.name, node.indent, section)
    c.is_count = node.is_count
    c.unit = node.unit
    c.is_project_scoped = True
    c.children = [_clone_subtree(ch, section) for ch in node.children]
    return c


def _share_project_template(sections):
    """Copy 灌溉项目's shared template (设计/费用评估/材料准备/施工/…) onto 排水项目 and 其他项目,
    and mark all three project sections is_project_scoped. Drops their stale placeholder children."""
    irrigation = next((s for s in sections if s.section == 'irrigation_project'), None)
    if irrigation is None or not irrigation.children:
        return
    template = irrigation.children
    for sec_key in ('drainage_project', 'other_project'):
        root = next((s for s in sections if s.section == sec_key), None)
        if root is None:
            continue
        root.children = [_clone_subtree(c, sec_key) for c in template]
        root.is_project_scoped = True


def _absorb_count_markers(sections):
    """A child named 弹出数量/下拉数量 marks its parent as a count leaf; strip the marker."""
    def _walk(n):
        kept = []
        for c in n.children:
            m = COUNT_MARKER_RE.match(c.name.strip())
            if m:
                n.is_count = True
                if m.group('unit'):
                    n.unit = m.group('unit')
                continue
            kept.append(c)
        n.children = kept
        for c in n.children:
            _walk(c)

    for s in sections:
        _walk(s)


def _assign_value_types(sections):
    def _walk(n, is_root):
        if is_root:
            n.value_type = 'group'                  # section roots are always containers
        elif n.children:
            n.value_type = 'group'
        elif n.is_count:
            n.value_type = 'count'
        else:
            n.value_type = 'toggle'
        for i, c in enumerate(n.children):
            c.order = i + 1
            _walk(c, is_root=False)

    for i, s in enumerate(sections):
        s.order = i + 1
        _walk(s, is_root=True)


def _emit(sections):
    rows = []

    def _walk(node, parent_code, level):
        for ch in node.children:
            code = f'{parent_code}.{ch.order}' if parent_code else str(ch.order)
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

    for s in sections:
        rows.append({
            'code': str(s.order),
            'parent_code': None,
            'name_zh': s.name,
            'order': s.order,
            'level': 0,
            'section': s.section,
            'value_type': s.value_type,
            'unit': s.unit,
            'is_project_scoped': s.is_project_scoped,
        })
        _walk(s, str(s.order), 1)
    return rows


def parse_workorder_tree(text):
    """Parse the markdown text and return a flat list of WorkItem node dicts."""
    root = _build_raw_tree(text)
    sections = _collect_sections(root)
    sections = _prune_and_assign_sections(sections)
    _collapse_irrigation_projects(sections)
    _share_project_template(sections)
    _absorb_count_markers(sections)
    _assign_value_types(sections)
    return _emit(sections)
