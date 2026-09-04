"""
DXF file parsing utilities for boundary import.
Handles closed shape extraction, nesting detection, coordinate system detection,
and affine transformation from local DXF coords to WGS84 lat/lng.
"""
import math


# ─── Site Calibration ───
# Two reference points mapping local DXF coordinates to WGS84 (lat, lng).
# Update these when the surveyor's coordinate system changes.
SITE_CALIBRATION_POINTS = [
    {'dxf_x': 18199.4368, 'dxf_y': -10216.4603, 'lat': 31.1431589, 'lng': 121.6579836},
    {'dxf_x': 18220.5437, 'dxf_y': -10196.3886, 'lat': 31.1433414, 'lng': 121.6582022},
]


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

        elif etype == 'HATCH':
            # HATCH boundaries: each polyline loop is a closed polygon (edge loops skipped).
            for path in (getattr(entity, 'paths', None) or []):
                if getattr(path, 'PATH_TYPE', None) != 'PolylinePath':
                    continue
                verts = []
                for v in (getattr(path, 'vertices', None) or []):
                    try:
                        verts.append((float(v[0]), float(v[1])))
                    except (TypeError, IndexError, ValueError):
                        continue
                if len(verts) >= 3:
                    shapes.append({
                        'id': f'shape_{idx}',
                        'entity_type': 'HATCH',
                        'layer': layer,
                        'closed': True,
                        'vertices': verts,
                        'vertex_count': len(verts),
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

    # Not WGS84 — check if site calibration is available for auto-transform
    has_calibration = bool(SITE_CALIBRATION_POINTS) and len(SITE_CALIBRATION_POINTS) >= 2

    return {
        'type': 'local',
        'info': f'本地坐标系 (X: {min_x:.1f}~{max_x:.1f}, Y: {min_y:.1f}~{max_y:.1f})',
        'need_anchors': not has_calibration,
        'auto_calibrated': has_calibration,
        'extent': {'min_x': min_x, 'max_x': max_x, 'min_y': min_y, 'max_y': max_y},
    }


def auto_calibrate(shapes):
    """
    Auto-transform local DXF coordinates to WGS84 using site calibration points.
    Negates DXF Y axis to correct for the common CAD Y-down vs geographic Y-up mismatch.
    Returns list of transformed shape dicts with vertices_latlng, or None if no calibration.
    """
    if not SITE_CALIBRATION_POINTS or len(SITE_CALIBRATION_POINTS) < 2:
        return None

    # Build calibration with negated Y (reflect to match geographic handedness)
    cal = [
        {'dxf_x': p['dxf_x'], 'dxf_y': -p['dxf_y'], 'lat': p['lat'], 'lng': p['lng']}
        for p in SITE_CALIBRATION_POINTS
    ]
    transform_fn = _similarity_transform(cal)
    if isinstance(transform_fn, str):
        return None  # error string

    # Apply transform with negated Y on each vertex
    result = []
    for s in shapes:
        ring = []
        for (x, y) in s['vertices']:
            lat, lng = transform_fn(x, -y)
            ring.append({'lat': lat, 'lng': lng})
        result.append({
            'id': s['id'],
            'entity_type': s['entity_type'],
            'layer': s['layer'],
            'vertices_latlng': ring,
            'vertex_count': len(ring),
        })
    return result


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


def similarity_transform_ls(pairs):
    """N点(≥2)相似变换最小二乘：lat = a*x + b*y + c；lng = -b*x + a*y + d。

    与 ``_similarity_transform`` 同一变换形式；N≥3 时存在多余约束，可给出
    每点残差（米）与 RMS，用于标定质量评估。传入的 pairs 需与现有调用方
    一致（DXF y 已取反）。返回 ``(transform_fn, stats)``；退化输入返回
    ``(None, 错误消息)``。
    """
    import math
    n = len(pairs)
    if n < 2:
        return None, '标定点至少需要 2 个'
    mx = sum(p['dxf_x'] for p in pairs) / n
    my = sum(p['dxf_y'] for p in pairs) / n
    mlat = sum(p['lat'] for p in pairs) / n
    mlng = sum(p['lng'] for p in pairs) / n
    nr = ni = denom = 0.0
    for p in pairs:
        x, y = p['dxf_x'] - mx, p['dxf_y'] - my
        la, ln = p['lat'] - mlat, p['lng'] - mlng
        nr += x * la + y * ln
        ni += y * la - x * ln
        denom += x * x + y * y
    if denom < 1e-12:
        return None, '标定用的 DXF 点不能全部重合'
    a = nr / denom
    b = ni / denom
    c = mlat - a * mx - b * my
    d = mlng + b * mx - a * my

    def transform(x, y):
        return (a * x + b * y + c, -b * x + a * y + d)

    # 残差（米）：等距圆柱近似换算经纬度差
    residuals = []
    for p in pairs:
        plat, plng = transform(p['dxf_x'], p['dxf_y'])
        dlatm = (p['lat'] - plat) * 111320.0
        dlngm = (p['lng'] - plng) * 111320.0 * math.cos(math.radians(p['lat']))
        residuals.append(math.hypot(dlatm, dlngm))
    rms = math.sqrt(sum(r * r for r in residuals) / n)
    stats = {
        'a': a, 'b': b, 'c': c, 'd': d,
        'scale': math.hypot(a, b),
        'rotation_deg': math.degrees(math.atan2(-b, a)),
        'rms_m': rms,
        'residuals_m': [round(r, 2) for r in residuals],
        'n': n,
    }
    return transform, stats


def similarity_inverse(a, b, c, d):
    """``similarity_transform_ls`` 系数的逆变换：x = ia*lat + ib*lng + ic；
    y = -ib*lat + ia*lng + id。用于把已存的 lat/lng 还原回本地坐标
    （重新校准 = old⁻¹ ∘ new）。退化返回 None。
    """
    s = a * a + b * b
    if s < 1e-18:
        return None
    return {
        'ia': a / s, 'ib': -b / s,
        'ic': (b * d - a * c) / s,
        'id': -(b * c + a * d) / s,
    }


# ── 薄板样条 TPS：多点橡皮筋变换，吸收卫星正射影像的局部畸变 ────────────
#
# 相似变换（上面那套）只有 4 个自由度（平移2+旋转1+单一比例），装不下
# 卫星图不同区域比例尺略有差异的局部畸变——控制点一多残差就互相打架。
# TPS 是 GIS 配准的标准解（QGIS/ArcGIS 的 rubber sheeting）：每个控制点
# 精确落位，点之间最小弯曲平滑变形。实现为 (N+3) 线性方程组的纯 Python
# 高斯消元（N≤10，规模可忽略，避免引入 numpy 依赖）。

def _tps_kernel(r):
    """U(r) = r² ln r（r=0 时取 0）。"""
    return r * r * math.log(r) if r > 0 else 0.0


def _solve_linear(a, b):
    """带部分主元的高斯消元，解 a·x = b（a 方阵）。返回解列表，奇异返回 None。"""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None   # 奇异
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        for r in range(col + 1, n):
            f = m[r][col] / pv
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s2 = m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s2 / m[i][i]
    return x


def _tps_fit_core(src, dst):
    """TPS 核心：src/dst 均为 [(x, y)]，返回可序列化系数 dict。

    方程组 [[K P][Pᵀ 0]]·[w a]ᵀ = [v 0]ᵀ，K_ij = U(|si-sj|)，P = [1 x y]。
    输入先做质心+尺度归一化（DXF 坐标量级 1e4~1e6，裸拟合 r²ln r 会把
    条件数炸掉）。重复/过近的点会得到奇异方程组 → 返回 None。
    numpy 可用时走 np.linalg.solve（300 点量级也是毫秒级）；否则纯 Python
    高斯消元回退（≤30 点实时，更多点会慢）。
    """
    n = len(src)
    if n < 3:
        return None
    cx = sum(p[0] for p in src) / n
    cy = sum(p[1] for p in src) / n
    s = max((math.hypot(p[0] - cx, p[1] - cy) for p in src), default=0.0)
    if s < 1e-9:
        return None   # 全部重合
    norm = [((p[0] - cx) / s, (p[1] - cy) / s) for p in src]

    try:
        import numpy as _np
    except ImportError:
        _np = None
    if _np is not None:
        xs = _np.array(norm)
        d = _np.linalg.norm(xs[:, None, :] - xs[None, :, :], axis=2)
        with _np.errstate(divide='ignore', invalid='ignore'):
            k = _np.where(d > 0, d * d * _np.log(_np.where(d > 0, d, 1.0)), 0.0)
        mat = _np.zeros((n + 3, n + 3))
        mat[:n, :n] = k
        mat[:n, n] = 1.0
        mat[:n, n + 1] = xs[:, 0]
        mat[:n, n + 2] = xs[:, 1]
        mat[n, :n] = 1.0
        mat[n + 1, :n] = xs[:, 0]
        mat[n + 2, :n] = xs[:, 1]
        out = {}
        for axis, key in ((0, 'u'), (1, 'v')):
            rhs = _np.zeros(n + 3)
            rhs[:n] = [dst[i][axis] for i in range(n)]
            try:
                sol = _np.linalg.solve(mat, rhs)
            except _np.linalg.LinAlgError:
                return None
            out[key + 'w'] = [float(v) for v in sol[:n]]
            out[key + 'a'] = [float(v) for v in sol[n:]]
        out.update({'cx': cx, 'cy': cy, 's': s, 'src': [list(p) for p in src], 'n': n})
        return out

    mat = [[0.0] * (n + 3) for _ in range(n + 3)]
    for i in range(n):
        for j in range(n):
            if i != j:
                mat[i][j] = _tps_kernel(math.hypot(norm[i][0] - norm[j][0],
                                                    norm[i][1] - norm[j][1]))
        mat[i][n] = 1.0
        mat[i][n + 1] = norm[i][0]
        mat[i][n + 2] = norm[i][1]
        mat[n][i] = 1.0
        mat[n + 1][i] = norm[i][0]
        mat[n + 2][i] = norm[i][1]

    out = {}
    for axis, key in ((0, 'u'), (1, 'v')):
        rhs = [dst[i][axis] for i in range(n)] + [0.0, 0.0, 0.0]
        sol = _solve_linear(mat, rhs)
        if sol is None:
            return None
        out[key + 'w'] = sol[:n]
        out[key + 'a'] = sol[n:]
    out.update({'cx': cx, 'cy': cy, 's': s, 'src': [list(p) for p in src], 'n': n})
    return out


def tps_from_coeffs(c):
    """序列化系数 → transform_fn（与 tps_fit 返回的 fn 同型，供反向评估）。"""
    src, s, cx, cy = c['src'], c['s'], c['cx'], c['cy']
    n = c['n']
    nsrc = [((p[0] - cx) / s, (p[1] - cy) / s) for p in src]

    def transform(x, y):
        ux, uy = (x - cx) / s, (y - cy) / s
        su = c['ua'][0] + c['ua'][1] * ux + c['ua'][2] * uy
        sv = c['va'][0] + c['va'][1] * ux + c['va'][2] * uy
        for i in range(n):
            k = _tps_kernel(math.hypot(ux - nsrc[i][0], uy - nsrc[i][1]))
            if k:
                su += c['uw'][i] * k
                sv += c['vw'][i] * k
        return (su, sv)

    return transform


def _residual_m(pred, lat, lng):
    dlatm = (lat - pred[0]) * 111320.0
    dlngm = (lng - pred[1]) * 111320.0 * math.cos(math.radians(lat))
    return math.hypot(dlatm, dlngm)


def tps_fit(pairs):
    """N点(≥4) TPS 拟合：pairs 同 similarity_transform_ls 格式。

    返回 (transform_fn, stats)。控制点零残差（精确落位），因此 stats 的
    residuals_m / rms_m 用**留一交叉验证**（LOO）：逐点用其余点重拟合、
    预测该点——这是 TPS 泛化误差的诚实度量（GIS 惯例：TPS 在控制点上
    残差恒为 0，展示残差没有意义）。退化输入返回 (None, 错误消息)。
    """
    n = len(pairs)
    if n < 4:
        return None, 'TPS 至少需要 4 个标定点'
    src = [(p['dxf_x'], p['dxf_y']) for p in pairs]
    dst = [(p['lat'], p['lng']) for p in pairs]
    coeffs = _tps_fit_core(src, dst)
    if coeffs is None:
        return None, '标定点过于集中或存在重复点，无法拟合 TPS'
    fn = tps_from_coeffs(coeffs)

    # LOO 残差：n-1 ≥ 3 点的核心拟合仍然成立。n 次重拟合在 numpy 下是
    # 毫秒级/次；无 numpy 的纯 Python 回退在 n>30 时会慢到不可用 → 跳过。
    try:
        import numpy  # noqa: F401
        _have_np = True
    except ImportError:
        _have_np = False
    residuals = []
    if _have_np or n <= 30:
        for i in range(n):
            sub = _tps_fit_core(src[:i] + src[i + 1:], dst[:i] + dst[i + 1:])
            if sub is None:
                residuals.append(None)
                continue
            sub_fn = tps_from_coeffs(sub)
            residuals.append(_residual_m(sub_fn(*src[i]), dst[i][0], dst[i][1]))
    valid = [r for r in residuals if r is not None]
    rms = math.sqrt(sum(r * r for r in valid) / len(valid)) if valid else None

    # 对照：同样点数下的相似变换 RMS（用户能看到 TPS 带来多大改善）
    _sim_fn, sim_stats = similarity_transform_ls(pairs)
    stats = {
        'method': 'tps', 'n': n,
        'coeffs': coeffs,
        'rms_m': rms,
        'residuals_m': [None if r is None else round(r, 2) for r in residuals],
        'sim_rms_m': sim_stats['rms_m'] if sim_stats else None,
        'scale': sim_stats['scale'] if sim_stats else None,
        'rotation_deg': sim_stats['rotation_deg'] if sim_stats else None,
    }
    return fn, stats


def mls_fit(pairs, _skip=None):
    """N点(≥2) MLS 相似变形（Moving Least Squares，Schaefer et al. 2006 的
    加权相似最小二乘等价形式）：对每个待求点 v，按 w_i = 1/(d_i²+ε²) 加权
    在控制点上拟合一个局部相似变换（中心化的相似 LS 闭式解）再作用于 v。

    与 TPS 的取舍：MLS 每个点只受**附近**控制点显著影响——控制点稀疏/
    覆盖区外的行为远比 TPS 稳定（远处自动退化成整体相似变换而不是外推
    发飘），单个坏点也只污染局部。控制点上近似精确落位（ε 很小时权重
    完全集中在自身）。无全局方程组、无需数值求解。评估 O(N)/点。

    ``_skip``：LOO 用——跳过该下标的控制点。
    """
    n = len(pairs)
    if n - (1 if _skip is not None else 0) < 2:
        return None, 'MLS 至少需要 2 个标定点'
    px = [p['dxf_x'] for p in pairs]
    py = [p['dxf_y'] for p in pairs]
    span = max(max(px) - min(px), max(py) - min(py))
    eps2 = (max(span, 1.0) * 1e-4) ** 2   # v→p_j 时权重被 j 完全主导

    def transform(x, y, _skip=None):
        sw = nr = ni = den = sxw = syw = slaw = slnw = 0.0
        for i in range(n):
            if _skip is not None and i == _skip:
                continue
            w = 1.0 / ((px[i] - x) ** 2 + (py[i] - y) ** 2 + eps2)
            sw += w
            sxw += w * px[i]; syw += w * py[i]
            slaw += w * pairs[i]['lat']; slnw += w * pairs[i]['lng']
        if sw <= 0:
            return None
        mx, my, mla, mln = sxw / sw, syw / sw, slaw / sw, slnw / sw
        for i in range(n):
            if _skip is not None and i == _skip:
                continue
            w = 1.0 / ((px[i] - x) ** 2 + (py[i] - y) ** 2 + eps2)
            cx, cy = px[i] - mx, py[i] - my
            cla, cln = pairs[i]['lat'] - mla, pairs[i]['lng'] - mln
            nr += w * (cx * cla + cy * cln)
            ni += w * (cy * cla - cx * cln)
            den += w * (cx * cx + cy * cy)
        if den < 1e-18:
            return None
        a, b = nr / den, ni / den
        dx, dy = x - mx, y - my
        return (a * dx + b * dy + mla, -b * dx + a * dy + mln)

    fn = lambda x, y: transform(x, y)

    # LOO 残差：MLS 无需重拟合——评估时跳过自身即可，天然精确的留一验证
    residuals = []
    for j in range(n):
        pred = transform(px[j], py[j], _skip=j)
        residuals.append(None if pred is None else
                         _residual_m(pred, pairs[j]['lat'], pairs[j]['lng']))
    valid = [r for r in residuals if r is not None]
    rms = math.sqrt(sum(r * r for r in valid) / len(valid)) if valid else None
    _sf, sim_stats = similarity_transform_ls(pairs)
    stats = {
        'method': 'mls', 'n': n,
        'rms_m': rms,
        'residuals_m': [None if r is None else round(r, 2) for r in residuals],
        'sim_rms_m': sim_stats['rms_m'] if sim_stats else None,
        'scale': sim_stats['scale'] if sim_stats else None,
        'rotation_deg': sim_stats['rotation_deg'] if sim_stats else None,
    }
    return fn, stats


def fit_calibration_transform(pairs, method=None):
    """按 method/点数选型：'mls' → MLS；≥4 → TPS 橡皮筋；2-3 → 相似 LS。

    所有标定链路（预览换算 / info / 保存校验 / 追溯应用）统一走这里，
    保证「保存时验证的变换」与「导入时使用的变换」是同一个。
    """
    if method == 'mls' and len(pairs) >= 2:
        return mls_fit(pairs)
    if len(pairs) >= 4:
        return tps_fit(pairs)
    return similarity_transform_ls(pairs)


def fit_calibration_inverse(pairs, method=None):
    """标定的反向变换 (lat,lng)→(dxf_x, dxf_y)。TPS/MLS 无解析逆——直接把
    点对调个方向重新拟合（GIS 常规做法，误差量级与正向一致）。

    返回 inverse_fn 或 None。注意 pairs 的 dxf_y 已是取反后的 negY 空间
    （与 similarity_inverse 的返回语义一致：调用方再自行取反回 DXF y）。
    """
    rev = [{'dxf_x': p['lat'], 'dxf_y': p['lng'],
            'lat': p['dxf_x'], 'lng': p['dxf_y']} for p in pairs]
    fn, _stats = fit_calibration_transform(rev, 'mls' if method == 'mls' else None)
    return fn if callable(fn) else None


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
