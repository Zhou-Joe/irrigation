"""DXF 管线导入：把灌溉 CAD 图纸解析成 Pipeline + PipeValve 行。

面向的图纸约定（与 Test dxf.dxf 一致）：
  * 管道按图层分类，图层名常直接是管径（``100``/``75``/``150``…）或
    ``WD``（疏水/放水）、``AD-I-LL/ML``（支管/主管）等关键词层；
  * 阀门是 INSERT 块，块名 ``WID_Val-*`` 的后缀编码阀门类型，插入点
    几乎总落在管道线上；块内画着的线条几何另展开到 ``块·<块名>``
    虚拟图层（默认不勾选，可当管线导入）；
  * 文字标注（MTEXT/TEXT，多在 ``设备编号``/``POC`` 层）是最近的阀门/
    设备编号，如 ``9-GV6``。

线条实体一次收全：LINE/LWPOLYLINE/POLYLINE/ARC/SPLINE/ELLIPSE/CIRCLE，
弧段按 ≤8° 或矢高细分；闭合折线是环状管网，按完整环收集。

流程：``analyze_dxf_pipelines`` 产出图层/块/标注清单 + 预览几何，并按
内容 hash 把解析结果缓存（导入阶段凭 token 复用，同一图纸不再二次解析）；
``import_dxf_pipelines`` 按用户映射把管道折线做连通分解（交叉点断开、
链式合并，每条简单路径 = 一条 Pipeline），阀门吸附到最近管段继承管径，
就近标注写入阀门名。坐标转换复用 ``dxf_utils.SITE_CALIBRATION_POINTS``
的相似变换（Y 取反），与区域边界导入落在同一套 WGS84 上。

性能要点（对千段管网）：
  * zone 边界只从 DB 读一次，预计算环+bbox，路径穿越检测全部在内存做；
  * 名称唯一性判重在内存 set 上；
  * 阀门→管段吸附走均匀网格空间索引，标注匹配按 x 排序窗口扫描；
  * SNAP_TOL/LABEL_RADIUS 按「米 ÷ 标定比例」换算成绘图单位，图纸单位
    不是米时依然正确。
"""

import hashlib
import math
import re
from collections import defaultdict

# 块名 → 默认阀门类型（甲方六类块；先按全名关键词匹配，再退回后缀表）
BLOCK_TYPE_KEYWORDS = [
    ('pullbox', r'拉线|牵引|PULL|\bPB\b'),
    ('qcv', r'取水|QCV|QUICK'),
    ('washdown', r'冲洗|WASH|\bWD\b'),
    ('solenoid', r'电磁|SOLENOID|\bCF\b|ZONE|自控'),
    ('angle', r'角阀|ANGLE|\bAV\b'),
    ('gate', r'闸|GATE|\bGV\b'),
]
# WID_Val-* 系列的后缀速查（测试图纸的命名习惯）
DEFAULT_VALVE_TYPE_BY_SUFFIX = {
    'cf': 'solenoid',    # Zone 自控电磁阀（数量最多）
    'lc': 'solenoid',    # 带 ATTDEF 的定位控制阀
    'att': 'solenoid',
    'bt': 'gate',        # 手动闸/蝶阀
    'btb': 'gate',
    'sf': 'angle',       # 手动角阀
    'hxf': 'washdown',   # WD 冲洗
    'ctf': 'washdown',
    'stf': 'washdown',
    'wd': 'washdown',
    'misc': 'gate',
}

# 图层名 → 线类型（甲方六类线；顺序即优先级，冲厕/套管/控制/通讯要先于
# 灌溉的宽松规则命中）
LAYER_TYPE_KEYWORDS = [
    ('toilet', r'冲厕|厕所|中水|TOIL'),
    ('casing', r'套管|过路|CAS'),
    ('control', r'控制|CTRL|CTL'),
    ('comm', r'通讯|通信|COMM'),
    ('flush', r'冲洗|疏水|放水|\bWD\b|WASH|FLUSH'),
    # 灌溉主干/支管命名（AD-I-LL/ML、LATERAL 等）——层名常不带管径数字，
    # 命中即默认勾选，不再整层漏导入
    ('irrigation', r'灌溉|喷灌|滴灌|IRRIG|\bLL\b|\bML\b|\bWL\b|LATERAL|MAINLINE'),
]

# 端点吸附容差（米）——判定两条折线相接
JOIN_TOL_M = 0.3
# 阀门贴线容差（米）——超出则不挂到任何管线
SNAP_TOL_M = 1.5
# 标注→阀门匹配半径（米）
LABEL_RADIUS_M = 2.5
# 解析缓存 TTL（秒）——analyze → import 之间复用
PARSE_CACHE_TTL = 15 * 60
# 缓存 key 前缀带解析器版本：解析逻辑升级后旧缓存立即失效
PARSE_CACHE_KEY_PREFIX = 'dxf:parse:v3:'


def _guess_line_type(layer_name):
    for t, pat in LAYER_TYPE_KEYWORDS:
        if re.search(pat, layer_name, re.I):
            return t
    return 'irrigation'


def _guess_block_type(block_name):
    low = block_name.lower()
    for t, pat in BLOCK_TYPE_KEYWORDS:
        if re.search(pat, low, re.I):
            return t
    suffix = low.rsplit('-', 1)[-1] if '-' in low else ''
    return DEFAULT_VALVE_TYPE_BY_SUFFIX.get(suffix, 'gate')


def _layer_diameter_guess(name):
    m = re.search(r'(\d+(?:\.\d+)?)', name)
    return float(m.group(1)) if m else None


def _layer_include_guess(name):
    """图层默认勾选：层名带管径数字 或 命中管线关键词（AD-I-LL/WD 这类
    不带数字的支管/冲洗层不再整层漏导入）；civil 图层与块展开虚拟层除外。"""
    return ((_layer_diameter_guess(name) is not None
             or any(re.search(pat, name, re.I) for _t, pat in LAYER_TYPE_KEYWORDS))
            and not name.startswith(('C-L', INSERT_EXPLODE_PREFIX)))


def _mtext_plain(text):
    return re.sub(r'\\[A-Za-z][^;\\]*;|\\P|\\[{}]|[{}]', '', text or '').strip()


def _polyline_len(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


# ── 坐标变换：本地绘图坐标 → WGS84，用户三点校准（库）优先 ────────────

CALIBRATION_CACHE_KEY = 'dxf:calib'


def _active_calibration_points():
    """→ (points, source, method)。source: 'db'=用户标定最新行 / 'default'=
    硬编码两点；method: 行上存的拟合方法（''=按点数自动 / 'tps' / 'mls'）。

    结果缓存 5 分钟，保存新标定时调用 ``_bust_calibration_cache()`` 失效。
    """
    from django.core.cache import cache
    from core.models import SiteCalibration
    from core.calibration import SITE_CALIBRATION_POINTS
    try:
        hit = cache.get(CALIBRATION_CACHE_KEY)
    except Exception:
        hit = None   # 缓存后端故障时直接走 DB，不让校准链路 500
    if hit is None:
        row = (SiteCalibration.objects.filter(is_active=True, drawing_token='').order_by('-id')
               .values_list('points', 'method').first())
        if row and row[0] and len(row[0]) >= 2:
            hit = (list(row[0]), 'db', row[1] or '')
        else:
            hit = (list(SITE_CALIBRATION_POINTS), 'default', '')
        try:
            cache.set(CALIBRATION_CACHE_KEY, hit, 300)
        except Exception:
            pass
    return hit


def _bust_calibration_cache():
    from django.core.cache import cache
    try:
        cache.delete(CALIBRATION_CACHE_KEY)
    except Exception:
        pass


def active_calibration_info(snapshot=None):
    """Display a specific calibration and its validation statistics.

    Nonlinear reverse fits are deliberately not exposed as inverse transforms;
    calibration picking uses preserved CAD coordinates instead.
    """
    from core.calibration import fit_calibration_transform
    from core.dxf_state import calibration_snapshot, calibration_quality, alignment_status
    snapshot = snapshot or calibration_snapshot()
    pts, source, stored_method = snapshot['points'], ('db' if snapshot['id'] else 'default'), snapshot['method']
    cal = [{'dxf_x': float(p['dxf_x']), 'dxf_y': -float(p['dxf_y']),
            'lat': float(p['lat']), 'lng': float(p['lng'])} for p in pts]
    fn, stats = fit_calibration_transform(cal, stored_method or None)
    # Display only; each batch stores its own effective transform.
    applied_at = None
    if source == 'db':
        from core.models import SiteCalibration
        row = SiteCalibration.objects.filter(pk=snapshot['id']).values_list('applied_at', flat=True).first()
        applied_at = row.isoformat() if row else None
    if not callable(fn):
        return {'id': snapshot['id'], 'quality': calibration_quality(snapshot), 'alignment': alignment_status(snapshot),
                'source': source, 'n': 0, 'method': 'similarity', 'scale': None,
                'rotation_deg': None, 'rms_m': None, 'residuals_m': [],
                'applied_at': applied_at, 'inverse': None, 'points': pts,
                'iso_k': None, 'spread_m': None}
    method = stats.get('method', 'similarity')
    k = stats.get('iso_k') or 1.0
    inv = None
    if method == 'similarity':
        from core.calibration import similarity_inverse
        inv = similarity_inverse(stats['a'], stats['b'], stats['c'], stats['d'])
        if inv:
            inv = dict(inv, iso_k=k)
    # 标定点最大间距（米）：n=2 即基线长。客户端据此提示"基线过短，
    # 远离基线的区域误差放大"（默认两点仅 ~29 m，是最危险的形态）。
    spread_m = None
    if len(pts) >= 2:
        worst = 0.0
        for a in pts:
            for b in pts:
                dlat = (b['lat'] - a['lat']) * 111320.0
                dlng = (b['lng'] - a['lng']) * 111320.0 * math.cos(
                    math.radians((a['lat'] + b['lat']) / 2))
                worst = max(worst, math.hypot(dlat, dlng))
        spread_m = round(worst, 1)
    return {
        'id': snapshot['id'],
        'quality': calibration_quality(snapshot),
        'alignment': alignment_status(snapshot),
        'check_points': snapshot.get('check_points', []),
        'source': source, 'n': stats['n'], 'method': method,
        'scale': round(stats['scale'], 8) if stats.get('scale') else None,
        'rotation_deg': round(stats['rotation_deg'], 4) if stats.get('rotation_deg') is not None else None,
        'rms_m': round(stats['rms_m'], 2) if stats.get('rms_m') is not None else None,
        'sim_rms_m': round(stats['sim_rms_m'], 2) if stats.get('sim_rms_m') is not None else None,
        'residuals_m': stats['residuals_m'],
        'applied_at': applied_at,
        'inverse': inv,
        'points': pts,
        'iso_k': k,
        'spread_m': spread_m,
    }


def _local_to_latlng_fn(snapshot=None):
    """返回 (to_latlng, meters_per_unit)。米/单位比例用于把米制容差换算
    成绘图单位——图纸以 mm/寸绘制时吸附距离依然按米判定。
    标定点来源：用户校准（SiteCalibration 最新行，含 method）优先，退回
    dxf_utils.SITE_CALIBRATION_POINTS 硬编码两点。method='mls' 用 MLS，
    其余按点数自动（≥4 TPS / 2-3 相似）。"""
    from core.calibration import fit_calibration_transform
    if snapshot is None:
        cal_pts, _source, _method = _active_calibration_points()
    else:
        cal_pts, _method = snapshot['points'], snapshot.get('method', '')
    if not cal_pts or len(cal_pts) < 2:
        return None, None
    cal = [
        {'dxf_x': p['dxf_x'], 'dxf_y': -p['dxf_y'], 'lat': p['lat'], 'lng': p['lng']}
        for p in cal_pts
    ]
    fn, _stats = fit_calibration_transform(cal, _method or None)
    if not callable(fn):
        return None, None

    def to_latlng(x, y):
        lat, lng = fn(x, -y)
        if not (math.isfinite(lat) and math.isfinite(lng)
                and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError('标定在图纸范围内产生无效坐标，请重新校准')
        return float(lat), float(lng)   # numpy 标量 → 原生 float（JSON 安全）

    # Use the complete least-squares fit, rather than an arbitrary first pair.
    meters_per_unit = (_stats.get('scale') or 0) * 111320.0
    return to_latlng, meters_per_unit


# ── 解析（临时文件用完即删 + 内容 hash 缓存） ──────────────────────────

def _parse_dxf_geometry(content_bytes):
    import ezdxf
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name
    try:
        doc = ezdxf.readfile(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    diagnostics = []
    geometry = _collect_geometry(doc.modelspace(), diagnostics=diagnostics)
    return (*geometry, {'file_hash': hashlib.sha256(content_bytes).hexdigest()[:32],
                        'units': int(doc.header.get('$INSUNITS', 0)),
                        'dxf_version': doc.dxfversion, 'diagnostics': diagnostics})


def _parse_cache():
    """``dxf:parse:v3:*`` 缓存句柄 —— FileBasedCache，跨 gunicorn worker 共享。

    不能用默认 LocMemCache（每 worker 一份内存）：analyze 落在哪个 worker，
    缓存就只在那个 worker 里；token 免重传的「保存并预览」/导入请求再落到
    别的 worker 时会误报「解析缓存已过期（15 分钟）」。见 settings.CACHES。
    """
    from django.core.cache import caches
    return caches['dxffile']


def _parsed_from_cache_or_file(content_bytes):
    """hash 命中缓存则复用解析结果，否则解析并写缓存。

    返回 (token, layers, valves, labels)。缓存走 FileBasedCache（跨 worker
    共享），单 worker 各自解析的问题不再存在。
    """
    cache = _parse_cache()
    token = hashlib.sha256(content_bytes).hexdigest()[:32]
    key = PARSE_CACHE_KEY_PREFIX + token
    hit = cache.get(key)
    if hit is not None:
        return token, hit[0], hit[1], hit[2], hit[3]
    parsed = _parse_dxf_geometry(content_bytes)
    try:
        cache.set(key, parsed, PARSE_CACHE_TTL)
    except Exception:
        pass   # 缓存写失败不影响功能
    return token, parsed[0], parsed[1], parsed[2], parsed[3]


# ── CAD 曲线：bulge 弧段细分 ───────────────────────────────────────────
# DXF 里弯管不是密集顶点，而是「顶点 + bulge 凸度」编码的圆弧段：CAD 按
# 圆弧渲染，只取顶点的话弧会变成弦（导入观感比 CAD 粗糙）。按 ≤ARC_STEP_DEG
# 一段在弧上取真实点；独立 ARC 实体同理细分。
ARC_STEP_DEG = 8.0


def _arc_points(cx, cy, radius, start_rad, sweep, n):
    return [(round(cx + radius * math.cos(start_rad + sweep * i / n), 3),
             round(cy + radius * math.sin(start_rad + sweep * i / n), 3))
            for i in range(1, n + 1)]


def _bulge_arc_points(a, b, bulge):
    """折线顶点对 (a,b) 上的 bulge 弧段 → 弧内细分点（不含端点 a/b）。

    bulge=0（直线段）或几何异常返回 []——退化成弦，不丢管线。
    bulge_to_arc 返回的 (sa, ea) 恒为逆时针弧；负 bulge（顺时针弧）时
    ezdxf 已把起止角交换（弧从 end_point 逆时针走回 start_point），因此
    含角 θ = (ea-sa) mod 2π，正 bulge 从 sa 正向采样、负 bulge 从 ea
    反向采样，才能按 a→b 顺序沿真实弧取点。
    """
    if abs(bulge) < 1e-9:
        return []
    try:
        from ezdxf.math import bulge_to_arc, Vec2
        center, sa, ea, radius = bulge_to_arc(Vec2(a[0], a[1]), Vec2(b[0], b[1]), bulge)
        cx, cy = float(center[0]), float(center[1])
        radius = float(radius)
        theta = (ea - sa) % (2 * math.pi)
        if radius < 1e-9 or theta < 1e-9:
            return []
        n = max(2, min(64, math.ceil(math.degrees(theta) / ARC_STEP_DEG)))
        if bulge > 0:
            return _arc_points(cx, cy, radius, sa, theta, n)
        return _arc_points(cx, cy, radius, ea, -theta, n)
    except Exception:
        return []


def _polyline_pts(raw):
    """[(x, y, bulge)] 顶点序列 → 含弧段细分的坐标点列表（bulge 属于
    该顶点起始的段）。"""
    pts = []
    for (x0, y0, b0), (x1, y1, _b1) in zip(raw, raw[1:]):
        pts.append((round(x0, 3), round(y0, 3)))
        pts.extend(_bulge_arc_points((x0, y0), (x1, y1), b0))
    if raw:
        pts.append((round(raw[-1][0], 3), round(raw[-1][1], 3)))
    return pts


# 曲线实体细分：弦到弧的最大偏差（绘图单位）。SPLINE/ELLIPSE/CIRCLE 无
# 顶点可取，按矢高细分——与 ARC_STEP_DEG 一样与半径无关地平滑。
FLATTEN_SAGITTA = 0.05
# 单条曲线细分点数上限：异常长曲线降采样，防预览/缓存负载爆炸
MAX_CURVE_PTS = 360

# 视作「线条几何」的实体类型（INSERT 块内展开同表）
LINE_ENTITY_TYPES = frozenset(
    ('LINE', 'LWPOLYLINE', 'POLYLINE', 'ARC', 'SPLINE', 'ELLIPSE', 'CIRCLE'))


def _flatten_curve(e):
    """SPLINE/ELLIPSE/CIRCLE → (细分点列, 是否闭合环)；失败返回 (None, False)。"""
    from ezdxf.path import make_path
    try:
        p = make_path(e)
        pts = [(round(v.x, 3), round(v.y, 3)) for v in p.flattening(FLATTEN_SAGITTA)]
    except Exception:
        return None, False
    if len(pts) > MAX_CURVE_PTS:
        last = pts[-1]
        step = math.ceil(len(pts) / MAX_CURVE_PTS)
        pts = pts[::step]
        if pts[-1] != last:
            pts.append(last)
    closed = bool(p.is_closed)
    if closed and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts, closed


def _entity_polyline(e):
    """单个线条实体 → (坐标点列, 是否闭合)。非线条实体/退化几何返回 None。

    闭合折线补上 末顶点→首顶点 的闭合段（该段 bulge 挂在末顶点上），
    环状管网按完整环输出而不是整条丢弃。
    """
    et = e.dxftype()
    def wcs(points, elevation=0):
        if tuple(e.dxf.get('extrusion', (0, 0, 1))) == (0, 0, 1):
            return points
        ocs = e.ocs()
        return [(round(v.x, 3), round(v.y, 3))
                for v in (ocs.to_wcs((x, y, elevation)) for x, y in points)]
    if et in ('LWPOLYLINE', 'POLYLINE'):
        if et == 'POLYLINE' and getattr(e, 'is_poly_face_mesh', False):
            return None   # 多面片网格顶点串不成管线
        if et == 'LWPOLYLINE':
            raw = [(p[0], p[1], p[2] or 0.0) for p in e.get_points('xyb')]
            closed = bool(e.closed)
        else:
            raw = [(v.dxf.location.x, v.dxf.location.y,
                    getattr(v.dxf, 'bulge', 0) or 0.0) for v in e.vertices]
            closed = bool(e.is_closed)
        if closed and len(raw) >= 2:
            raw.append(raw[0])
        pts = _polyline_pts(raw)
        if et == 'LWPOLYLINE':
            pts = wcs(pts, e.dxf.elevation)
        elif e.is_2d_polyline:
            pts = wcs(pts, e.dxf.elevation.z)
        return (pts, closed) if len(pts) >= 2 else None
    if et == 'ARC':
        c, r = e.dxf.center, float(e.dxf.radius)
        sa = math.radians(float(e.dxf.start_angle))
        sweep = (math.radians(float(e.dxf.end_angle)) - sa) % (2 * math.pi)
        if sweep < 1e-9:
            sweep = 2 * math.pi   # 起点=终点的整圆表示
        n = max(2, min(90, math.ceil(math.degrees(sweep) / ARC_STEP_DEG)))
        pts = [(round(c.x + r * math.cos(sa), 3), round(c.y + r * math.sin(sa), 3))]
        pts.extend(_arc_points(c.x, c.y, r, sa, sweep, n))
        return wcs(pts, c.z), False
    if et == 'LINE':
        a, b = e.dxf.start, e.dxf.end
        return [(round(a.x, 3), round(a.y, 3)), (round(b.x, 3), round(b.y, 3))], False
    if et == 'CIRCLE':
        # 整圆=起止角相等的 ARC：走精确三角细分（make_path 的 Bézier 近似
        # 在 r=25 时有 ~7mm 径向误差，没必要）
        c, r = e.dxf.center, float(e.dxf.radius)
        n = max(8, math.ceil(360.0 / ARC_STEP_DEG))
        pts = [(round(c.x + r, 3), round(c.y, 3))]
        pts.extend(_arc_points(c.x, c.y, r, 0.0, 2 * math.pi, n))
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        return wcs(pts, c.z), True
    if et in ('SPLINE', 'ELLIPSE'):
        return _flatten_curve(e)
    return None


# INSERT 块内线条几何展开到的虚拟图层前缀（默认不勾选，用户按需导入）
INSERT_EXPLODE_PREFIX = '块·'
# 嵌套块展开深度上限（防自引用块递归）
INSERT_EXPLODE_DEPTH = 3


def _entity_label(e, layer=None, source_id='', block=''):
    if e.dxftype() not in ('TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF'):
        return None
    plain = e.plain_text().strip()
    if not plain:
        return None
    if e.dxftype() == 'MTEXT':
        pos = e.dxf.insert
    else:
        pos = e.ocs().to_wcs(e.get_placement()[1])
    if not all(math.isfinite(float(c)) for c in pos):
        raise ValueError('标注包含非有限坐标')
    return {'layer': layer or e.dxf.layer, 'text': plain,
            'x': float(pos[0]), 'y': float(pos[1]),
            'source_id': source_id, 'block': block}


def _add_geometry(e, layer, layers, source_id, diagnostics):
    try:
        result = _entity_polyline(e)
        if result is None or not result[0] or len(result[0]) < 2 or _polyline_len(result[0]) <= 0:
            raise ValueError('退化或不支持的线条几何')
        pts, closed = result
        if not all(math.isfinite(c) for point in pts for c in point):
            raise ValueError('线条包含非有限坐标')
        bucket = layers.setdefault(layer, {'polys': [], 'closed': 0, 'entities': []})
        bucket['polys'].append(pts)
        bucket['entities'].append({'source_id': source_id, 'type': e.dxftype(),
                                   'layer': e.dxf.layer})
        bucket['closed'] += int(closed)
    except Exception as exc:
        diagnostics.append({'source_id': source_id, 'type': e.dxftype(),
                            'layer': layer, 'reason': str(exc)})


def _explode_insert_geometry(insert, name, layers, depth=INSERT_EXPLODE_DEPTH,
                             labels=None, diagnostics=None, source_id=''):
    labels = labels if labels is not None else []
    diagnostics = diagnostics if diagnostics is not None else []
    if depth <= 0:
        diagnostics.append({'source_id': source_id, 'type': 'INSERT',
                            'layer': insert.dxf.layer, 'reason': '嵌套块超过展开深度'})
        return
    def skipped(entity, reason):
        diagnostics.append({'source_id': source_id, 'type': entity.dxftype(),
                            'layer': entity.dxf.layer, 'reason': reason})
    try:
        ves = list(insert.virtual_entities(skipped_entity_callback=skipped))
    except Exception as exc:
        skipped(insert, str(exc))
        return
    for index, ve in enumerate(ves):
        child_id = f'{source_id}/{index}'
        if ve.dxftype() == 'INSERT':
            instances = list(ve.multi_insert()) if ve.mcount > 1 else [ve]
            for i, instance in enumerate(instances):
                _explode_insert_geometry(instance, name, layers, depth - 1,
                                         labels, diagnostics, f'{child_id}/{i}')
        elif ve.dxftype() in LINE_ENTITY_TYPES:
            _add_geometry(ve, INSERT_EXPLODE_PREFIX + name, layers, child_id, diagnostics)
        elif ve.dxftype() in ('TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF'):
            try:
                label = _entity_label(ve, INSERT_EXPLODE_PREFIX + name, child_id, name)
                if label:
                    labels.append(label)
            except Exception as exc:
                skipped(ve, str(exc))
        else:
            skipped(ve, '未作为管线或标注导入')


def _collect_geometry(msp, diagnostics=None):
    """Collect source geometry in WCS, retaining identity and unsupported reasons."""
    layers, valves, labels = {}, [], []
    diagnostics = diagnostics if diagnostics is not None else []
    for e in msp:
        et, layer = e.dxftype(), e.dxf.layer
        source_id = e.dxf.get('handle', '')
        if et in LINE_ENTITY_TYPES:
            _add_geometry(e, layer, layers, source_id, diagnostics)
        elif et == 'INSERT':
            instances = list(e.multi_insert()) if e.mcount > 1 else [e]
            for i, instance in enumerate(instances):
                sid = f'{source_id}/{i}'
                pos = instance.ocs().to_wcs(instance.dxf.insert)
                if not all(math.isfinite(float(c)) for c in pos):
                    diagnostics.append({'source_id': sid, 'type': et, 'layer': layer,
                                        'reason': '块包含非有限坐标'})
                    continue
                valves.append({'block': instance.dxf.name, 'layer': layer,
                               'source_id': sid, 'x': float(pos.x), 'y': float(pos.y),
                               'attrs': {a.dxf.tag: a.dxf.text for a in instance.attribs}})
                _explode_insert_geometry(instance, instance.dxf.name, layers,
                                         labels=labels, diagnostics=diagnostics, source_id=sid)
        elif et in ('MTEXT', 'TEXT'):
            try:
                label = _entity_label(e, source_id=source_id)
                if label:
                    labels.append(label)
            except Exception as exc:
                diagnostics.append({'source_id': source_id, 'type': et,
                                    'layer': layer, 'reason': str(exc)})
        else:
            diagnostics.append({'source_id': source_id, 'type': et,
                                'layer': layer, 'reason': '未作为管线或标注导入'})
    return layers, valves, labels


# ── 连通分解：把折线集合切成简单路径（交叉点断开、链式合并） ──────────

class _NodeIndex:
    """真距离吸附的节点索引：网格分桶 + 3×3 邻桶探测。

    比纯 ``round(p/tol)`` 网格量化稳健——端点落在格边界两侧 tol 内仍能
    相接，同格内也不会误接超过 tol 的点。
    """

    def __init__(self, tol):
        self.tol = tol
        self.tol2 = tol * tol
        self.grid = {}      # (bx, by) -> [nid, ...]
        self.pts = {}       # nid -> (x, y)
        self._next = 0

    def get(self, x, y):
        bx, by = int(x // self.tol), int(y // self.tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for nid in self.grid.get((bx + dx, by + dy), ()):
                    nx, ny = self.pts[nid]
                    if (nx - x) ** 2 + (ny - y) ** 2 <= self.tol2:
                        return nid
        nid = self._next
        self._next += 1
        self.pts[nid] = (x, y)
        self.grid.setdefault((bx, by), []).append(nid)
        return nid


def _decompose_paths(polys, tol_m=JOIN_TOL_M, meters_per_unit=1.0):
    """折线 → 简单路径列表。

    每条输入折线视作一条边（两端节点）；节点按真距离吸附（容差由米换算
    成绘图单位）。度数 ≠2 的节点（端点/交叉点）是路径的起止；纯 2 度闭环
    整体输出。共享两端的平行环由 visited 边集保护。
    """
    unit_tol = tol_m / meters_per_unit if meters_per_unit else tol_m
    idx = _NodeIndex(unit_tol)
    edges = []                 # (na, nb, pts, is_selfloop)
    incident = defaultdict(list)
    for pts in polys:
        if len(pts) < 2 or _polyline_len(pts) <= 0:
            continue
        na = idx.get(*pts[0])
        nb = idx.get(*pts[-1])
        is_selfloop = na == nb
        edges.append((na, nb, pts, is_selfloop))
        incident[na].append(len(edges) - 1)
        incident[nb].append(len(edges) - 1)

    used = [False] * len(edges)

    def oriented(eidx, from_node):
        na, nb, pts, _ = edges[eidx]
        return pts if na == from_node else list(reversed(pts))

    def walk(edge_idx, from_node):
        path = []
        cur = from_node
        eidx = edge_idx
        while True:
            used[eidx] = True
            seg = oriented(eidx, cur)
            if path:
                seg = seg[1:]   # 去掉接头重复点
            path.extend(seg)
            na, nb, _, loop = edges[eidx]
            nxt = nb if na == cur else na
            if loop or len(incident[nxt]) != 2:
                return path
            nxt_idx = next((i for i in incident[nxt] if i != eidx and not used[i]), None)
            if nxt_idx is None:
                return path
            cur, eidx = nxt, nxt_idx

    paths = []
    for node, idxs in incident.items():
        if len(idxs) == 2:
            continue
        for eidx in idxs:
            if used[eidx]:
                continue
            na, nb, _, loop = edges[eidx]
            if loop:
                continue
            paths.append(walk(eidx, na if na == node else nb))
    for i, (na, nb, pts, loop) in enumerate(edges):
        if used[i]:
            continue
        if loop:
            used[i] = True
            paths.append(pts)
        else:
            paths.append(walk(i, na))
    return [p for p in paths if len(p) >= 2]


# ── 空间索引：线段网格（阀门吸附） + 标注 x 排序（就近命名） ──────────

class _SegmentGrid:
    """均匀网格线段索引：查询点周边 3×3 桶内的候选线段。

    桶边长 ≥ 吸附容差（米换算后），3×3 邻桶覆盖所有可能命中的线段。
    """

    def __init__(self, cell):
        self.cell = max(cell, 0.5)
        self.grid = defaultdict(list)

    def _key(self, x, y):
        return (int(x // self.cell), int(y // self.cell))

    def add(self, seg_key, a, b):
        # 栅格化注册：沿段以 cell/2 步长覆盖所有经过的桶——只写端点+中点
        # 会漏掉长段中间的桶，导致那一段上的阀门找不到候选而 skipped。
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        steps = max(1, int(length / (self.cell / 2)) + 1)
        seen = set()
        for i in range(steps + 1):
            t = i / steps
            k = self._key(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            if k in seen:
                continue
            seen.add(k)
            lst = self.grid[k]
            if seg_key not in [x[0] for x in lst]:
                lst.append((seg_key, a, b))

    def candidates(self, x, y):
        bx, by = int(x // self.cell), int(y // self.cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield from self.grid.get((bx + dx, by + dy), ())


def _dist_to_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class _LabelIndex:
    """按 x 排序的标注索引：窗口扫描 [x-r, x+r] 再比 y，避免 O(V×L) 全扫。"""

    def __init__(self, labels):
        self.items = sorted(labels, key=lambda lb: lb['x'])
        self.xs = [lb['x'] for lb in self.items]   # bisect 用（py3.9 无 key 参数）

    def nearest_within(self, x, y, radius):
        import bisect
        lo = bisect.bisect_left(self.xs, x - radius)
        best = None
        for i in range(lo, len(self.items)):
            lb = self.items[i]
            if lb['x'] > x + radius:
                break
            d = math.hypot(lb['x'] - x, lb['y'] - y)
            if d <= radius and (best is None or d < best[0]):
                best = (d, lb['text'])
        return best


# ── zone 预计算：环 + bbox + 配对属性，一次 DB 读取全程复用 ────────────

def _load_zone_data():
    from core.models import Zone
    from core.pipe_utils import flatten_rings, _ring_bbox
    zone_rings = []   # (zone_id, ring, bbox)
    zone_info = {}    # zone_id -> {'name', 'code', 'station_id', 'valve_dia'}
    for z in Zone.objects.exclude(boundary_points=[]).only(
            'id', 'name', 'code', 'boundary_points', 'dxf_boundary_points',
            'boundary_source', 'maxicom_runtime', 'solenoid_valve_size'):
        info = {'name': z.name, 'code': z.code,
                'station_id': (z.maxicom_runtime[0]
                               if isinstance(z.maxicom_runtime, list) and z.maxicom_runtime
                               else None),
                'valve_dia': (round(z.solenoid_valve_size * 25.4, 1)
                              if z.solenoid_valve_size else None)}
        for ring in flatten_rings(z.active_boundary_points):
            if len(ring) >= 3:
                zone_rings.append((z.id, ring, _ring_bbox(ring)))
        zone_info[z.id] = info
    return zone_rings, zone_info


def _crossed_zone_ids(line, zone_rings):
    """内存版路径穿越检测（与 pipe_utils.detect_crossed_zones 同算法，
    但 zone 环/bbox 已预计算，循环内零 DB 访问）。``line`` 是 (lat,lng) 列表。
    """
    from core.pipe_utils import _point_in_ring, _segments_intersect
    if len(line) < 2:
        return []
    lats = [p[0] for p in line]
    lngs = [p[1] for p in line]
    buf = 0.5 / 111000.0   # 半米缓冲，弥补折线顶点稀疏
    lbbox = (min(lats) - buf, max(lats) + buf, min(lngs) - buf, max(lngs) + buf)
    segs = list(zip(line[:-1], line[1:]))

    crossed = []
    seen = set()
    for zid, ring, bbox in zone_rings:
        if zid in seen:
            continue
        if lbbox[1] < bbox[0] or lbbox[0] > bbox[1] or lbbox[3] < bbox[2] or lbbox[2] > bbox[3]:
            continue
        hit = any(_point_in_ring(lat, lng, ring) for lat, lng in line)
        if not hit:
            n = len(ring)
            for (a, b) in segs:
                for i in range(n):
                    if _segments_intersect(a, b, ring[i], ring[(i + 1) % n]):
                        hit = True
                        break
                if hit:
                    break
        if hit:
            crossed.append(zid)
            seen.add(zid)
    return crossed


# ── analyze：图纸概览 + 预览几何 ───────────────────────────────────────

def analyze_dxf_pipelines(uploaded_file=None, token=None, user_id=None, calibration_id=None):
    """解析 DXF，始终返回原始 CAD 坐标；位置验证通过后才附加经纬度。

    额外返回 ``token``（内容 hash）——导入阶段凭它复用本次解析结果。
    ``uploaded_file`` 为空且给了 ``token`` 时直接读解析缓存重建预览
    （三点校准保存后免重传刷新预览用）。
    """
    if uploaded_file is not None:
        content = uploaded_file.read()
        if isinstance(content, str):
            content = content.encode('utf-8', errors='ignore')
        token, layers, valves, labels, metadata = _parsed_from_cache_or_file(content)
    elif token:
        hit = _parse_cache().get(PARSE_CACHE_KEY_PREFIX + token)
        if hit is None:
            return {'success': False, 'error': '解析缓存已过期（15 分钟），请重新上传 DXF 文件'}
        layers, valves, labels, metadata = hit
    else:
        return {'success': False, 'error': '请上传 .dxf 文件或提供解析 token'}

    from core.dxf_state import calibration_snapshot, sign_preview, alignment_status
    snapshot = calibration_snapshot(token, calibration_id)
    alignment = alignment_status(snapshot)
    to_latlng, meters_per_unit = _local_to_latlng_fn(snapshot) if alignment['ready'] else (None, None)
    def preview_point(x, y):
        point = {'dxf_x': x, 'dxf_y': y}
        if to_latlng:
            lat, lng = to_latlng(x, y)
            point.update(lat=round(lat, 6), lng=round(lng, 6))
        return point

    layer_infos = []
    for name, bucket in sorted(layers.items(),
                               key=lambda kv: -sum(_polyline_len(p) for p in kv[1]['polys'])):
        polys = bucket['polys']
        if not polys:
            continue
        total_len = sum(_polyline_len(p) for p in polys)
        layer_infos.append({
            'layer': name,
            'color': 7,
            'segments': len(polys),
            'total_len': round(total_len * (meters_per_unit or 1.0), 1),
            'closed_shapes': bucket['closed'],
            'diameter_guess': _layer_diameter_guess(name),
            'type_guess': _guess_line_type(name),
            'include_guess': _layer_include_guess(name),
        })

    blocks = defaultdict(lambda: {'count': 0, 'attrs': set(), 'samples': []})
    for v in valves:
        blk = blocks[v['block']]
        blk['count'] += 1
        for val in v['attrs'].values():
            if val and len(blk['attrs']) < 6:
                blk['attrs'].add(val[:20])
        if len(blk['samples']) < 3:
            blk['samples'].append(preview_point(v['x'], v['y']))
    block_infos = []
    for name, info in sorted(blocks.items(), key=lambda kv: -kv[1]['count']):
        block_infos.append({
            'block': name,
            'count': info['count'],
            'attrs': sorted(info['attrs']),
            'valve_type_guess': _guess_block_type(name),
            'samples': info['samples'],
            'include_guess': name.startswith('WID_Val') or bool(re.search(r'拉线|QCV|\bWD\b', name, re.I)),
        })

    label_layers = defaultdict(lambda: {'count': 0, 'samples': [], 'points': []})
    for lb in labels:
        b = label_layers[lb['layer']]
        b['count'] += 1
        if len(b['samples']) < 6:
            b['samples'].append(lb['text'])
        b['points'].append(dict(preview_point(lb['x'], lb['y']), text=lb['text'],
                                source_id=lb.get('source_id', '')))

    previewable = layer_infos
    preview_layers = []
    for info in previewable:
        pts_list = layers[info['layer']]['polys']
        paths = []
        for pts in pts_list:
            paths.append([preview_point(x, y) for x, y in pts])
        preview_layers.append({'layer': info['layer'], 'paths': paths})
    preview_valves = []
    for v in valves:
        preview_valves.append(dict(preview_point(v['x'], v['y']), block=v['block'],
                                   source_id=v.get('source_id', '')))

    extents = []
    for bucket in layers.values():
        for pts in bucket['polys'][:50]:
            extents.extend(pts)
    coord_info = ''
    if extents:
        xs = [p[0] for p in extents]; ys = [p[1] for p in extents]
        coord_info = f'本地坐标 X[{min(xs):.0f}..{max(xs):.0f}] Y[{min(ys):.0f}..{max(ys):.0f}]' + ('，已验证对齐' if alignment['ready'] else '，尚未定位')

    return {
        'success': True,
        'token': token,
        'preview_token': sign_preview(token, snapshot, user_id),
        'calibration': active_calibration_info(snapshot),
        'metadata': metadata,
        'alignment': alignment,
        'length_unit': 'm' if to_latlng else 'CAD',
        'coverage': {'paths': sum(len(b['polys']) for b in layers.values()),
                     'blocks': len(valves), 'labels': len(labels),
                     'unsupported': len(metadata['diagnostics'])},
        'coord_info': coord_info,
        'layers': layer_infos,
        'blocks': block_infos,
        'labels': [{'layer': k, 'count': v['count'], 'samples': v['samples'],
                    'points': v['points']} for k, v in label_layers.items()],
        'preview': {'layers': preview_layers, 'valves': preview_valves},
    }


# ── import：按用户映射落库 ────────────────────────────────────────────

def _resolve_parsed_geometry(uploaded_file, token, content):
    """导入几何来源：``token`` 解析缓存优先，过期/缺失退回文件/字节内容。"""
    if token:
        hit = _parse_cache().get(PARSE_CACHE_KEY_PREFIX + token)
        if hit is not None:
            return hit
        # 缓存过期，退回文件解析
    if content is None:
        if uploaded_file is None:
            raise ValueError('缺少文件且解析缓存已过期，请重新上传解析')
        content = uploaded_file.read()
        if isinstance(content, str):
            content = content.encode('utf-8', errors='ignore')
    _, layers, valves, labels, metadata = _parsed_from_cache_or_file(content)
    return layers, valves, labels, metadata


def _unique_name_code(name, code, used_names, used_codes):
    """名称/编号唯一化（内存判重 + 截断到字段上限，超长在 PostgreSQL 会炸）。
    就地登记到 used 集合，DB 唯一约束兜底并发。"""
    base_name, base_code, n = name[:255], code[:50], 2
    while name in used_names or code in used_codes:
        name = f'{base_name} ({n})'[:255]
        code = f'{base_code}-{n}'[:50]
        n += 1
    used_names.add(name)
    used_codes.add(code)
    return name, code


def _attach_valves(valves, block_specs, all_paths, to_latlng,
                   off_lat, off_lng, meters_per_unit, usable_labels,
                   zone_rings, zone_info):
    """阀门吸附：INSERT 块 → 1.5m 内最近管段（网格空间索引），就近标注命名，
    电磁阀配 zone/station/口径。→ (valve_rows, labeled_valves, skipped_valves, unmatched)。"""
    from core.models import PipeValve
    from core.pipe_utils import _point_in_ring

    def zone_of(lat, lng):
        for zid, ring, bb in zone_rings:
            if bb[0] <= lat <= bb[1] and bb[2] <= lng <= bb[3]:
                if _point_in_ring(lat, lng, ring):
                    return zid
        return None

    snap_units = SNAP_TOL_M / (meters_per_unit or 1.0)
    grid = _SegmentGrid(snap_units)
    for pi, (pts, _dia, _p) in enumerate(all_paths):
        for i in range(len(pts) - 1):
            grid.add((pi, i), pts[i], pts[i + 1])
    label_units = LABEL_RADIUS_M / (meters_per_unit or 1.0)
    label_idx = _LabelIndex(usable_labels) if usable_labels else None

    valve_rows, labeled_valves, skipped_valves, unmatched = [], 0, 0, []
    order_by_pipe = defaultdict(int)
    for v in valves:
        spec = (block_specs or {}).get(v['block'])
        if not spec or not spec.get('include'):
            continue
        best = None
        for (pi, si), a, b in grid.candidates(v['x'], v['y']):
            d = _dist_to_seg(v['x'], v['y'], a[0], a[1], b[0], b[1])
            if d <= snap_units and (best is None or d < best[0]):
                best = (d, pi)
        if best is None:
            skipped_valves += 1
            unmatched.append(dict(v, reason='距所选管线超过 1.5 m，待人工挂接'))
            continue
        _, pi = best
        pts, diameter, pipe = all_paths[pi]
        lat, lng = to_latlng(v['x'], v['y'])
        lat += off_lat; lng += off_lng
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError('阀门坐标无效或超界，请重新校准')
        name = next((value for tag, value in v['attrs'].items()
                     if tag.upper() in ('ID', 'NAME', 'NUMBER', 'VALVE_ID', '设备编号') and value), '')
        if name:
            labeled_valves += 1
        if label_idx and not name:
            hit = label_idx.nearest_within(v['x'], v['y'], label_units)
            if hit:
                name = hit[1][:50]   # PipeValve.name 上限 50
                labeled_valves += 1
        vtype = spec.get('valve_type') if spec.get('valve_type') in \
            dict(PipeValve.VALVE_TYPE_CHOICES) else PipeValve.VALVE_SOLENOID
        zid = zone_of(lat, lng)
        station_id = None
        vdia = diameter   # 默认继承所在管线的管径
        # 电磁阀(Zone自控) 落在 zone 内：自动配对该 zone 的 Maxicom
        # station（首页即可显示灌溉运行数据）并用 zone 的电磁阀尺寸
        # 换算口径（比图层管径更准确）。
        if vtype == PipeValve.VALVE_SOLENOID and zid:
            zi = zone_info.get(zid) or {}
            station_id = zi.get('station_id')
            if zi.get('valve_dia'):
                vdia = zi['valve_dia']
        order_by_pipe[pipe.id] += 1
        valve_rows.append(PipeValve(
            pipeline=pipe,
            zone_id=zid,
            station_id=station_id,
            name=name[:50] or f"{v['block'].rsplit('-', 1)[-1].upper()}·{v['x']:.0f},{v['y']:.0f}"[:50],
            point=[{'lat': round(lat, 6), 'lng': round(lng, 6)}],
            source_point=[v['x'], v['y']],
            source_map_point=[{'lat': round(lat, 6), 'lng': round(lng, 6)}],
            source_attributes={'tags': v['attrs'], 'block': v['block'],
                               'source_id': v.get('source_id', '')},
            notes='\n'.join(f'{tag}: {value}' for tag, value in v['attrs'].items()),
            valve_type=vtype,
            diameter=vdia,
            order=order_by_pipe[pipe.id],
        ))
    return valve_rows, labeled_valves, skipped_valves, unmatched


def import_dxf_pipelines(layer_specs, block_specs, uploaded_file=None,
                         label_layers=None, valve_name_from_label=True,
                         offset=(0.0, 0.0), token=None, content=None,
                         batch_name=None, imported_by=None, preview_token=None):
    """按映射创建 Pipeline + PipeValve。

    ``layer_specs``: {layer: {'include', 'diameter', 'type'}}
    ``block_specs``: {block: {'include', 'valve_type'}}
    几何来源优先级：``token`` 解析缓存 → ``uploaded_file``/``content``。
    ``batch_name``/``imported_by``：创建导入批次并把本批管道全部挂上
    （水管管理页按批次整批删除用）。
    返回 {pipelines, valves, labeled_valves, skipped_valves, layer_stats, batch_id}。
    整个落库过程包在一个事务里——失败不留下半截数据。
    """
    from django.db import transaction as _db_txn
    from core.models import Pipeline, PipeValve, PipelineImportBatch
    from core.pipe_utils import _auto_pipeline_name_code

    from core.dxf_state import calibration_snapshot, read_preview, require_quality
    if preview_token:
        state = read_preview(preview_token, token, getattr(imported_by, 'pk', None))
        token = state['token']
        snapshot = state['calibration']
    else:
        snapshot = calibration_snapshot(token)
    require_quality(snapshot)
    to_latlng, meters_per_unit = _local_to_latlng_fn(snapshot)
    if to_latlng is None:
        raise ValueError('缺少站点标定点，无法转换坐标')
    if uploaded_file is not None:
        content = uploaded_file.read()
        if token and hashlib.sha256(content).hexdigest()[:32] != token:
            raise ValueError('文件与预览不一致，请重新解析图纸')
    layers, valves, labels, metadata = _resolve_parsed_geometry(None, token, content)
    token = token or metadata['file_hash']

    usable_labels = [lb for lb in labels
                     if label_layers is None or lb['layer'] in label_layers]

    zone_rings, zone_info = _load_zone_data()

    off_lat, off_lng = float(offset[0] or 0), float(offset[1] or 0)
    if not all(math.isfinite(n) for n in (off_lat, off_lng)):
        raise ValueError('微调偏移必须是有限数值')

    # 名称唯一性判重：内存 set（一次 DB 读取），DB 唯一约束兜底并发
    used_names = set(Pipeline.objects.values_list('name', flat=True))
    used_codes = set(Pipeline.objects.values_list('code', flat=True))

    created_pipes = 0
    layer_stats = []
    all_paths = []   # (local_pts, diameter, pipeline)

    with _db_txn.atomic():
        # 批次在事务内创建：导入失败整体回滚，不留 0 管道的孤儿批次行
        batch = PipelineImportBatch.objects.create(
            name=(batch_name or 'DXF导入')[:200],
            imported_by=imported_by, source_token=token or '',
            calibration_snapshot=snapshot, applied_calibration=snapshot,
            source_geometry={'layers': layers, 'valves': valves, 'labels': labels,
                             'metadata': metadata},
            import_options={'layers': layer_specs, 'blocks': block_specs,
                            'label_layers': label_layers, 'offset': [off_lat, off_lng]},
        )
        for layer, spec in layer_specs.items():
            if not isinstance(spec, dict):
                raise ValueError(f'图层 {layer} 的映射参数无效')
            if not spec.get('include'):
                continue
            bucket = layers.get(layer)
            if not bucket or not bucket['polys']:
                raise ValueError(f'图层 {layer} 不在已解析图纸内，请刷新映射')
            try:
                diameter = float(spec.get('diameter')) if spec.get('diameter') else None
            except (TypeError, ValueError):
                raise ValueError(f'图层 {layer} 的管径不是有效数值')
            if diameter is not None and (not math.isfinite(diameter) or diameter <= 0):
                raise ValueError(f'图层 {layer} 的管径需为正数')
            ptype = spec.get('type') or 'irrigation'
            if ptype not in dict(Pipeline.TYPE_CHOICES):
                raise ValueError(f'图层 {layer} 的管线类型无效')
            paths = _decompose_paths(bucket['polys'], JOIN_TOL_M, meters_per_unit or 1.0)
            n_paths = 0
            for pts in paths:
                ll = [{'lat': round(la + off_lat, 6), 'lng': round(ln + off_lng, 6)}
                      for la, ln in (to_latlng(x, y) for x, y in pts)]
                if len(ll) < 2:
                    continue
                if any(not (math.isfinite(pt['lat']) and math.isfinite(pt['lng'])
                            and -90 <= pt['lat'] <= 90 and -180 <= pt['lng'] <= 180) for pt in ll):
                    raise ValueError('导入坐标无效或超界，请重新校准')
                # 内存穿越检测 + zone 属性查表（批量预计算，零 DB 访问）
                zids = _crossed_zone_ids([(p['lat'], p['lng']) for p in ll], zone_rings)
                name, code = _auto_pipeline_name_code(zids, ptype)
                if not name:
                    dl = f'DN{diameter:.0f}' if diameter else layer
                    name = f'{dl} 管段（DXF）'
                    code = f"{'IRR' if ptype == 'irrigation' else 'FLU'}-DXF"
                name, code = _unique_name_code(name, code, used_names, used_codes)
                p = Pipeline.objects.create(
                    name=name, code=code,
                    pipeline_type=ptype,
                    main_diameter=diameter,
                    flow_direction=Pipeline.FLOW_FORWARD,
                    source_label=f'DXF导入 · 图层 {layer}',
                    line_points=ll, source_points=pts, source_map_points=ll,
                    import_batch=batch,
                )
                if zids:
                    p.zones.set(zids)
                # 块展开层（阀/接头符号）不作贴管目标——否则阀门会吸到自己的
                # 符号环上，而不是真正经过它的管道
                if not layer.startswith(INSERT_EXPLODE_PREFIX):
                    all_paths.append((pts, diameter, p))
                created_pipes += 1
                n_paths += 1
            layer_stats.append({'layer': layer, 'paths': n_paths,
                                'segments': len(bucket['polys'])})

        valve_rows, labeled_valves, skipped_valves, unmatched = _attach_valves(
            valves, block_specs, all_paths, to_latlng, off_lat, off_lng,
            meters_per_unit, usable_labels, zone_rings, zone_info)
        batch.source_geometry['unmatched_valves'] = unmatched
        batch.save(update_fields=['source_geometry'])
        if valve_rows:
            PipeValve.objects.bulk_create(valve_rows)

    return {
        'pipelines': created_pipes,
        'valves': len(valve_rows),
        'labeled_valves': labeled_valves,
        'skipped_valves': skipped_valves,
        'layer_stats': layer_stats,
        'batch_id': batch.id,
        'unmatched_valves': unmatched,
        'unsupported': metadata['diagnostics'],
    }


def build_cad_reference_payload():
    """Independent, retained CAD reference/annotation/unmatched-asset overlays."""
    from core.models import PipelineImportBatch
    result = []
    for batch in PipelineImportBatch.objects.exclude(source_geometry={}):
        snapshot = batch.applied_calibration or batch.calibration_snapshot
        if not snapshot:
            continue
        fn, _ = _local_to_latlng_fn(snapshot)
        if fn is None:
            continue
        off_lat, off_lng = batch.import_options.get('offset', [0, 0])
        def point(x, y):
            lat, lng = fn(x, y)
            return {'lat': round(lat + off_lat, 6), 'lng': round(lng + off_lng, 6)}
        source = batch.source_geometry
        result.append({
            'batch_id': batch.id, 'name': batch.name,
            'layers': [{'layer': name, 'paths': [[point(x, y) for x, y in path]
                         for path in bucket['polys']]}
                       for name, bucket in source.get('layers', {}).items()],
            'labels': [dict(lb, **point(lb['x'], lb['y'])) for lb in source.get('labels', [])],
            'unmatched_valves': [dict(v, **point(v['x'], v['y']))
                                 for v in source.get('unmatched_valves', [])],
            'unsupported': source.get('metadata', {}).get('diagnostics', []),
        })
    return result
