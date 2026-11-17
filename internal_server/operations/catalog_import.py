"""Read the supplied heading/bullet outline as reference data, not executable rules."""
import hashlib
import re
from pathlib import Path

from django.db import transaction
from .models import ReferenceCatalog, ReferenceNode


def parse_outline(text):
    active = False
    stack = []
    result = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if line.strip() == '## 完整层级目录':
            active = True
            continue
        if line.strip() == '## 结构说明':
            break
        if not active:
            continue
        heading = re.match(r'^(#{2,3})\s+(.+?)\s*$', line)
        bullet = re.match(r'^( *)-\s+(.+?)\s*$', line)
        if heading:
            level = len(heading[1])
            label = heading[2]
            kind = 'node'
        elif bullet:
            if len(bullet[1]) % 2:
                raise ValueError(f'第 {line_no} 行缩进不是两空格层级，请核对原文。')
            level = 4 + len(bullet[1]) // 2
            label = bullet[2]
            kind = 'note' if label.startswith('↳') else 'node'
            label = label.removeprefix('↳').strip()
            if label.startswith('**') and label.endswith('**'):
                label = label[2:-2]
        else:
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        if level > 2 and (not stack or level > stack[-1][0] + 1):
            raise ValueError(f'第 {line_no} 行缺少上级节点。')
        parent = stack[-1][1] if stack else None
        result.append({'label': label, 'kind': kind, 'source_line': line_no, 'parent_index': parent})
        stack.append((level, len(result) - 1))
    if not result:
        raise ValueError('未找到完整层级目录，请使用 PM管理_层级结构整理版.md 格式。')
    return result


@transaction.atomic
def import_reference(path, business):
    path = Path(path)
    text = path.read_text(encoding='utf-8-sig')
    parsed = parse_outline(text)
    version = hashlib.sha256(text.encode()).hexdigest()
    catalog, created = ReferenceCatalog.objects.get_or_create(business=business, version=version, defaults={
        'name': 'Pest Management · 工作参考目录', 'source_name': path.name})
    if created:
        nodes = []
        for index, item in enumerate(parsed):
            parent_index = item.pop('parent_index')
            nodes.append(ReferenceNode.objects.create(catalog=catalog,
                parent=nodes[parent_index] if parent_index is not None else None, order=index, **item))
    return catalog, created
