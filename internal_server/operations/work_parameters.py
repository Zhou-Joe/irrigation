"""Work-specific observations and building-bound fields, with issued-value snapshots.

ReferenceNode definitions inherit down the work tree. A ``location`` definition
requests the identically keyed field from each selected building's definitions;
that makes, for example, impact direction a property of the building being
observed instead of a single direction accidentally applied to every location.
"""
import json
import math
import re
from datetime import date, time


PARAMETER_TYPES = frozenset({'text', 'choice', 'integer', 'number', 'date', 'time', 'location'})
EMPTY_VALUES = {'work': [], 'locations': []}


def definitions(value, *, allow_location=True):
    """Validate the small administrative configuration, never executable JSON."""
    if value is None or value == '':
        value = []
    if isinstance(value, str):
        if len(value) > 30000:
            raise ValueError('参数配置过长。')
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError('参数配置应为有效的 JSON 列表。') from None
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError('参数配置应为列表，最多 32 个参数。')
    result = []; keys = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {'key', 'label', 'type', 'required', 'options', 'unit'}:
            raise ValueError('参数配置包含无效的字段。')
        key = item.get('key'); label = item.get('label'); kind = item.get('type', 'text')
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', key) or key in keys:
            raise ValueError('参数 key 应为唯一的小写英文编号（可含数字和下划线）。')
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100:
            raise ValueError('参数名称应为 1–100 字。')
        if not isinstance(kind, str) or kind not in PARAMETER_TYPES or (kind == 'location' and not allow_location):
            raise ValueError('参数类型无效。')
        required = item.get('required', False)
        if type(required) is not bool:
            raise ValueError('required 应为 true 或 false。')
        clean = {'key': key, 'label': label.strip(), 'type': kind, 'required': required}
        if 'unit' in item:
            if not isinstance(item['unit'], str) or len(item['unit']) > 20:
                raise ValueError('参数单位最多 20 字。')
            clean['unit'] = item['unit']
        if kind == 'choice':
            options = item.get('options', [])
            if not isinstance(options, list) or not 1 <= len(options) <= 100:
                raise ValueError('选项参数需要 1–100 个选项。')
            choices = []; identifiers = set()
            for option in options:
                if isinstance(option, str):
                    option = {'value': option, 'label': option}
                if not isinstance(option, dict) or set(option) != {'value', 'label'} or any(
                    not isinstance(option.get(k), str) or not 1 <= len(option[k]) <= 200 for k in ('value', 'label')):
                    raise ValueError('选项应为文字，或包含 value 和 label 的对象。')
                if option['value'] in identifiers:
                    raise ValueError('参数选项不能重复。')
                identifiers.add(option['value']); choices.append(dict(option))
            clean['options'] = choices
        elif 'options' in item:
            raise ValueError('只有 choice 类型可设置 options。')
        result.append(clean); keys.add(key)
    return result


def form_schema(catalog, locations, values=None):
    """Only pass locations visible to the active team, including no private parents."""
    return {'nodes': [{'id': str(n.pk), 'parent': str(n.parent_id or ''), 'name': n.label,
                       'parameters': definitions(n.parameters)} for n in catalog.nodes.all()],
            'locations': [{'id': str(p.pk), 'parent': str(p.parent_id or ''), 'name': p.name,
                           'parameters': definitions(p.parameters, allow_location=False)} for p in locations],
            'values': values or {'work': [], 'locations': []}}


def _inherited(items, identifier):
    path = []; seen = set(); item = items.get(str(identifier))
    while item:
        if item['id'] in seen:
            raise ValueError('参数层级存在循环。')
        seen.add(item['id']); path.insert(0, item)
        item = items.get(str(item.get('parent', '')))
    fields = {}
    for item in path:
        for field in item['parameters']:
            fields[field['key']] = {**field, 'owner_id': item['id'], 'owner_label': item['name']}
    return list(fields.values())


def applicable_fields(schema, node_ids, location_ids):
    nodes = {n['id']: n for n in schema['nodes']}; places = {p['id']: p for p in schema['locations']}
    work = {}; bindings = {}
    for identifier in sorted(str(n) for n in node_ids):
        for field in _inherited(nodes, identifier):
            target = bindings if field['type'] == 'location' else work
            previous = target.get(field['key'])
            # Different requested work items must not silently overwrite one another.
            if previous and {k: v for k, v in previous.items() if not k.startswith('owner_')} != {
                k: v for k, v in field.items() if not k.startswith('owner_')}:
                raise ValueError('所选工作内容使用了冲突的参数，请分别提交。')
            target[field['key']] = field
    location_fields = {}
    for identifier in sorted(str(p) for p in location_ids):
        inherited = _inherited(places, identifier)
        inherited_keys = {field['key'] for field in inherited}
        for binding in bindings.values():
            if binding['required'] and binding['key'] not in inherited_keys:
                raise ValueError(f'所选地点尚未配置{binding["label"]}，请联系团队经理。')
        for field in inherited:
            if field['key'] not in bindings:
                continue
            field = {**field, 'required': field['required'] or bindings[field['key']]['required']}
            location_fields[(field['owner_id'], field['key'])] = field
    if set(work).intersection(bindings):
        raise ValueError('所选工作内容使用了冲突的参数，请分别提交。')
    return {'work': list(work.values()), 'locations': list(location_fields.values())}


def _clean_value(field, value):
    if value is None or value == '':
        if field['required']:
            raise ValueError(f'请填写{field["label"]}。')
        return None, ''
    kind = field['type']
    if kind == 'text':
        if not isinstance(value, str) or len(value) > 2000:
            raise ValueError(f'{field["label"]}最多支持 2000 字。')
        if field['required'] and not value.strip():
            raise ValueError(f'请填写{field["label"]}。')
        return value.strip() or None, value.strip()
    if kind == 'choice':
        for option in field['options']:
            if value == option['value']:
                return value, option['label']
        raise ValueError(f'请重新选择{field["label"]}。')
    if kind in ('integer', 'number'):
        if isinstance(value, bool):
            raise ValueError(f'{field["label"]}应为有效数字。')
        try:
            number = float(value)
            if not math.isfinite(number) or abs(number) > 1e15 or (kind == 'integer' and not number.is_integer()):
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f'{field["label"]}应为有效数字。') from None
        value = int(number) if kind == 'integer' else number
        return value, str(value)
    if not isinstance(value, str):
        raise ValueError(f'请核对{field["label"]}的格式。')
    try:
        if kind == 'date':
            clean = date.fromisoformat(value).isoformat()
        else:
            parsed = time.fromisoformat(value)
            if parsed.tzinfo is not None:
                raise ValueError
            clean = parsed.isoformat(timespec='minutes' if not parsed.second else 'seconds')
    except ValueError:
        raise ValueError(f'请核对{field["label"]}的格式。') from None
    return clean, clean


def parameter_snapshot(catalog, node_ids, locations, raw_values, *, available_locations, previous=None):
    """Validate against visible definitions; labels are supplied exclusively by server."""
    if isinstance(raw_values, str):
        if len(raw_values) > 100000:
            raise ValueError('参数内容过长。')
        try:
            raw_values = json.loads(raw_values or '{}')
        except ValueError:
            raise ValueError('参数格式无效。') from None
    if raw_values is None:
        raw_values = {'work': [], 'locations': []}
    if not isinstance(raw_values, dict) or set(raw_values) - {'work', 'locations'}:
        raise ValueError('参数格式无效。')
    schema = form_schema(catalog, available_locations)
    active = applicable_fields(schema, node_ids, [p.pk for p in locations])
    saved = {'work': [], 'locations': []}
    old = previous or {'work': [], 'locations': []}
    for section in saved:
        submitted = raw_values.get(section, [])
        if not isinstance(submitted, list) or len(submitted) > 1000:
            raise ValueError('参数内容无效。')
        by_key = {}
        for item in submitted:
            if not isinstance(item, dict) or set(item) - {'key', 'location_id', 'value'}:
                raise ValueError('参数内容无效。')
            if not isinstance(item.get('key'), str) or (section == 'work' and item.get('location_id')):
                raise ValueError('参数编号无效。')
            key = (str(item.get('location_id', '')) if section == 'locations' else '', item.get('key'))
            if key in by_key:
                raise ValueError('参数不能重复。')
            by_key[key] = item.get('value')
        accepted = set()
        for field in active[section]:
            location_id = field['owner_id'] if section == 'locations' else ''
            key = (location_id, field['key']); accepted.add(key)
            value = by_key.get(key)
            try:
                clean, label = _clean_value(field, value)
            except ValueError:
                # An unchanged historical option remains valid for an edit, even
                # after its building's configuration has retired that option.
                prior = next((p for p in old.get(section, []) if p.get('key') == field['key'] and
                              str(p.get('location_id', '')) == location_id and p.get('value') == value), None)
                if field['type'] != 'choice' or prior is None or value in (None, ''):
                    raise
                clean, label = value, prior.get('value_label', str(value))
            item = {'key': field['key'], 'label': field['label'], 'type': field['type'],
                    'value': clean, 'value_label': label}
            if field.get('unit'):
                item['unit'] = field['unit']
            if section == 'locations':
                item.update(location_id=location_id, location_label=field['owner_label'])
            saved[section].append(item)
        if set(by_key) - accepted:
            raise ValueError('参数不属于所选的工作内容或建筑，请重新打开表单。')
    return saved
