"""
DXF file parsing utilities for boundary import.
Handles closed shape extraction, nesting detection, coordinate system detection,
and affine transformation from local DXF coords to WGS84 lat/lng.
"""
import math


def parse_dxf_shapes(uploaded_file):
    """
    Parse a DXF file and extract all closed shapes.

    Returns list of dicts:
        {id, entity_type, layer, closed, vertices:[(x,y),...], vertex_count}
    """
    import ezdxf
    import io

    # ezdxf can read from a file path or file-like object
    try:
        if hasattr(uploaded_file, 'read'):
            # Django UploadedFile: write to temp file for ezdxf (it needs seekable text stream)
            import tempfile
            content = uploaded_file.read()
            if isinstance(content, str):
                content = content.encode('utf-8', errors='ignore')
            with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                doc = ezdxf.readfile(tmp_path)
            finally:
                import os
                os.unlink(tmp_path)
        else:
            doc = ezdxf.readfile(uploaded_file)
    except Exception as e:
        return {'error': f'DXF解析失败: {str(e)}'}

    msp = doc.modelspace()
    shapes = []
    idx = 0

    for entity in msp:
        etype = entity.dxftype()
        layer = entity.dxf.get('layer', '0')

        if etype == 'LWPOLYLINE':
            closed = bool(entity.dxf.get('flags', 0) & 1)
            if not closed:
                continue
            vertices = [(float(p[0]), float(p[1])) for p in entity.get_points(format='xy')]
            if len(vertices) < 3:
                continue
            shapes.append({
                'id': f'shape_{idx}',
                'entity_type': 'LWPOLYLINE',
                'layer': layer,
                'closed': True,
                'vertices': vertices,
                'vertex_count': len(vertices),
            })
            idx += 1

        elif etype == 'POLYLINE':
            # Check POLYLINE2D with closed flag
            closed = bool(entity.dxf.get('flags', 0) & 1)
            if not closed:
                continue
            vertices = []
            for v in entity.vertices:
                vertices.append((float(v.dxf.location.x), float(v.dxf.location.y)))
            if len(vertices) < 3:
                continue
            shapes.append({
                'id': f'shape_{idx}',
                'entity_type': 'POLYLINE',
                'layer': layer,
                'closed': True,
                'vertices': vertices,
                'vertex_count': len(vertices),
            })
            idx += 1

        elif etype == 'CIRCLE':
            cx = float(entity.dxf.center.x)
            cy = float(entity.dxf.center.y)
            r = float(entity.dxf.radius)
            # Generate 36 evenly-spaced vertices
            n = 36
            vertices = []
            for i in range(n):
                angle = 2 * math.pi * i / n
                vertices.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
            shapes.append({
                'id': f'shape_{idx}',
                'entity_type': 'CIRCLE',
                'layer': layer,
                'closed': True,
                'vertices': vertices,
                'vertex_count': n,
            })
            idx += 1

        elif etype == 'ELLIPSE':
            cx = float(entity.dxf.center.x)
            cy = float(entity.dxf.center.y)
            # Major axis vector
            mx = float(entity.dxf.major_axis.x)
            my = float(entity.dxf.major_axis.y)
            ratio = float(entity.dxf.ratio)
            start = float(entity.dxf.start_param)
            end = float(entity.dxf.end_param)

            # Only treat as closed if it's a full ellipse
            if not (start == 0 and abs(end - 2 * math.pi) < 0.01):
                continue

            n = 36
            vertices = []
            for i in range(n):
                t = 2 * math.pi * i / n
                # Minor axis is major rotated 90° and scaled by ratio
                # Parametric: (cx + cos(t)*mx - sin(t)*ratio*my, cy + cos(t)*my + sin(t)*ratio*mx)
                # Actually: P(t) = center + cos(t)*major_axis + sin(t)*minor_axis
                # minor_axis = ratio * rotate90(major_axis)
                # rotate90(mx,my) = (-my, mx)
                minx = ratio * (-my)
                miny = ratio * mx
                px = cx + math.cos(t) * mx + math.sin(t) * minx
                py = cy + math.cos(t) * my + math.sin(t) * miny
                vertices.append((px, py))

            shapes.append({
                'id': f'shape_{idx}',
                'entity_type': 'ELLIPSE',
                'layer': layer,
                'closed': True,
                'vertices': vertices,
                'vertex_count': n,
            })
            idx += 1

    return shapes


def detect_coord_system(shapes):
    """
    Auto-detect the DXF coordinate system type.

    Returns dict:
        {type: 'wgs84'|'local', info: str, need_anchors: bool}
    """
    if not shapes:
        return {'type': 'local', 'info': '无图形数据', 'need_anchors': True}

    all_x = []
    all_y = []
    for s in shapes:
        for (x, y) in s['vertices']:
            all_x.append(x)
            all_y.append(y)

    if not all_x:
        return {'type': 'local', 'info': '无顶点数据', 'need_anchors': True}

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    # WGS84 check: X (longitude) in [-180, 180], Y (latitude) in [-90, 90]
    # Note: some DXF files swap X/Y — check both orientations
    x_is_lng = -180 <= min_x and max_x <= 180
    y_is_lat = -90 <= min_y and max_y <= 90

    y_is_lng = -180 <= min_y and max_y <= 180
    x_is_lat = -90 <= min_x and max_x <= 90

    if x_is_lng and y_is_lat:
        # X=longitude, Y=latitude (standard DXF)
        return {
            'type': 'wgs84',
            'info': '检测到WGS84坐标系 (X=经度, Y=纬度)',
            'need_anchors': False,
            'axis_map': 'xy_to_lnglat',  # x→lng, y→lat
        }
    elif x_is_lat and y_is_lng:
        # X=latitude, Y=longitude (swapped)
        return {
            'type': 'wgs84',
            'info': '检测到WGS84坐标系 (X=纬度, Y=经度)',
            'need_anchors': False,
            'axis_map': 'xy_to_latlng',  # x→lat, y→lng
        }

    # Not WGS84 — require manual georeferencing
    return {
        'type': 'local',
        'info': f'本地坐标系 (X: {min_x:.1f}~{max_x:.1f}, Y: {min_y:.1f}~{max_y:.1f})，需要手动配准',
        'need_anchors': True,
        'extent': {'min_x': min_x, 'max_x': max_x, 'min_y': min_y, 'max_y': max_y},
    }


def shapes_to_latlng_auto(shapes, axis_map):
    """
    Convert shapes from WGS84 DXF coordinates to the system's {lat, lng} format.
    axis_map: 'xy_to_lnglat' means DXF X→lng, Y→lat
              'xy_to_latlng' means DXF X→lat, Y→lng
    """
    converted = []
    for s in shapes:
        ring = []
        for (x, y) in s['vertices']:
            if axis_map == 'xy_to_lnglat':
                ring.append({'lat': y, 'lng': x})
            else:
                ring.append({'lat': x, 'lng': y})
        converted.append({
            'id': s['id'],
            'entity_type': s['entity_type'],
            'layer': s['layer'],
            'vertices_latlng': ring,
            'vertex_count': len(ring),
        })
    return converted


# ─── Nesting Detection ───

def _point_in_polygon(px, py, polygon):
    """Ray-casting algorithm to test if point (px, py) is inside polygon."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _centroid(vertices):
    """Compute the centroid of a polygon."""
    n = len(vertices)
    if n == 0:
        return (0, 0)
    cx = sum(v[0] for v in vertices) / n
    cy = sum(v[1] for v in vertices) / n
    return (cx, cy)


def detect_nesting(shapes):
    """
    Detect nesting relationships among shapes.
    Returns a list of groups, each containing:
        {id, outer: shape_index, holes: [shape_indices], shape_ids: [...]}
    Outer shapes with no holes form their own group with empty holes list.
    """
    if not shapes:
        return []

    n = len(shapes)
    # Compute centroids
    centroids = [_centroid(s['vertices']) for s in shapes]

    # Compute areas (shoelace formula) for containment ordering
    def polygon_area(vertices):
        area = 0
        nv = len(vertices)
        for i in range(nv):
            j = (i + 1) % nv
            area += vertices[i][0] * vertices[j][1]
            area -= vertices[j][0] * vertices[i][1]
        return abs(area) / 2.0

    areas = [polygon_area(s['vertices']) for s in shapes]

    # Build containment: shape i is contained by shape j if centroid[i] is inside polygon[j]
    # and area[i] < area[j]
    contained_by = [None] * n  # contained_by[i] = index of smallest shape that contains i
    for i in range(n):
        best_container = None
        best_area = float('inf')
        for j in range(n):
            if i == j:
                continue
            if areas[i] >= areas[j]:
                continue
            cx, cy = centroids[i]
            if _point_in_polygon(cx, cy, shapes[j]['vertices']):
                if areas[j] < best_area:
                    best_area = areas[j]
                    best_container = j
        contained_by[i] = best_container

    # Build groups: find top-level shapes (not contained by anything)
    # and their direct children (holes)
    # For simplicity: only one level of nesting (outer + holes)
    # If a hole contains another shape, that inner shape is ignored (would need recursive grouping)
    top_level = [i for i in range(n) if contained_by[i] is None]

    groups = []
    for outer_idx in top_level:
        holes = []
        # Find shapes directly contained by this outer
        for i in range(n):
            if contained_by[i] == outer_idx:
                holes.append(i)
        groups.append({
            'id': f'group_{len(groups)}',
            'outer': outer_idx,
            'holes': holes,
            'shape_ids': [shapes[outer_idx]['id']] + [shapes[h]['id'] for h in holes],
        })

    return groups


# ─── Affine Transform ───

def compute_affine_transform(anchor_pairs):
    """
    Compute an affine transform from DXF local coords to WGS84 lat/lng.

    anchor_pairs: list of {dxf_x, dxf_y, lat, lng} dicts (minimum 2)

    Returns a callable: transform(dxf_x, dxf_y) -> (lat, lng)
    or an error string.
    """
    if len(anchor_pairs) < 2:
        return '需要至少2个锚点'

    if len(anchor_pairs) == 2:
        return _similarity_transform(anchor_pairs)
    else:
        return _affine_transform_ls(anchor_pairs)


def _similarity_transform(pairs):
    """
    2-point similarity transform: translation + rotation + uniform scale.
    lat = a * dxf_x + b * dxf_y + c
    lng = -b * dxf_x + a * dxf_y + d  (rotation by same angle, same scale)

    With 2 points we get 4 equations for 4 unknowns (a, b, c, d).
    """
    x1, y1 = pairs[0]['dxf_x'], pairs[0]['dxf_y']
    lat1, lng1 = pairs[0]['lat'], pairs[0]['lng']
    x2, y2 = pairs[1]['dxf_x'], pairs[1]['dxf_y']
    lat2, lng2 = pairs[1]['lat'], pairs[1]['lng']

    # dx, dy in DXF space
    ddx = x2 - x1
    ddy = y2 - y1
    ddx2 = ddx * ddx + ddy * ddy

    if ddx2 < 1e-12:
        return '两个锚点的DXF坐标不能相同'

    # dlat, dlng in WGS84 space
    dlat = lat2 - lat1
    dlng = lng2 - lng1

    # a = (ddx*dlat + ddy*dlng) / ddx2
    # b = (ddy*dlat - ddx*dlng) / ddx2
    a = (ddx * dlat + ddy * dlng) / ddx2
    b = (ddy * dlat - ddx * dlng) / ddx2

    c = lat1 - a * x1 - b * y1
    d = lng1 - (-b) * x1 - a * y1

    def transform(dx, dy):
        lat = a * dx + b * dy + c
        lng = -b * dx + a * dy + d
        return (lat, lng)

    return transform


def _affine_transform_ls(pairs):
    """
    N-point full affine transform via least-squares (no numpy).
    lat = a*x + b*y + c
    lng = d*x + e*y + f

    Solve two independent 3x3 systems (or overdetermined via normal equations).
    """
    n = len(pairs)
    # Build normal equation A^T A * coeff = A^T b
    # For lat: [x, y, 1] -> lat
    # A^T A is 3x3 symmetric
    sxx = sum(p['dxf_x'] ** 2 for p in pairs)
    syy = sum(p['dxf_y'] ** 2 for p in pairs)
    sxy = sum(p['dxf_x'] * p['dxf_y'] for p in pairs)
    sx = sum(p['dxf_x'] for p in pairs)
    sy = sum(p['dxf_y'] for p in pairs)

    # A^T A matrix
    ATA = [
        [sxx, sxy, sx],
        [sxy, syy, sy],
        [sx, sy, float(n)],
    ]

    # A^T b for lat
    bx_lat = [sum(p['dxf_x'] * p['lat'] for p in pairs),
              sum(p['dxf_y'] * p['lat'] for p in pairs),
              sum(p['lat'] for p in pairs)]

    # A^T b for lng
    bx_lng = [sum(p['dxf_x'] * p['lng'] for p in pairs),
              sum(p['dxf_y'] * p['lng'] for p in pairs),
              sum(p['lng'] for p in pairs)]

    # Solve 3x3 system using Cramer's rule
    def det3(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

    def solve3(matrix, rhs):
        D = det3(matrix)
        if abs(D) < 1e-12:
            return None
        n_col = len(rhs)
        result = []
        for col in range(n_col):
            # Replace column col with rhs
            m = [row[:] for row in matrix]
            for row in range(3):
                m[row][col] = rhs[row]
            result.append(det3(m) / D)
        return result

    coeff_lat = solve3(ATA, bx_lat)
    coeff_lng = solve3(ATA, bx_lng)

    if coeff_lat is None or coeff_lng is None:
        return '锚点坐标无法求解变换方程（可能共线）'

    a, b, c = coeff_lat
    d, e, f = coeff_lng

    def transform(dx, dy):
        lat = a * dx + b * dy + c
        lng = d * dx + e * dy + f
        return (lat, lng)

    return transform


def transform_shape(shape, transform_fn):
    """Apply transform function to a shape's vertices. Returns new dict with vertices_latlng."""
    ring = []
    for (x, y) in shape['vertices']:
        lat, lng = transform_fn(x, y)
        ring.append({'lat': lat, 'lng': lng})
    return {
        'id': shape['id'],
        'entity_type': shape['entity_type'],
        'layer': shape['layer'],
        'vertices_latlng': ring,
        'vertex_count': len(ring),
    }


def transform_group_to_boundary(group, shapes, transform_fn):
    """
    Transform a nesting group into multi-ring boundary_points format.
    Returns [[{lat,lng},...]] with outer ring first, then holes.
    """
    outer_shape = shapes[group['outer']]
    outer_ring = []
    for (x, y) in outer_shape['vertices']:
        lat, lng = transform_fn(x, y)
        outer_ring.append({'lat': lat, 'lng': lng})

    rings = [outer_ring]
    for hole_idx in group['holes']:
        hole_shape = shapes[hole_idx]
        hole_ring = []
        for (x, y) in hole_shape['vertices']:
            lat, lng = transform_fn(x, y)
            hole_ring.append({'lat': lat, 'lng': lng})
        rings.append(hole_ring)

    return rings


def shapes_to_geojson_preview(shapes, groups=None):
    """
    Build a lightweight preview structure for the frontend.
    Returns dict with shapes list and groups list, including DXF coords.
    """
    result_shapes = []
    for s in shapes:
        cx, cy = _centroid(s['vertices'])
        result_shapes.append({
            'id': s['id'],
            'entity_type': s['entity_type'],
            'layer': s['layer'],
            'vertex_count': s['vertex_count'],
            'centroid': {'x': round(cx, 2), 'y': round(cy, 2)},
        })

    result_groups = []
    if groups:
        for g in groups:
            outer = shapes[g['outer']]
            holes_info = []
            for h in g['holes']:
                hs = shapes[h]
                holes_info.append({
                    'id': hs['id'],
                    'entity_type': hs['entity_type'],
                    'vertex_count': hs['vertex_count'],
                })
            result_groups.append({
                'id': g['id'],
                'outer': {
                    'id': outer['id'],
                    'entity_type': outer['entity_type'],
                    'layer': outer['layer'],
                    'vertex_count': outer['vertex_count'],
                },
                'holes': holes_info,
                'has_holes': len(g['holes']) > 0,
            })

    return {'shapes': result_shapes, 'groups': result_groups}
