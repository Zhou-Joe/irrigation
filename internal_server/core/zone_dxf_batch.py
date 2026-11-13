"""Reviewable CAD/hand-drawn matching with frozen geometry and atomic writes."""
import hashlib
import json
import logging
import math
import uuid

from django.core import signing
from django.db import transaction
from django.http import JsonResponse

from .models import SubmissionReceipt, Zone
from .role_utils import get_django_user, is_admin
from .submissions import submission

logger = logging.getLogger(__name__)
MATCH_SALT = 'core.zone-dxf-match.v1'
MATCH_TTL = 30 * 60
CACHE_PREFIX = 'zone-dxf:match:v1:'
MAX_SHAPES = 5000
MAX_POINTS = 250000
MAX_TRANSLATION_METERS = 1000
MAX_TRANSLATION_DEGREES = 0.02
REVISION_FIELDS = ('boundary_points', 'dxf_boundary_points', 'boundary_source', 'dxf_boundary_source',
                   'label_lat', 'label_lng')
ZONE_FIELDS = ('id', 'code', 'name', 'patch_id', 'patch__name', 'boundary_points',
               'dxf_boundary_points', 'boundary_source', 'dxf_boundary_source', 'label_lat', 'label_lng',
               'area_sqm', 'updated_at')


class BatchError(ValueError):
    def __init__(self, message, *, status=400, refresh=False):
        self.status, self.refresh = status, refresh
        super().__init__(message)


def _response_error(exc):
    return JsonResponse({'success': False, 'message': str(exc), 'refresh_required': exc.refresh}, status=exc.status)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def zone_revision(zone):
    """Guard geometry and its custom label position, not unrelated label styling."""
    return _digest({field: getattr(zone, field) for field in REVISION_FIELDS})


def zone_state(zone):
    return {'id': zone.pk, 'zone_id': zone.pk, 'code': zone.code, 'name': zone.name,
            'patch_name': zone.patch.name if zone.patch_id else '',
            'boundary_source': zone.boundary_source,
            'has_dxf': bool(zone.dxf_boundary_points), 'has_dxf_boundary': bool(zone.dxf_boundary_points),
            'manual_boundary_points': zone.boundary_points,
            'dxf_boundary_points': zone.dxf_boundary_points,
            'dxf_boundary_source': zone.dxf_boundary_source,
            'label_lat': zone.label_lat, 'label_lng': zone.label_lng,
            'expected_revision': zone_revision(zone), 'area_display': zone.area_display}


def invalidate_drawing(session):
    """A new upload or server-side re-georeference invalidates older matches."""
    session['zone_dxf_revision'] = str(uuid.uuid4())
    if not session.get('zone_dxf_session'):
        session['zone_dxf_session'] = str(uuid.uuid4())


def _drawing_identity(session):
    if not session.get('zone_dxf_revision') or not session.get('zone_dxf_session'):
        invalidate_drawing(session)
    return {'revision': session['zone_dxf_revision'], 'session': session['zone_dxf_session'],
            'drawing': _digest([session.get('dxf_shapes'), session.get('dxf_groups')])}


def _coordinate(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BatchError(f'{label}必须是有限数值。')
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise BatchError(f'{label}必须是有限数值。') from None
    if not math.isfinite(number):
        raise BatchError(f'{label}必须是有限数值。')
    return number


def _normalized_transform(shapes, transformed):
    if (not isinstance(shapes, list) or not shapes or len(shapes) > MAX_SHAPES
            or not isinstance(transformed, list) or len(transformed) != len(shapes)):
        raise BatchError('当前 CAD 图形数量与原图不一致，或超过 5000 个，请重新解析。')
    seen, result, count = set(), [], 0
    for shape, converted in zip(shapes, transformed):
        if not isinstance(shape, dict) or not isinstance(converted, dict):
            raise BatchError('CAD 图形结构无效，请重新解析。')
        identifier = shape.get('id')
        if not isinstance(identifier, str) or identifier in seen or converted.get('id') != identifier:
            raise BatchError('CAD 图形编号或顺序与原图不一致，请重新解析。')
        seen.add(identifier)
        original, ring = shape.get('vertices'), converted.get('vertices_latlng')
        if not isinstance(original, list) or not isinstance(ring, list) or len(original) != len(ring) or len(ring) < 3:
            raise BatchError(f'图形 {identifier} 的顶点数量与原图不一致，不能替换或重画 CAD 轮廓。')
        count += len(ring)
        if count > MAX_POINTS:
            raise BatchError('CAD 顶点超过 250,000 个，请拆分图纸后处理。')
        points = []
        for point in ring:
            if not isinstance(point, dict) or 'lat' not in point or 'lng' not in point:
                raise BatchError('CAD 轮廓需要有效的经纬度点。')
            lat, lng = _coordinate(point['lat'], '纬度'), _coordinate(point['lng'], '经度')
            if not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise BatchError('CAD 轮廓超出有效经纬度范围，请重新配准。')
            points.append({'lat': lat, 'lng': lng})
        # Degenerate CAD symbols do not invalidate the entire drawing. The
        # matcher skips them; final selection still requires valid polygons.
        result.append({'id': identifier, 'entity_type': shape.get('entity_type', ''),
                       'layer': shape.get('layer', ''), 'vertex_count': len(points), 'vertices_latlng': points})
    return result


def _translation_of(base, moved):
    """The browser may translate the whole drawing, not edit individual CAD rings."""
    if len(base) != len(moved):
        return False
    first, other = base[0]['vertices_latlng'][0], moved[0]['vertices_latlng'][0]
    dlat, dlng = other['lat'] - first['lat'], other['lng'] - first['lng']
    return all(abs((b['lat'] - a['lat']) - dlat) <= 2e-9
               and abs((b['lng'] - a['lng']) - dlng) <= 2e-9
               for original, transformed in zip(base, moved)
               for a, b in zip(original['vertices_latlng'], transformed['vertices_latlng']))


def _valid_groups(groups, shapes):
    if not isinstance(groups, list) or not groups or len(groups) > len(shapes):
        raise BatchError('CAD 图形组无效，请重新上传。')
    result, seen = [], set()
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('id'), str) or group['id'] in seen:
            raise BatchError('CAD 图形组编号无效，请重新上传。')
        indices = [group.get('outer'), *(group.get('holes') or [])]
        if (any(isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(shapes) for idx in indices)
                or len(indices) != len(set(indices))):
            raise BatchError('CAD 图形组引用的轮廓无效，请重新上传。')
        seen.add(group['id'])
        result.append({'id': group['id'], 'outer': indices[0], 'holes': indices[1:],
                       'shape_ids': [shapes[index]['id'] for index in indices]})
    return result


def current_transform(request):
    shapes = request.session.get('dxf_shapes')
    groups = request.session.get('dxf_groups')
    if not shapes:
        raise BatchError('请先上传 CAD 图纸。')
    groups = _valid_groups(groups, shapes)
    baseline = request.session.get('dxf_transformed')
    preview = request.session.get('dxf_preview_transformed')
    if not baseline:
        info = request.session.get('dxf_coord_info', {})
        if info.get('type') == 'wgs84':
            from .dxf_utils import shapes_to_latlng_auto
            baseline = shapes_to_latlng_auto(shapes, info.get('axis_map', 'xy_to_lnglat'))
    raw = request.POST.get('transformed_json', '')
    if raw:
        if len(raw) > 60 * 1024 * 1024:
            raise BatchError('CAD 坐标内容过大，请拆分图纸。')
        try:
            moved = _normalized_transform(shapes, json.loads(raw))
        except (ValueError, TypeError) as exc:
            if isinstance(exc, BatchError):
                raise
            raise BatchError('CAD 坐标格式无效，请重新配准。') from None
        bases = []
        for candidate in (baseline, preview):
            if candidate:
                try:
                    bases.append(_normalized_transform(shapes, candidate))
                except BatchError:
                    # A freshly computed server preview can replace an old,
                    # incomplete session transform without accepting client edits.
                    continue
        if not bases or not any(_translation_of(candidate, moved) for candidate in bases):
            raise BatchError('提交的 CAD 轮廓不是当前配准结果的整体平移，请重新配准后匹配。')
    elif baseline or preview:
        moved = _normalized_transform(shapes, baseline or preview)
    else:
        raise BatchError('请先完成坐标配准，再进行批量匹配。')
    if _digest(moved) != _digest(baseline):
        invalidate_drawing(request.session)
    request.session['dxf_transformed'] = moved
    return shapes, groups, moved


def _candidate_ids(candidate, group_ids):
    ids = candidate.get('group_ids') if isinstance(candidate, dict) else None
    if (not isinstance(ids, list) or not ids or any(not isinstance(item, str) or item not in group_ids for item in ids)
            or len(ids) != len(set(ids))):
        raise BatchError('匹配候选引用了无效图形组，请重新匹配。')
    return ids


def auto_match(request):
    from .dxf_pipeline_utils import _parse_cache
    from .zone_dxf_matching import match_zones
    shapes, groups, transformed = current_transform(request)
    zones = list(Zone.objects.select_related('patch').only(*ZONE_FIELDS).order_by('code'))
    states = {zone.pk: zone_state(zone) for zone in zones}
    source = [{**states[zone.pk], 'boundary_points': zone.boundary_points} for zone in zones]
    matches = match_zones(source, groups, transformed)
    group_ids = {group['id'] for group in groups}
    rows, allowed = [], {}
    for match in matches:
        identifier = match.get('zone_id', match.get('id'))
        if identifier not in states:
            continue
        row = {**states[identifier], **match, 'zone_id': identifier}
        candidates = []
        for candidate in match.get('candidates', [])[:10]:
            ids = _candidate_ids(candidate, group_ids)
            # Only numeric scores/labels travel back; geometry is already in the map.
            data = {key: candidate[key] for key in ('score', 'confidence', 'iou', 'manual_coverage',
                'cad_coverage', 'area_ratio', 'centroid_distance_m', 'boundary_distance_m', 'reason',
                'cad_area_sqm', 'conflict', 'conflicting_zone_ids', 'conflicting_zone_codes',
                'quality', 'high_confidence', 'label') if key in candidate}
            data.update(group_ids=ids)
            data.setdefault('label', f'CAD 轮廓 · {len(ids)} 片')
            if any(isinstance(value, float) and not math.isfinite(value) for value in data.values()):
                raise BatchError('候选计算结果无效，请重新匹配。')
            candidates.append(data)
        row['candidates'] = candidates
        row['can_save'] = bool(candidates)
        row['high_confidence'] = (row.get('status') == 'matched' and bool(candidates)
                                  and not candidates[0].get('conflict'))
        row['has_dxf'] = states[identifier]['has_dxf']
        row['expected_revision'] = states[identifier]['expected_revision']
        rows.append(row)
        # Unmatched zones may still be reviewed against a manually selected
        # combination of groups from this exact frozen drawing.
        allowed[str(identifier)] = {'expected_revision': row['expected_revision'],
            'candidates': candidates, 'status': row.get('status'), 'high_confidence': row['high_confidence']}
    identifier = str(uuid.uuid4())
    identity = _drawing_identity(request.session)
    owner = get_django_user(request.user).pk
    frozen = {'id': identifier, 'owner': owner, **identity, 'groups': groups, 'transformed': transformed,
              'filename': str(request.session.get('dxf_filename', ''))[:255], 'allowed': allowed}
    cache = _parse_cache()
    cache.set(CACHE_PREFIX + identifier, frozen, MATCH_TTL)
    if cache.get(CACHE_PREFIX + identifier) is None:
        raise BatchError('匹配快照暂时无法保存，请稍后重试。', status=503)
    token = signing.dumps({'id': identifier, 'owner': owner, **identity}, salt=MATCH_SALT, compress=True)
    return JsonResponse({'success': True, 'match_token': token, 'submission_key': str(uuid.uuid4()),
                         'match_id': identifier, 'zones': rows, 'expires_in': MATCH_TTL,
                         'message': '匹配完成，请核对候选轮廓后选择需要保存的区域。'})


def _read_match(request):
    from .dxf_pipeline_utils import _parse_cache
    raw = request.POST.get('match_token', '')
    if not raw or len(raw) > 5000:
        raise BatchError('请先进行自动匹配。', refresh=True)
    try:
        token = signing.loads(raw, salt=MATCH_SALT, max_age=MATCH_TTL)
    except signing.BadSignature:
        raise BatchError('匹配预览已过期或无效，请重新匹配。', status=410, refresh=True) from None
    identity = _drawing_identity(request.session)
    if (not isinstance(token, dict) or token.get('owner') != get_django_user(request.user).pk
            or any(token.get(key) != value for key, value in identity.items())):
        raise BatchError('图纸或配准位置已变化，请重新匹配。', status=409, refresh=True)
    frozen = _parse_cache().get(CACHE_PREFIX + str(token.get('id', '')))
    if not frozen or frozen.get('owner') != token['owner'] or any(frozen.get(key) != value for key, value in identity.items()):
        raise BatchError('匹配快照已过期，请重新匹配。', status=410, refresh=True)
    return frozen


def _require_key(request):
    try:
        key = str(uuid.UUID(request.POST.get('submission_key', '')))
        header = request.headers.get('X-Submission-Key')
        if header and str(uuid.UUID(header)) != key:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise BatchError('提交编号无效，请重新确认本次操作。') from None


def _request_rows(request, field):
    raw = request.POST.get(field, '')
    if len(raw) > 2 * 1024 * 1024:
        raise BatchError('批量选择内容过大，请分批操作。')
    try:
        rows = json.loads(raw)
    except (ValueError, TypeError):
        raise BatchError('批量选择内容格式无效。') from None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise BatchError('每次请选择 1 至 5000 个区域。')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or isinstance(row.get('zone_id'), bool):
            raise BatchError('区域选择无效。')
        value = row.get('zone_id')
        if len(str(value)) > 19 or not str(value).isdecimal() or not 0 < int(value) < 9223372036854775807:
            raise BatchError('区域编号无效。')
        row['zone_id'] = int(value)
        revision = row.get('expected_revision')
        if row['zone_id'] in seen or not isinstance(revision, str) or len(revision) != 64:
            raise BatchError('区域重复或缺少边界版本，请更新列表后再试。', status=409, refresh=True)
        seen.add(row['zone_id'])
    return rows


def _lock_zones(rows):
    # Serializes competing batches which might claim one group for different zones.
    list(Zone.objects.select_for_update().order_by('pk').values_list('pk', flat=True))
    zones = {zone.pk: zone for zone in Zone.objects.filter(pk__in=[row['zone_id'] for row in rows])
             .select_related('patch').only(*ZONE_FIELDS)}
    for row in rows:
        zone = zones.get(row['zone_id'])
        if zone is None:
            raise BatchError('部分区域已删除，请更新列表后再试。', status=409, refresh=True)
        if zone_revision(zone) != row['expected_revision']:
            raise BatchError(f'区域 {zone.code} 的手绘、DXF 或来源已被更新，请重新匹配或更新列表。', status=409, refresh=True)
    return zones


def _point(point):
    if isinstance(point, dict):
        lat = point.get('lat', point.get('latitude'))
        lng = point.get('lng', point.get('longitude'))
    elif isinstance(point, (list, tuple)) and len(point) == 2:
        lat, lng = point
    else:
        raise BatchError('DXF 边界点格式无效。')
    lat, lng = _coordinate(lat, '纬度'), _coordinate(lng, '经度')
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise BatchError('DXF 边界点超出有效经纬度范围。')
    return lng, lat


def _is_point(value):
    return isinstance(value, dict) or (isinstance(value, (list, tuple)) and len(value) == 2
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value))


def validate_boundary(boundary):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.errors import GEOSException
    if not isinstance(boundary, list) or not boundary:
        raise BatchError('没有可用的 DXF 边界。')
    if _is_point(boundary[0]):
        groups = [[boundary]]
    elif isinstance(boundary[0], list) and boundary[0] and _is_point(boundary[0][0]):
        groups = [boundary]
    else:
        groups = boundary
    polygons = []
    total = 0
    try:
        for group in groups:
            if not isinstance(group, list) or not group:
                raise BatchError('DXF 图形组不能为空。')
            rings = []
            for ring in group:
                if not isinstance(ring, list) or len(ring) < 3:
                    raise BatchError('DXF 每个轮廓至少需要三个顶点。')
                total += len(ring)
                if total > MAX_POINTS:
                    raise BatchError('区域 DXF 边界顶点过多，请拆分处理。')
                points = [_point(point) for point in ring]
                if len(set(points)) < 3:
                    raise BatchError('DXF 轮廓顶点退化。')
                rings.append(points)
            polygon = Polygon(rings[0], rings[1:])
            if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
                raise BatchError('DXF 轮廓自相交、孔洞无效或面积为零，请核对后再保存。')
            polygons.append(polygon)
        # Adjacent CAD pieces may share an edge. Validate their union without
        # replacing or simplifying the original saved coordinates.
        geometry = polygons[0] if len(polygons) == 1 else unary_union(polygons)
        area = sum(polygon.area for polygon in polygons)
        if not geometry.is_valid or area - geometry.area > max(1e-14, area * 1e-8):
            raise BatchError('所选 DXF 图形相互重叠或无效，请调整候选选择。')
    except (TypeError, ValueError, GEOSException) as exc:
        if isinstance(exc, BatchError):
            raise
        raise BatchError('DXF 边界结构无效，请核对后再保存。') from None


def _boundary(frozen, group_ids):
    groups = {group['id']: group for group in frozen['groups']}
    result = []
    for identifier in group_ids:
        group = groups[identifier]
        result.append([frozen['transformed'][index]['vertices_latlng']
                       for index in [group['outer'], *group['holes']]])
    boundary = result[0] if len(result) == 1 else result
    validate_boundary(boundary)
    return boundary


def _read_translation(value):
    """Only a bounded rigid offset is accepted; clients never submit new vertices."""
    if value is None:
        return {'lat': 0.0, 'lng': 0.0}
    if not isinstance(value, dict) or set(value) != {'lat', 'lng'}:
        raise BatchError('位置调整需要同时提供纬度和经度偏移。')
    delta = {key: _coordinate(value[key], '位置偏移') for key in ('lat', 'lng')}
    if any(abs(number) > MAX_TRANSLATION_DEGREES for number in delta.values()):
        raise BatchError('单个区域的位置微调过大，请将每个方向的偏移限制在 0.02 度以内。')
    return delta


def _has_translation(delta):
    return delta['lat'] != 0 or delta['lng'] != 0


def _translated_geometry(boundary, delta, *, allow_empty=False, minimum_points=3):
    """Copy and offset coordinates without interpreting or rebuilding ring topology.

    Legacy hand-drawn lists may represent islands rather than outer/hole pairs.
    A rigid translation must preserve that distinction, all point metadata and
    the original closure, instead of passing old geometry through a new parser.
    """
    if boundary is None and allow_empty:
        return boundary
    if not isinstance(boundary, (list, tuple)):
        raise BatchError('区域边界结构无效，无法进行位置微调。')
    if boundary and not isinstance(boundary[0], (list, tuple, dict)):
        raise BatchError('区域边界需要轮廓点列表，无法进行位置微调。')
    count, reference_lat = 0, None

    def shift(lat, lng):
        nonlocal count, reference_lat
        lat, lng = _coordinate(lat, '边界纬度'), _coordinate(lng, '边界经度')
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise BatchError('区域原边界超出有效经纬度范围，无法微调。')
        count += 1
        if count > MAX_POINTS:
            raise BatchError('区域边界顶点过多，请拆分处理。')
        if reference_lat is None:
            reference_lat = lat
        moved_lat, moved_lng = lat + delta['lat'], lng + delta['lng']
        if not -90 <= moved_lat <= 90 or not -180 <= moved_lng <= 180:
            raise BatchError('位置调整后的边界超出有效经纬度范围。')
        return moved_lat, moved_lng

    def walk(value, depth=0):
        if depth > 8:
            raise BatchError('区域边界层级过深，无法进行位置微调。')
        if isinstance(value, dict):
            lat_keys = [key for key in ('lat', 'latitude') if key in value]
            lng_keys = [key for key in ('lng', 'longitude') if key in value]
            if not lat_keys or not lng_keys:
                raise BatchError('区域边界点缺少经纬度，无法进行位置微调。')
            lat = _coordinate(value[lat_keys[0]], '边界纬度')
            lng = _coordinate(value[lng_keys[0]], '边界经度')
            if (any(_coordinate(value[key], '边界纬度') != lat for key in lat_keys[1:])
                    or any(_coordinate(value[key], '边界经度') != lng for key in lng_keys[1:])):
                raise BatchError('区域边界点包含不一致的经纬度别名，无法微调。')
            moved_lat, moved_lng = shift(lat, lng)
            return {**value, **{key: moved_lat for key in lat_keys},
                    **{key: moved_lng for key in lng_keys}}
        if not isinstance(value, (list, tuple)):
            raise BatchError('区域边界点结构无效，无法进行位置微调。')
        # Numeric coordinate pairs can carry an optional third coordinate or
        # other point metadata. Preserve it rather than flattening the ring.
        if len(value) >= 2 and not isinstance(value[0], (list, tuple, dict)):
            moved_lat, moved_lng = shift(value[0], value[1])
            values = [moved_lat, moved_lng, *value[2:]]
        else:
            point_children = [isinstance(item, dict) or (isinstance(item, (list, tuple))
                and len(item) >= 2 and not isinstance(item[0], (list, tuple, dict))) for item in value]
            if any(point_children) and not all(point_children):
                raise BatchError('区域边界的点与轮廓层级混合，无法进行位置微调。')
            values = [walk(item, depth + 1) for item in value]
        return tuple(values) if isinstance(value, tuple) else values

    result = walk(boundary)
    if not count:
        if allow_empty:
            return boundary
        raise BatchError('没有可微调的 DXF 边界。')
    if count < minimum_points:
        raise BatchError('区域边界有效顶点不足，无法进行位置微调。')
    distance = 111320 * math.hypot(delta['lat'], delta['lng'] * math.cos(math.radians(reference_lat)))
    if distance > MAX_TRANSLATION_METERS:
        raise BatchError('单个区域的位置微调不能超过 1 公里，请先核对选中的区域。')
    # Zero offsets must preserve the saved JSON exactly, including number types.
    return result if _has_translation(delta) else boundary


def _prepare_translation(zone, boundary, delta):
    """Prepare both boundary variants and custom label before any DB write."""
    if not _has_translation(delta):
        return boundary, zone.boundary_points, None
    dxf = _translated_geometry(boundary, delta)
    manual = _translated_geometry(zone.boundary_points, delta, allow_empty=True)
    label = None
    if zone.label_lat is not None and zone.label_lng is not None:
        point = _translated_geometry([{'lat': zone.label_lat, 'lng': zone.label_lng}], delta, minimum_points=1)[0]
        label = (point['lat'], point['lng'])
    return dxf, manual, label


def _invalidate_reference():
    # Home/neutral-location geometry is read from Zone directly. Only the CAD
    # reference-map variants have a separate short-lived cache to invalidate.
    try:
        from django.core.cache import cache
        value = cache.get('ref_map:ver') or 0
        cache.set('ref_map:ver', value + 1, 30 * 86400)
    except Exception:
        logger.warning('Zone DXF reference-map cache invalidation failed', exc_info=True)


@submission('zone.dxf.batch_assign')
def _assign_submission(request, frozen):
    try:
        rows = _request_rows(request, 'assignments')
        mode = request.POST.get('mode', 'save_only')
        if mode not in ('save_only', 'save_and_activate'):
            raise BatchError('请选择保存边界或保存并启用。')
        with transaction.atomic():
            zones = _lock_zones(rows)
            used = {}
            previous = SubmissionReceipt.objects.filter(owner=get_django_user(request.user),
                kind='zone.dxf.batch_assign', response__match_id=frozen['id']).values_list('response', flat=True)
            for receipt in previous:
                for assignment in receipt.get('assignments', []):
                    for group in assignment.get('group_ids', []):
                        used[group] = assignment['zone_id']
            prepared = []
            for row in rows:
                zone = zones[row['zone_id']]
                eligible = frozen['allowed'].get(str(zone.pk))
                if eligible is None or eligible['expected_revision'] != row['expected_revision']:
                    raise BatchError(f'区域 {zone.code} 不属于本次候选，或已在本次匹配后更新，请重新匹配。', status=409, refresh=True)
                groups = row.get('group_ids')
                valid_ids = {group['id'] for group in frozen['groups']}
                _candidate_ids({'group_ids': groups}, valid_ids)
                candidate = next((choice for choice in eligible['candidates'] if set(choice['group_ids']) == set(groups)), None)
                reliable = bool(candidate and candidate.get('high_confidence') and not candidate.get('conflict'))
                if not reliable and row.get('reviewed') is not True:
                    raise BatchError(f'请先核对区域 {zone.code} 的候选轮廓，再勾选已核对。')
                if zone.dxf_boundary_points and row.get('overwrite_existing') is not True:
                    raise BatchError(f'区域 {zone.code} 已有 DXF，请明确勾选覆盖后再保存。')
                for group in groups:
                    if group in used and used[group] != zone.pk:
                        raise BatchError(f'同一个 CAD 图形组不能分配给多个区域，请核对 {zone.code} 的候选。', status=409)
                    used[group] = zone.pk
                delta = _read_translation(row.get('translation'))
                boundary, manual, label = _prepare_translation(zone, _boundary(frozen, groups), delta)
                prepared.append((zone, groups, boundary, manual, label, delta))
            changed, assignments = [], []
            for zone, groups, boundary, manual, label, delta in prepared:
                zone.dxf_boundary_points = boundary
                zone.dxf_boundary_source = frozen['filename']
                fields = ['dxf_boundary_points', 'dxf_boundary_source', 'area_sqm', 'updated_at']
                if _has_translation(delta) and manual != zone.boundary_points:
                    zone.boundary_points = manual
                    fields.append('boundary_points')
                if label is not None:
                    zone.label_lat, zone.label_lng = label
                    fields.extend(['label_lat', 'label_lng'])
                if mode == 'save_and_activate':
                    zone.boundary_source = 'dxf'
                    fields.append('boundary_source')
                zone.save(update_fields=fields)
                changed.append(zone_state(zone))
                assignments.append({'zone_id': zone.pk, 'group_ids': groups, 'translation': delta})
            transaction.on_commit(_invalidate_reference)
        return JsonResponse({'success': True, 'message': f'已保存 {len(changed)} 个区域的 CAD 边界。',
            'zones': changed, 'changed_ids': [zone['zone_id'] for zone in changed], 'mode': mode,
            'match_id': frozen['id'], 'assignments': assignments})
    except BatchError as exc:
        return _response_error(exc)


@submission('zone.dxf.batch_translate')
def _translate_submission(request):
    """Tune saved DXF zones independently, using only their locked DB geometry."""
    try:
        rows = _request_rows(request, 'zones')
        mode = request.POST.get('mode', 'save_only')
        if mode not in ('save_only', 'save_and_activate'):
            raise BatchError('请选择保存边界或保存并启用。')
        with transaction.atomic():
            zones = _lock_zones(rows)
            prepared = []
            for row in rows:
                zone = zones[row['zone_id']]
                delta = _read_translation(row.get('translation'))
                # Validate coordinates without changing legacy holes/islands or
                # applying the current drawing's transform to an unrelated zone.
                boundary = _translated_geometry(zone.dxf_boundary_points, delta)
                if _has_translation(delta):
                    manual = _translated_geometry(zone.boundary_points, delta, allow_empty=True)
                    label = None
                    if zone.label_lat is not None and zone.label_lng is not None:
                        point = _translated_geometry([{'lat': zone.label_lat, 'lng': zone.label_lng}], delta,
                                                     minimum_points=1)[0]
                        label = (point['lat'], point['lng'])
                else:
                    manual, label = zone.boundary_points, None
                prepared.append((zone, boundary, manual, label, delta))
            changed, translations, any_changed = [], [], False
            for zone, boundary, manual, label, delta in prepared:
                fields = []
                if _has_translation(delta):
                    zone.dxf_boundary_points = boundary
                    fields.append('dxf_boundary_points')
                    if manual != zone.boundary_points:
                        zone.boundary_points = manual
                        fields.append('boundary_points')
                    if label is not None:
                        zone.label_lat, zone.label_lng = label
                        fields.extend(['label_lat', 'label_lng'])
                if mode == 'save_and_activate' and zone.boundary_source != 'dxf':
                    zone.boundary_source = 'dxf'
                    fields.append('boundary_source')
                if fields:
                    zone.save(update_fields=[*fields, 'area_sqm', 'updated_at'])
                    any_changed = True
                changed.append(zone_state(zone))
                translations.append({'zone_id': zone.pk, 'translation': delta})
            if any_changed:
                transaction.on_commit(_invalidate_reference)
        return JsonResponse({'success': True, 'message': f'已保存 {len(changed)} 个区域的位置调整。',
            'zones': changed, 'changed_ids': [zone['zone_id'] for zone in changed], 'mode': mode,
            'translations': translations})
    except BatchError as exc:
        return _response_error(exc)


@submission('zone.dxf.batch_source')
def _switch_submission(request):
    try:
        rows = _request_rows(request, 'zones')
        source = request.POST.get('source')
        if source not in ('manual', 'dxf'):
            raise BatchError('请选择手绘或 DXF 边界来源。')
        with transaction.atomic():
            zones = _lock_zones(rows)
            if source == 'dxf':
                for zone in zones.values():
                    try:
                        validate_boundary(zone.dxf_boundary_points)
                    except BatchError as exc:
                        raise BatchError(f'区域 {zone.code} 的 DXF 尚不可用：{exc}') from None
            changed = []
            for zone in zones.values():
                if zone.boundary_source != source:
                    zone.boundary_source = source
                    zone.save(update_fields=['boundary_source', 'area_sqm', 'updated_at'])
                changed.append(zone_state(zone))
            transaction.on_commit(_invalidate_reference)
        return JsonResponse({'success': True, 'message': f'已将 {len(changed)} 个区域切换为{"DXF" if source == "dxf" else "手绘"}边界。',
                             'zones': changed, 'changed_ids': [zone['zone_id'] for zone in changed], 'source': source})
    except BatchError as exc:
        return _response_error(exc)


def handle_batch_action(request, action):
    """Permission and signed ownership checks run before idempotency receipts."""
    if not is_admin(request.user):
        return _response_error(BatchError('只有管理员或经理可以批量管理 CAD 边界。', status=403))
    try:
        if action == 'auto_match':
            return auto_match(request)
        _require_key(request)
        if action == 'batch_assign':
            return _assign_submission(request, _read_match(request))
        if action == 'batch_translate':
            return _translate_submission(request)
        if action == 'batch_switch_source':
            return _switch_submission(request)
        raise BatchError('未知批量操作。')
    except BatchError as exc:
        return _response_error(exc)
    except Exception:
        logger.exception('Zone CAD batch operation failed')
        return JsonResponse({'success': False, 'message': 'CAD 批量操作未完成，请保留当前选择并重试。'}, status=500)
