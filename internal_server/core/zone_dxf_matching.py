"""Read-only recommendations between hand-drawn zones and retained CAD groups.

``boundary_points`` is deliberately the only zone geometry used. Active DXF
boundaries, smoothing, simplified display rings and saved import progress never
replace that reference. The output contains group IDs and measurements only;
callers must save the original transformed rings belonging to those IDs.

All areas/distances use one local metre plane. An STRtree bounds the expensive
polygon intersections, and boundary deviation samples a bounded number of
positions without simplifying or modifying either source contour.
"""
from __future__ import annotations

import itertools
import math
from bisect import bisect_right
from collections import Counter, defaultdict

from .pipe_utils import _to_latlng

try:
    from shapely.errors import GEOSException
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
except ImportError:  # A useful per-row explanation is preferable to a page 500.
    STRtree = None


MIN_AREA_SQM = 0.01
MAX_NEIGHBORS = 32
MAX_CANDIDATES = 5
BOUNDARY_SAMPLES = 24


def _point(value):
    if isinstance(value, dict):
        if not (('lat' in value or 'latitude' in value)
                and ('lng' in value or 'longitude' in value)):
            return None
    elif not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        point = _to_latlng(value)
        if point and all(math.isfinite(v) for v in point) and -90 < point[0] < 90 and -180 <= point[1] <= 180:
            return point
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _looks_point(value):
    if isinstance(value, dict):
        return 'lat' in value or 'latitude' in value
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and not isinstance(value[0], (dict, list, tuple))
            and not isinstance(value[1], (dict, list, tuple)))


def _is_ring(value):
    return isinstance(value, (list, tuple)) and bool(value) and _looks_point(value[0])


def _first_point(value, depth=0):
    if depth > 4:
        return None
    if _looks_point(value):
        return _point(value)
    if isinstance(value, (list, tuple)):
        for child in value:
            point = _first_point(child, depth + 1)
            if point:
                return point
    return None


def _projection(zones, transformed):
    # A common origin keeps nearby geometries in one STRtree. Sampling one
    # vertex per zone avoids a second traversal of all detailed CAD vertices.
    samples = [_first_point(zone.get('boundary_points')) for zone in zones]
    samples = [point for point in samples if point]
    if not samples:
        samples = [point for shape in transformed
                   if isinstance(shape, dict)
                   if (point := _first_point(shape.get('vertices_latlng')))]
    if not samples:
        return None
    lat0 = sorted(point[0] for point in samples)[len(samples) // 2]
    lng0 = sorted(point[1] for point in samples)[len(samples) // 2]
    longitude_scale = 111320.0 * math.cos(math.radians(lat0))
    if longitude_scale < 1:
        return None

    def project(point):
        return ((point[1] - lng0) * longitude_scale, (point[0] - lat0) * 111320.0)
    return project


def _ring(value, project):
    if not _is_ring(value):
        raise ValueError('边界不是有效的点环')
    points = [_point(point) for point in value]
    if any(point is None for point in points):
        raise ValueError('边界含缺失、非有限或超界的经纬度')
    coordinates = [project(point) for point in points]
    if len(set(coordinates)) < 3:
        raise ValueError('边界至少需要三个不同的有效顶点')
    polygon = Polygon(coordinates)
    if not polygon.is_valid:
        raise ValueError('边界存在自交或重叠线段，需先检查轮廓')
    if polygon.is_empty or polygon.area < MIN_AREA_SQM:
        raise ValueError('边界面积过小或顶点接近同一直线')
    return coordinates, polygon


def _group_geometry(rings, project):
    if not isinstance(rings, (list, tuple)) or not rings:
        raise ValueError('图形组没有外边界')
    coordinates = [_ring(ring, project)[0] for ring in rings]
    polygon = Polygon(coordinates[0], coordinates[1:])
    if not polygon.is_valid or polygon.is_empty or polygon.area < MIN_AREA_SQM:
        raise ValueError('外边界或孔洞关系无效，孔洞须完整位于外边界内且互不交叉')
    return polygon


def _manual_geometry(boundary, project):
    """Preserve holes; disjoint legacy flat rings remain separate islands.

    Nested groups explicitly declare [outer, holes...]. Flat ring lists also
    occur in older hand drawings as several independent islands, so *complete*
    geometric containment determines nesting rather than treating every later
    ring as a hole. A point-in-polygon/centroid shortcut is insufficient here.
    """
    if not isinstance(boundary, (list, tuple)) or not boundary:
        raise ValueError('没有手绘边界，无法按手绘轮廓匹配')
    warnings = []
    if _is_ring(boundary):
        return _ring(boundary, project)[1], warnings
    if all(_is_ring(ring) for ring in boundary):
        data = [_ring(ring, project) for ring in boundary]
        polygons = [pair[1] for pair in data]
        if len({polygon.normalize().wkb for polygon in polygons}) != len(polygons):
            raise ValueError('手绘边界包含重复轮廓，需先核对')
        tree = STRtree(polygons)
        parents = []
        for index, polygon in enumerate(polygons):
            containers = [int(other) for other in tree.query(polygon, predicate='covered_by')
                          if int(other) != index and polygons[int(other)].area > polygon.area]
            parents.append(min(containers, key=lambda other: polygons[other].area) if containers else None)
        depths = []
        for index in range(len(polygons)):
            depth, parent = 0, parents[index]
            while parent is not None:
                depth += 1
                parent = parents[parent]
            depths.append(depth)
        parts = []
        for index, depth in enumerate(depths):
            if depth % 2:
                continue
            rings = [data[index][0]] + [data[child][0] for child in range(len(data))
                                      if parents[child] == index and depths[child] == depth + 1]
            polygon = Polygon(rings[0], rings[1:])
            if not polygon.is_valid:
                raise ValueError('手绘边界的孔洞相交或接触外边界，需先核对')
            parts.append(polygon)
    elif all(isinstance(group, (list, tuple)) and group
             and all(_is_ring(ring) for ring in group) for group in boundary):
        parts = [_group_geometry(group, project) for group in boundary]
    else:
        raise ValueError('手绘边界层级格式无效，需检查点环与多块区域的分组')
    geometry = unary_union(parts)
    if geometry.is_empty or not geometry.is_valid or geometry.area < MIN_AREA_SQM:
        raise ValueError('手绘边界无法组成有效区域')
    if sum(part.area for part in parts) - geometry.area > max(0.01, geometry.area * 0.001):
        warnings.append('手绘的多块区域互相重叠，匹配结果需要人工核对')
    return geometry, warnings


def _cad_catalog(groups, transformed, project):
    records, invalid = [], 0
    counts = Counter(group.get('id') for group in groups if isinstance(group, dict)
                     and isinstance(group.get('id'), (str, int)))
    for group in groups:
        try:
            if not isinstance(group, dict) or not isinstance(group.get('id'), (str, int)) or counts[group['id']] != 1:
                raise ValueError('图形组编号缺失或重复')
            holes = group.get('holes') or []
            if not isinstance(holes, (list, tuple)):
                raise ValueError('孔洞索引格式无效')
            indices = [group.get('outer')] + list(holes)
            if any(type(index) is not int or not 0 <= index < len(transformed) for index in indices) or len(set(indices)) != len(indices):
                raise ValueError('图形组索引无效')
            shapes = [transformed[index] for index in indices]
            expected = group.get('shape_ids')
            if expected and (len(expected) != len(shapes) or any(str(shape.get('id')) != str(shape_id) for shape, shape_id in zip(shapes, expected))):
                raise ValueError('转换轮廓与原图形组不一致')
            polygon = _group_geometry([shape['vertices_latlng'] for shape in shapes], project)
            records.append({'id':group['id'], 'geometry':polygon, 'bounds':polygon.bounds,
                            'centroid':polygon.centroid, 'label':str(group.get('label') or group['id'])})
        except (ValueError, TypeError, KeyError, AttributeError, GEOSException):
            invalid += 1
    return records, invalid


def _bbox_iou(first, second):
    intersection = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(0, min(first[3], second[3]) - max(first[1], second[1]))
    area_a = (first[2] - first[0]) * (first[3] - first[1])
    area_b = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / max(area_a + area_b - intersection, 1e-12)


def _neighbors(geometry, tree, records, limit=MAX_NEIGHBORS):
    padding = min(75.0, max(12.0, math.sqrt(geometry.area) * 0.5))
    bounds = geometry.bounds
    indices = [int(index) for index in tree.query(box(bounds[0] - padding, bounds[1] - padding, bounds[2] + padding, bounds[3] + padding))]
    center = geometry.centroid
    indices.sort(key=lambda index: (-_bbox_iou(bounds, records[index]['bounds']), center.distance(records[index]['centroid']), index))
    return indices[:limit]


def _metrics(manual, cad, group_ids, label):
    intersection = manual.intersection(cad).area
    manual_area, cad_area = manual.area, cad.area
    iou = intersection / max(manual_area + cad_area - intersection, 1e-12)
    coverage, precision = intersection / manual_area, intersection / cad_area
    center_distance = manual.centroid.distance(cad.centroid)
    area_similarity = min(manual_area, cad_area) / max(manual_area, cad_area)
    score = (0.70 * iou + 0.17 * min(coverage, precision) + 0.06 * area_similarity
             + 0.03 * math.exp(-center_distance / max(math.sqrt(manual_area), 1.0)))
    return {'group_ids':list(group_ids), 'label':label, 'score':score,
            'iou':iou, 'manual_coverage':coverage, 'cad_coverage':precision,
            'area_ratio':cad_area / manual_area, 'cad_area_sqm':cad_area,
            'centroid_distance_m':center_distance, '_geometry':cad,
            '_combined':len(group_ids) > 1}


def _union_candidates(manual, tree, records):
    """Offer bounded combinations only for genuine multi-island hand drawings.

    Each component must mostly cover its own CAD group. Overlapping CAD groups,
    adjacent unrelated areas and combinations swallowing a neighbor are not
    eligible. IDs continue to refer to the original separate CAD groups.
    """
    if manual.geom_type != 'MultiPolygon' or not 2 <= len(manual.geoms) <= 8:
        return []
    choices = []
    for part in manual.geoms:
        options = []
        for index in _neighbors(part, tree, records, limit=8):
            cad = records[index]['geometry']
            overlap = part.intersection(cad).area
            if overlap / cad.area >= 0.75 and overlap / part.area >= 0.35:
                options.append((overlap / (part.area + cad.area - overlap), index))
        options.sort(reverse=True)
        if not options:
            return []
        choices.append([item[1] for item in options[:2]])
    baseline = [options[0] for options in choices]
    combinations = [baseline]
    for position, options in enumerate(choices):
        if len(options) > 1:
            alternative = baseline.copy()
            alternative[position] = options[1]
            combinations.append(alternative)
        if len(combinations) == 5:
            break
    result, seen = [], set()
    for combination in combinations:
        indices = tuple(sorted(set(combination)))
        if len(indices) < 2 or indices in seen:
            continue
        seen.add(indices)
        parts = [records[index]['geometry'] for index in indices]
        if any(a.intersection(b).area > min(a.area, b.area) * 0.01 for a, b in itertools.combinations(parts, 2)):
            continue
        cad = unary_union(parts)
        result.append(_metrics(manual, cad, [records[index]['id'] for index in indices],
                               '组合 ' + str(len(indices)) + ' 个图形组（' + ' + '.join(records[index]['label'] for index in indices) + '）'))
    return result


def _boundary_samples(geometry, cache):
    key = id(geometry)
    if key in cache:
        return cache[key][1]
    boundary = geometry.boundary
    lines = list(boundary.geoms) if hasattr(boundary, 'geoms') else [boundary]
    cumulative, total = [], 0.0
    for line in lines:
        total += line.length
        cumulative.append(total)
    points = []
    for index in range(BOUNDARY_SAMPLES):
        position = (index + 0.5) / BOUNDARY_SAMPLES * total
        part = min(bisect_right(cumulative, position), len(lines) - 1)
        points.append(lines[part].interpolate(position - (cumulative[part - 1] if part else 0.0)))
    # Retain the geometry alongside its id to prevent object-id reuse.
    cache[key] = (geometry, points)
    return points


def _boundary_deviation(first, second, cache):
    # Bounded quadrature, not all source vertices against all other vertices.
    # Polygon holes participate through the complete boundary geometry.
    if first.equals(second):
        return 0.0
    a, b = first.boundary, second.boundary
    # Interpolate individual rings explicitly: some GEOS/Shapely operations on
    # multi-line inputs use only their first component. Sampling the cumulative
    # length keeps holes and all islands in the same bounded quadrature.
    forward = sum(point.distance(b) for point in _boundary_samples(first, cache)) / BOUNDARY_SAMPLES
    backward = sum(point.distance(a) for point in _boundary_samples(second, cache)) / BOUNDARY_SAMPLES
    return max(forward, backward)


def match_zones(zones, groups, transformed):
    """Return at most five candidates per zone; never write or mutate inputs.

    ``score`` and overlap/coverage values are fractions in [0, 1]. Only a
    unique, geometrically strong, conflict-free top candidate sets
    ``high_confidence``/``can_save``. A caller still needs explicit user
    confirmation before writing any boundary. ``area_ratio`` is CAD/manual.
    """
    zones = [zone if isinstance(zone, dict) else {} for zone in (zones or [])]
    groups = list(groups or [])
    transformed = list(transformed or [])
    rows = [{'zone_id':zone.get('id', zone.get('zone_id')), 'code':str(zone.get('code') or ''),
             'name':str(zone.get('name') or ''), 'status':'unmatched', 'reason':'',
             'high_confidence':False, 'can_save':False, 'manual_area_sqm':None,
             'candidates':[], 'warnings':[]} for zone in zones]
    if not zones:
        return rows
    if STRtree is None:
        for row in rows:
            row['reason'] = '几何匹配组件不可用，请联系管理员检查 Shapely 安装'
        return rows
    project = _projection(zones, transformed)
    if project is None:
        for row in rows:
            row['reason'] = '没有有效的手绘或 CAD 经纬度，无法建立匹配参照'
        return rows
    records, invalid_cad = _cad_catalog(groups, transformed, project)
    tree = STRtree([record['geometry'] for record in records]) if records else None
    sample_cache = {}
    for zone, row in zip(zones, rows):
        try:
            manual, warnings = _manual_geometry(zone.get('boundary_points'), project)
            row['manual_area_sqm'] = round(manual.area, 3)
            row['warnings'] = warnings
            if not records:
                row['reason'] = '没有可用的完整 CAD 图形组' + (f'（{invalid_cad} 个图形组无效）' if invalid_cad else '，请先完成图纸配准')
                continue
            candidates = [_metrics(manual, records[index]['geometry'], [records[index]['id']], '图形组 ' + records[index]['label'])
                          for index in _neighbors(manual, tree, records)]
            singles = list(candidates)
            for candidate in _union_candidates(manual, tree, records):
                # A combination must improve actual overlap, rather than merely
                # adding nearby polygons to inflate coverage.
                if not singles or candidate['iou'] > max(item['iou'] for item in singles) + 0.03:
                    candidates.append(candidate)
            candidates = [candidate for candidate in candidates
                          if candidate['iou'] >= 0.02 or candidate['centroid_distance_m'] <= min(15.0, max(4.0, math.sqrt(manual.area) * 0.3))]
            candidates.sort(key=lambda candidate: (-candidate['score'], -candidate['iou'], candidate['centroid_distance_m']))
            # Boundary sampling is only needed for the most promising entries.
            for candidate in candidates[:MAX_CANDIDATES + 2]:
                deviation = _boundary_deviation(manual, candidate['_geometry'], sample_cache)
                candidate['boundary_distance_m'] = deviation
                candidate['score'] += 0.04 * math.exp(-deviation / max(2.0, math.sqrt(manual.area) * 0.1))
            candidates = [candidate for candidate in candidates if 'boundary_distance_m' in candidate]
            candidates.sort(key=lambda candidate: (-candidate['score'], -candidate['iou'], candidate['centroid_distance_m']))
            row['candidates'] = candidates[:MAX_CANDIDATES]
            if not candidates:
                row['reason'] = '附近没有足够重叠的 CAD 轮廓，不按最近距离强行匹配'
                continue
            for candidate in row['candidates']:
                geometric_high = (candidate['iou'] >= 0.78 and candidate['manual_coverage'] >= 0.85
                                  and candidate['cad_coverage'] >= 0.85
                                  and candidate['centroid_distance_m'] <= max(10.0, math.sqrt(manual.area) * 0.25)
                                  and candidate['boundary_distance_m'] <= max(4.0, math.sqrt(manual.area) * 0.15))
                candidate['_geometric_high'] = geometric_high
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, GEOSException) as error:
            row['reason'] = str(error) if isinstance(error, ValueError) else '边界几何无法计算，请检查原始手绘轮廓与 CAD 孔洞'
            row['candidates'] = []

    # Do not silently assign a popular CAD group to more than one zone. Include
    # reviewable recommendations in the ownership check, not just strong ones.
    owners = defaultdict(set)
    by_id = {row['zone_id']:row for row in rows}
    for row in rows:
        if row['candidates']:
            top = row['candidates'][0]
            if top['iou'] >= 0.2 and top['manual_coverage'] >= 0.25 and top['cad_coverage'] >= 0.25:
                for group_id in top['group_ids']:
                    owners[group_id].add(row['zone_id'])
    for row in rows:
        candidates = row['candidates']
        for position, candidate in enumerate(candidates):
            conflicts = set().union(*(owners[group_id] for group_id in candidate['group_ids'])) - {row['zone_id']}
            candidate['conflict'] = bool(conflicts)
            candidate['conflicting_zone_ids'] = sorted(conflicts, key=str)
            candidate['conflicting_zone_codes'] = [by_id[zone_id]['code'] for zone_id in candidate['conflicting_zone_ids']]
            ambiguous = position == 0 and len(candidates) > 1 and candidate['score'] - candidates[1]['score'] < 0.07 and candidate['iou'] - candidates[1]['iou'] < 0.08
            candidate['high_confidence'] = position == 0 and candidate.pop('_geometric_high', False) and not conflicts and not ambiguous and not row['warnings']
            candidate['can_save'] = candidate['high_confidence']
            candidate['quality'] = 'high' if candidate['high_confidence'] else 'review' if candidate['iou'] >= 0.3 else 'low'
            reason = f'轮廓重叠 {candidate["iou"]:.0%}，手绘覆盖 {candidate["manual_coverage"]:.0%}，CAD 覆盖 {candidate["cad_coverage"]:.0%}'
            if candidate['_combined']:
                reason += '；由多个独立图形组共同覆盖手绘的多块区域'
            if conflicts:
                reason += '；同一 CAD 轮廓也被其他区域推荐，需核对归属'
            elif ambiguous:
                reason += '；多个候选接近，需人工选择'
            elif candidate['quality'] == 'low':
                reason += '；重叠不足，不建议直接关联'
            candidate['reason'] = reason
            candidate.pop('_geometry', None)
            candidate.pop('_combined', None)
            candidate.pop('_geometric_high', None)
            for key in ('score', 'iou', 'manual_coverage', 'cad_coverage', 'area_ratio'):
                candidate[key] = round(candidate[key], 6)
            for key in ('centroid_distance_m', 'boundary_distance_m', 'cad_area_sqm'):
                candidate[key] = round(candidate[key], 3)
        if candidates:
            top = candidates[0]
            row['high_confidence'] = row['can_save'] = top['high_confidence']
            row['status'] = 'matched' if top['high_confidence'] else 'review' if top['iou'] >= 0.15 else 'unmatched'
            row['reason'] = top['reason']
    return rows
