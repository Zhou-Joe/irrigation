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
IMPACT_DIRECTION = 'impact_direction'
EDITABLE_BIRD_FIELDS = frozenset({'object_name', 'species_alpha_code'})
AUTOMATIC_WORK_FIELDS = frozenset({'reported_by', 'weather'})
HIDDEN_FORM_FIELDS = AUTOMATIC_WORK_FIELDS | {'notes'}
DEFAULT_DIRECTIONS = [
    {'value': 'E', 'label': '东'}, {'value': 'S', 'label': '南'},
    {'value': 'W', 'label': '西'}, {'value': 'N', 'label': '北'},
]


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


def location_schema(locations):
    places = {str(p.pk): {'id': str(p.pk), 'parent': str(p.parent_id or ''), 'name': p.name,
                         'kind': p.kind, 'parameters': definitions(p.parameters, allow_location=False)}
              for p in locations}
    # Resolve parents first so an unconfigured annex inherits its building's
    # existing field, including the field owner used by issued work orders.
    for place in sorted(places.values(), key=lambda item: len(_path(places, item['id']))):
        if place['kind'] == 'building' and not any(
                field['key'] == IMPACT_DIRECTION for field in _inherited(places, place['id'])):
            place['parameters'].append({'key': IMPACT_DIRECTION, 'label': '撞击方向', 'type': 'choice',
                                        'required': False, 'options': [dict(option) for option in DEFAULT_DIRECTIONS]})
    return places


def location_definitions(location, *, available_locations=()):
    places = {str(p.pk): p for p in available_locations}
    places[str(location.pk)] = location
    return _inherited(location_schema(places.values()), location.pk)


def form_schema(catalog, locations, values=None, *, suggestions=None):
    """Only pass locations visible to the active team, including no private parents."""
    nodes = [{'id': str(n.pk), 'parent': str(n.parent_id or ''), 'name': n.label,
              'parameters': definitions(n.parameters)} for n in catalog.nodes.all()]
    for node in nodes:
        for field in node['parameters']:
            if field['key'] in EDITABLE_BIRD_FIELDS and field['type'] in ('text', 'choice'):
                field['allow_custom'] = True
                choices = list(field.get('options', []))
                known = {choice['value'] for choice in choices}
                for choice in (suggestions or {}).get(field['key'], []):
                    if choice['value'] not in known:
                        choices.append(choice); known.add(choice['value'])
                field['options'] = choices[:100]
            if field['key'] in HIDDEN_FORM_FIELDS:
                field['hidden'] = True
    by_id = {node['id']: node for node in nodes}
    for node in nodes:
        path = []; seen = set(); current = node
        while current and current['id'] not in seen:
            path.append(current); seen.add(current['id']); current = by_id.get(current['parent'])
        names = ' '.join(item['name'] for item in path).lower()
        bird_collision = ('鸟' in names or 'bird' in names) and any(word in names for word in ('撞', 'strike', 'collision'))
        configured = any(field['key'] == IMPACT_DIRECTION for item in path for field in item['parameters'])
        if bird_collision and not configured:
            node['parameters'].append({'key': IMPACT_DIRECTION, 'label': '撞击方向',
                                       'type': 'location', 'required': False})
    return {'nodes': nodes,
            'locations': list(location_schema(locations).values()),
            'values': values or {'work': [], 'locations': []}}


def parameter_suggestions(snapshots):
    """Reuse bounded, caller-visible bird names/codes without changing catalogues."""
    choices = {key: {} for key in EDITABLE_BIRD_FIELDS}
    for snapshot in snapshots:
        for item in (snapshot or {}).get('work', []):
            key = item.get('key'); value = item.get('value')
            if key in choices and isinstance(value, str) and value.strip() and len(value) <= 2000:
                choices[key].setdefault(value, {'value': value, 'label': item.get('value_label') or value})
    return {key: list(values.values())[:100] for key, values in choices.items()}


def merged_remark(remark, notes):
    remark = (remark or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if notes is None or notes == '':
        return remark
    if not isinstance(notes, str) or len(notes) > 2000:
        raise ValueError('观察备注最多支持 2000 字。')
    notes = notes.replace('\r\n', '\n').replace('\r', '\n').strip()
    return remark if not notes or notes in remark else '\n'.join(part for part in (notes, remark) if part)


def report_remark(report):
    if report is None:
        return ''
    notes = next((item.get('value') for item in report.pest_data.parameters.get('work', [])
                  if item.get('key') == 'notes'), None)
    return merged_remark(report.remark, notes)


def _path(items, identifier):
    path = []; seen = set(); item = items.get(str(identifier))
    while item:
        if item['id'] in seen:
            raise ValueError('参数层级存在循环。')
        seen.add(item['id']); path.insert(0, item)
        item = items.get(str(item.get('parent', '')))
    return path


def _inherited(items, identifier):
    fields = {}
    for item in _path(items, identifier):
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
            if previous and field['type'] == 'location':
                # Bindings request the same location field even when work
                # branches use different captions or required settings.
                target[field['key']] = {**previous, 'required': previous['required'] or field['required']}
                continue
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
        if field['key'] in EDITABLE_BIRD_FIELDS:
            return _clean_value({**field, 'type': 'text'}, value)
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


def parse_values(raw_values):
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
    return raw_values


def parameter_snapshot(catalog, node_ids, locations, raw_values, *, available_locations, previous=None,
                       automatic_values=None, remark=None):
    """Validate visible fields; trusted submission data supplies automatic values."""
    raw_values = parse_values(raw_values)
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
            if section == 'work' and remark is not None and field['key'] == 'notes':
                _clean_value({**field, 'required': False}, value)
                if field['required'] and not remark.strip():
                    raise ValueError('请填写备注。')
                continue
            if section == 'work' and automatic_values is not None and field['key'] in AUTOMATIC_WORK_FIELDS:
                value = automatic_values[field['key']]
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
