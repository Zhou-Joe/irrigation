"""Validated, repeatable imports of privately supplied bird-collision history.

The input is a local manifest plus its relative media files, not executable
configuration. Historical observations never imply a completed disposal/repair,
hours worked, staff attendance, map coordinates or a new PM task.
"""
import hashlib
import json
import re
import uuid
from datetime import date
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.models import WorkReport, Worker
from .catalog_service import current_catalog, selection_snapshot
from .models import (AuditEvent, Location, PestHistoryImport, PestHistoryRecord,
                     PestWorkData, ReferenceCatalog, ReferenceNode, Team)
from .work_parameters import definitions, parameter_snapshot, _clean_value
from .workorder_media import (MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES,
                             prepare_uploads, save_uploaded, delete_uploaded)

DEFAULT_DATASET = 'bird-collision-register'
HISTORY_PATH = ('野生动物', '鸟类', '撞击事件记录')
# Preflight holds validated uploads until the atomic import. Bound the entire
# batch, as well as each work order, before reading any attachment into memory.
MAX_BATCH_MEDIA_BYTES = 100 * 1024 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def _text(value, label, maximum, *, optional=False):
    if optional and value in (None, ''):
        return None
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f'{label}无效。')
    return value.strip()


def _options(value, label):
    if not isinstance(value, list) or not value or len(value) > 100:
        raise ValueError(f'{label}选项无效。')
    cleaned = [_text(v, label, 200) for v in value]
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f'{label}选项重复。')
    return cleaned


def _field_definitions(manifest):
    options = manifest.get('controlled_options', {})
    if not isinstance(options, dict):
        raise ValueError('来源选项格式无效。')
    directions = _options(options.get('side_of_building'), '撞击朝向')
    statuses = _options(options.get('status'), '发现状态')
    source_objects = manifest.get('objects')
    if source_objects is None:
        source_objects = [{'name': row.get('object_name')} for row in manifest.get('records', []) if isinstance(row, dict)]
        names = list(dict.fromkeys(item['name'] for item in source_objects))
    elif isinstance(source_objects, list) and all(isinstance(item, dict) for item in source_objects):
        names = [item.get('name') for item in source_objects]
    else:
        raise ValueError('鸟类对象清单无效。')
    names = _options(names, '鸟类对象')
    work = definitions([
        {'key': 'object_name', 'label': '鸟类对象', 'type': 'choice', 'options': names},
        {'key': 'species_alpha_code', 'label': '物种代码', 'type': 'text'},
        {'key': 'status', 'label': '发现状态', 'type': 'choice', 'options': statuses},
        {'key': 'weather', 'label': '天气', 'type': 'text'},
        {'key': 'reported_by', 'label': '原报告人', 'type': 'text'},
        {'key': 'observed_time', 'label': '发现时间', 'type': 'time'},
        {'key': 'location_detail', 'label': '具体位置', 'type': 'text'},
        {'key': 'notes', 'label': '观察备注', 'type': 'text'},
        {'key': 'impact_direction', 'label': '撞击朝向', 'type': 'location'},
    ])
    building = definitions([{'key': 'impact_direction', 'label': '撞击朝向',
                             'type': 'choice', 'options': directions}], allow_location=False)
    return work, building


def _catalog_preflight(team, work_defs):
    original = current_catalog(team)
    if original is None:
        return None, None
    remaining = list(original.nodes.all()); seen = set()
    for node in remaining:
        definitions(node.parameters)
    while remaining:
        ready = [node for node in remaining if node.parent_id is None or node.parent_id in seen]
        if not ready:
            raise ValueError('原工作目录层级无效。')
        for node in ready:
            seen.add(node.pk); remaining.remove(node)
    parent = None
    for label in HISTORY_PATH:
        matches = list(original.nodes.filter(parent=parent, label=label)[:2])
        if not matches:
            return original, None
        if len(matches) != 1:
            raise ValueError('已有撞击事件目录存在重名分支，请先人工核对。')
        parent = matches[0]
    if parent.children.exists() or definitions(parent.parameters) != work_defs:
        raise ValueError('已有撞击事件条目配置不同，请先人工核对。')
    return original, parent


def _detail_spec(row):
    detail = row.get('location_detail')
    if not detail:
        return None
    name = _text(detail, '具体位置', 150)
    kind = 'floor' if '楼' in name else 'room' if any(v in name for v in ('大堂', '贵宾廊')) else 'other'
    suffix = hashlib.sha256((row['building_code'] + '\0' + name).encode()).hexdigest()[:16]
    return {'code': 'history-place-' + suffix, 'name': name, 'kind': kind,
            'parent': row['building_code']}


def _location_specs(records):
    specs = {}
    for row in records:
        root = {'code': row['parent_code'], 'name': row['parent_name'], 'kind': 'zone', 'parent': None}
        building = {'code': row['building_code'], 'name': row['building_name'], 'kind': 'building',
                    'parent': row['parent_code']}
        for item in (root, building, _detail_spec(row)):
            if item is None:
                continue
            prior = specs.get(item['code'])
            if prior is not None and prior != item:
                raise ValueError('来源中的地点编码对应了不同的层级或名称。')
            specs[item['code']] = item
    return specs


def _work_values(row):
    values = row['parameters']
    mapping = {'object_name': row.get('object_name'),
               'species_alpha_code': values.get('species_alpha_code'), 'status': values.get('status'),
               'weather': values.get('weather'), 'reported_by': values.get('reported_by'),
               'observed_time': row.get('time'), 'location_detail': row.get('location_detail'),
               'notes': values.get('notes')}
    return [{'key': key, 'value': value} for key, value in mapping.items()]


def _media_paths(records, root):
    result = []; batch_bytes = 0
    for row in records:
        if not isinstance(row, dict):
            raise ValueError('历史记录格式无效。')
        media = row.get('media', [])
        if not isinstance(media, list) or len(media) > MAX_FILES:
            raise ValueError('每条历史记录最多包含 10 个附件。')
        checked = []; row_bytes = 0
        for item in media:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                raise ValueError('历史附件路径无效。')
            size = item.get('bytes')
            if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
                raise ValueError('历史附件大小无效，单个附件最多 50 MB。')
            row_bytes += size; batch_bytes += size
            if row_bytes > MAX_TOTAL_BYTES or batch_bytes > MAX_BATCH_MEDIA_BYTES:
                raise ValueError('每批历史附件总大小不能超过 100 MB，请拆分清单。')
            relative = Path(item['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('历史附件必须位于清单目录内。')
            file_path = (root / relative).resolve()
            if not file_path.is_relative_to(root) or not file_path.is_file():
                raise ValueError('历史附件不存在或超出清单目录。')
            if file_path.stat().st_size != size:
                raise ValueError('历史附件大小与清单不符。')
            checked.append((item, file_path))
        result.append(checked)
    return result


def _preflight(path, team):
    path = Path(path).resolve()
    if path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError('历史清单过大。')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('历史清单版本无效。')
    if team.business.code != 'pest-control' or not team.active or not team.business.active:
        raise ValueError('只能将历史记录导入启用中的植保团队。')
    if manifest.get('team_business_code') != team.business.code:
        raise ValueError('来源不属于当前业务。')
    source = manifest.get('source')
    if not isinstance(source, dict):
        raise ValueError('来源信息无效。')
    name = _text(source.get('name'), '来源名称', 255)
    source_hash = source.get('sha256')
    if not isinstance(source_hash, str) or not re.fullmatch('[0-9a-f]{64}', source_hash):
        raise ValueError('来源校验值无效。')
    dataset = manifest.get('dataset', DEFAULT_DATASET)
    if not isinstance(dataset, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', dataset):
        raise ValueError('来源数据集编号无效。')
    records = manifest.get('records')
    if not isinstance(records, list) or not 1 <= len(records) <= 10000:
        raise ValueError('历史清单应包含 1–10000 条记录。')
    media_paths = _media_paths(records, path.parent)
    work_defs, building_defs = _field_definitions(manifest)
    _catalog_preflight(team, work_defs)
    worker = Worker.objects.filter(employee_id=f'PEST-HISTORY-{team.pk}').first()
    if worker and (worker.user_id is not None or worker.active):
        raise ValueError('历史记录占位处理人已被实际账号使用，请先人工核对。')
    identifiers = set(); prepared = []; photos = 0
    for row, checked_media in zip(records, media_paths):
        if not isinstance(row, dict) or not isinstance(row.get('parameters'), dict):
            raise ValueError('历史记录格式无效。')
        identifier = row.get('source_no')
        if type(identifier) is not int or identifier < 1 or str(identifier) in identifiers:
            raise ValueError('来源事件编号无效或重复。')
        identifiers.add(str(identifier))
        if type(row.get('source_row')) is not int or row['source_row'] < 1:
            raise ValueError('来源行号无效。')
        _text(row.get('source_sheet'), '来源工作表', 128)
        try:
            day = date.fromisoformat(row['date'])
        except (KeyError, ValueError, TypeError):
            raise ValueError('历史事件日期无效。') from None
        if day > timezone.localdate():
            raise ValueError('历史事件日期不能晚于今天。')
        if row.get('completion_outcome') is not None:
            raise ValueError('事件观察清单不能声明已完成处置。')
        for key in ('building_code', 'parent_code'):
            _text(row.get(key), '地点编码', 100)
        for key in ('building_name', 'parent_name'):
            _text(row.get(key), '地点名称', 150)
        _text(row.get('object_name'), '鸟类对象', 2000)
        values = {v['key']: v['value'] for v in _work_values(row)}
        for field in work_defs:
            if field['type'] != 'location':
                _clean_value(field, values.get(field['key']))
        _clean_value(building_defs[0], row['parameters'].get('side_of_building'))
        uploads = []
        for item, file_path in checked_media:
            data = file_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != item.get('sha256'):
                raise ValueError('历史附件校验失败。')
            uploads.append(SimpleUploadedFile(file_path.name, data))
        uploads = prepare_uploads(uploads)
        canonical = {key: value for key, value in row.items() if key != 'source_key'}
        content_digest = _digest(canonical)
        existing = PestHistoryRecord.objects.filter(team=team, dataset=dataset, source_key=str(identifier)).select_related('report').first()
        if existing and (existing.content_digest != content_digest or existing.report.business_team_id != team.pk):
            raise ValueError(f'来源事件 {identifier} 已导入但内容有变化，请人工核对，不能覆盖历史工单。')
        prepared.append({'row': row, 'day': day, 'key': str(identifier), 'digest': content_digest,
                         'uploads': uploads, 'existing': existing})
        photos += len(uploads)
    specs = _location_specs(records)
    locations = {p.code: p for p in Location.objects.filter(owner_team=team, code__in=specs).select_related('parent')}
    for code, place in locations.items():
        spec = specs[code]
        if place.kind != spec['kind'] or (place.parent_id and
                (place.parent.owner_team_id != team.pk or place.parent.code != spec['parent'])):
            raise ValueError(f'地点 {code} 已存在且层级不同，请先人工核对。')
        if place.kind == 'building':
            configured = definitions(place.parameters, allow_location=False)
            field = next((field for field in configured if field['key'] == 'impact_direction'), None)
            if field and field != building_defs[0]:
                raise ValueError(f'建筑 {code} 已有不同的撞击朝向配置，请先人工核对。')
    input_digest = _digest(manifest)
    batch = PestHistoryImport.objects.filter(team=team, dataset=dataset, source_sha256=source_hash).first()
    if batch and batch.input_digest != input_digest:
        raise ValueError('同一来源的转换清单已变化，请核对后使用明确的新来源版本。')
    return {'manifest': manifest, 'name': name, 'source_hash': source_hash, 'dataset': dataset,
            'work_defs': work_defs, 'building_defs': building_defs, 'prepared': prepared,
            'locations': locations, 'specs': specs, 'input_digest': input_digest, 'batch': batch,
            'summary': {'records': len(records), 'photos': photos,
                        'new_records': sum(item['existing'] is None for item in prepared),
                        'existing_records': sum(item['existing'] is not None for item in prepared),
                        'new_locations': len(specs) - len(locations),
                        'buildings': sum(item['kind'] == 'building' for item in specs.values())}}


def _install_locations(team, plan):
    locations = plan['locations']; pending = dict(plan['specs'])
    while pending:
        ready = [spec for spec in pending.values() if not spec['parent'] or spec['parent'] in locations]
        if not ready:
            raise ValueError('地点层级存在循环或缺少上级。')
        for spec in ready:
            place = locations.get(spec['code'])
            if place is None:
                place = Location.objects.create(owner_team=team, code=spec['code'], name=spec['name'],
                    kind=spec['kind'], parent=locations.get(spec['parent']),
                    parameters=plan['building_defs'] if spec['kind'] == 'building' else [])
                locations[spec['code']] = place
            else:
                changed = []
                if not place.parent_id and spec['parent']:
                    place.parent = locations[spec['parent']]; changed.append('parent')
                configured = definitions(place.parameters, allow_location=False)
                if spec['kind'] == 'building' and not any(p['key'] == 'impact_direction' for p in configured):
                    place.parameters = configured + plan['building_defs']
                    changed.append('parameters')
                if changed:
                    place.save(update_fields=[*changed, 'updated_at'])
            del pending[spec['code']]
    return locations


def _install_catalog(team, plan):
    original, found = _catalog_preflight(team, plan['work_defs'])
    if found is not None:
        return original, found
    catalog = ReferenceCatalog.objects.create(business=team.business, owner_team=team,
        name='植保作业目录', version=uuid.uuid4().hex, source_name='历史记录字段配置')
    mapping = {}; pending = list(original.nodes.all()) if original else []
    order = 0
    while pending:
        ready = [node for node in pending if not node.parent_id or node.parent_id in mapping]
        if not ready:
            raise ValueError('原工作目录层级无效。')
        for node in ready:
            clone = ReferenceNode.objects.create(catalog=catalog, parent=mapping.get(node.parent_id),
                label=node.label, kind=node.kind, source_line=node.source_line, order=node.order,
                parameters=definitions(node.parameters))
            mapping[node.pk] = clone; pending.remove(node); order = max(order, node.order + 1)
    line = max((node.source_line for node in mapping.values()), default=0) + 1
    parent = None
    for label in HISTORY_PATH:
        found = catalog.nodes.filter(parent=parent, label=label).first()
        if found is None:
            found = ReferenceNode.objects.create(catalog=catalog, parent=parent, label=label, kind='node',
                source_line=line, order=order, parameters=plan['work_defs'] if label == HISTORY_PATH[-1] else [])
            line += 1; order += 1
        parent = found
    team.work_catalog = catalog; team.save(update_fields=['work_catalog'])
    return catalog, parent


def import_history(path, team, *, apply=False):
    """Dry-run by default. Applying a validated batch is atomic and idempotent."""
    if not apply:
        return dict(_preflight(path, team)['summary'], applied=False)
    saved = []
    try:
        with transaction.atomic():
            Team.objects.filter(pk=team.pk).update(work_catalog_id=F('work_catalog_id'))
            team = Team.objects.select_related('business', 'work_catalog').get(pk=team.pk)
            plan = _preflight(path, team)
            summary = dict(plan['summary'], applied=True)
            if not summary['new_records']:
                return summary
            locations = _install_locations(team, plan)
            catalog, leaf = _install_catalog(team, plan)
            batch = plan['batch'] or PestHistoryImport.objects.create(team=team, dataset=plan['dataset'],
                source_name=plan['name'], source_sha256=plan['source_hash'], input_digest=plan['input_digest'],
                provenance={key: value for key, value in plan['manifest'].items() if key != 'records'})
            worker, created = Worker.objects.get_or_create(employee_id=f'PEST-HISTORY-{team.pk}',
                defaults={'full_name': '历史记录（原报告人见详情）', 'active': False,
                          'department': '其他', 'department_other': '植保历史资料'})
            if not created and (worker.user_id is not None or worker.active):
                raise ValueError('历史记录占位处理人已被实际账号使用，请先人工核对。')
            for item in plan['prepared']:
                if item['existing']:
                    continue
                row = item['row']; building = locations[row['building_code']]
                specific = _detail_spec(row)
                place = locations[specific['code']] if specific else building
                raw = {'work': _work_values(row), 'locations': [{'key': 'impact_direction',
                       'location_id': str(building.pk), 'value': row['parameters'].get('side_of_building')}]}
                snapshot = parameter_snapshot(catalog, [leaf.pk], [place], raw,
                                              available_locations=list(locations.values()))
                selections = selection_snapshot(catalog, [leaf.pk])
                labels = [row['parent_name'], row['building_name']]
                if specific:
                    labels.append(specific['name'])
                report = WorkReport.all_businesses.create(worker=worker, business_team=team,
                    date=item['day'], team_size=0, third_party_count=0, team_hours=0, third_party_hours=0,
                    work_start_time=None, work_end_time=None, shift='', is_pm=False,
                    weather=row['parameters'].get('weather') or '', zone_names=' / '.join(labels),
                    work_content=' / '.join(HISTORY_PATH), remark=(row['parameters'].get('notes') or ''))
                report.ticket_number = f'PPC-H-{report.pk}'
                report.photos = save_uploaded(report, item['uploads']); saved.extend(report.photos)
                report.save(update_fields=['ticket_number', 'photos'])
                detail = PestWorkData.objects.create(report=report, catalog=catalog, selections=selections,
                    parameters=snapshot, location_labels=[{'id': str(place.pk), 'name': place.name, 'code': place.code}])
                detail.locations.add(place)
                PestHistoryRecord.objects.create(report=report, team=team, batch=batch, dataset=plan['dataset'],
                    source_key=item['key'], content_digest=item['digest'], source_sheet=row['source_sheet'],
                    source_row=row['source_row'], observations={**row['parameters'], 'observed_date': row['date'],
                        'observed_time': row.get('time'), 'object_name': row['object_name'],
                        'completion_outcome': None, 'completion_note': row.get('completion_note', '')}, original=row)
            AuditEvent.objects.create(team=team, action='pest.history.import', object_ref=str(batch.pk),
                                      detail={'dataset': plan['dataset'], **summary})
            return summary
    except Exception:
        if saved:
            delete_uploaded(saved)
        raise
