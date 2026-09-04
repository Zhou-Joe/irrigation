"""DXF 管线导入：把灌溉 CAD 图纸解析成 Pipeline + PipeValve 行。

面向的图纸约定（与 Test dxf.dxf 一致）：
  * 管道按图层分类，图层名常直接是管径（``100``/``75``/``150``…）或
    ``WD``（疏水/放水）；
  * 阀门是 INSERT 块，块名 ``WID_Val-*`` 的后缀编码阀门类型，插入点
    几乎总落在管道线上；
  * 文字标注（MTEXT/TEXT，多在 ``设备编号``/``POC`` 层）是最近的阀门/
    设备编号，如 ``9-GV6``。

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
]

# 端点吸附容差（米）——判定两条折线相接
JOIN_TOL_M = 0.3
# 阀门贴线容差（米）——超出则不挂到任何管线
SNAP_TOL_M = 1.5
# 标注→阀门匹配半径（米）
LABEL_RADIUS_M = 2.5
# 解析缓存 TTL（秒）——analyze → import 之间复用
PARSE_CACHE_TTL = 15 * 60


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
    from core.dxf_utils import SITE_CALIBRATION_POINTS
    try:
        hit = cache.get(CALIBRATION_CACHE_KEY)
    except Exception:
        hit = None   # 缓存后端故障时直接走 DB，不让校准链路 500
    if hit is None:
        row = (SiteCalibration.objects.order_by('-id')
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


def active_calibration_info():
    """当前生效标定的展示/客户端信息：来源、点数、方法、拟合统计、逆变换。

    页面初始渲染用它给 JS 提供逆变换（地图点击 → 本地坐标，校准取点用），
    以及拟合参数（比例/旋转）供新拟合对比显示。≥4 点时 method='tps'：
    比例/旋转取同样点数下相似变换的拟合值（仅作对照显示——TPS 没有单一
    比例/旋转），rms_m 为 LOO 泛化误差；inverse 为反向 TPS 的可序列化
    系数（{'type':'tps', ...}），JS 端用核函数求值。
    """
    from core.dxf_utils import fit_calibration_transform
    pts, source, stored_method = _active_calibration_points()
    cal = [{'dxf_x': float(p['dxf_x']), 'dxf_y': -float(p['dxf_y']),
            'lat': float(p['lat']), 'lng': float(p['lng'])} for p in pts]
    fn, stats = fit_calibration_transform(cal, stored_method or None)
    if not callable(fn):
        return {'source': source, 'n': 0, 'method': 'similarity', 'scale': None,
                'rotation_deg': None, 'rms_m': None, 'residuals_m': [],
                'inverse': None, 'points': pts}
    method = stats.get('method', 'similarity')
    inv = None
    if method == 'mls':
        # MLS 无拟合系数——逆变换直接携带点对，JS 端加权相似 LS 求值
        inv = {'type': 'mls',
               'points': [[p['lat'], p['lng'], p['dxf_x'], p['dxf_y']] for p in cal]}
    elif method == 'tps':
        # 反向 TPS 系数 ((lat,lng)→(x,-y))，JS 用核函数求值（地图取点用）
        from core.dxf_utils import _tps_fit_core
        rc = _tps_fit_core([(p['lat'], p['lng']) for p in cal],
                           [(p['dxf_x'], p['dxf_y']) for p in cal])
        inv = {'type': 'tps', 'coeffs': rc} if rc else None
    else:
        from core.dxf_utils import similarity_inverse
        inv = similarity_inverse(stats['a'], stats['b'], stats['c'], stats['d'])
    return {
        'source': source, 'n': stats['n'], 'method': method,
        'scale': round(stats['scale'], 8) if stats.get('scale') else None,
        'rotation_deg': round(stats['rotation_deg'], 4) if stats.get('rotation_deg') is not None else None,
        'rms_m': round(stats['rms_m'], 2) if stats.get('rms_m') is not None else None,
        'sim_rms_m': round(stats['sim_rms_m'], 2) if stats.get('sim_rms_m') is not None else None,
        'residuals_m': stats['residuals_m'],
        'inverse': inv,
        'points': pts,
    }


def _local_to_latlng_fn():
    """返回 (to_latlng, meters_per_unit)。米/单位比例用于把米制容差换算
    成绘图单位——图纸以 mm/寸绘制时吸附距离依然按米判定。
    标定点来源：用户校准（SiteCalibration 最新行，含 method）优先，退回
    dxf_utils.SITE_CALIBRATION_POINTS 硬编码两点。method='mls' 用 MLS，
    其余按点数自动（≥4 TPS / 2-3 相似）。"""
    from core.dxf_utils import fit_calibration_transform
    cal_pts, _source, _method = _active_calibration_points()
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
        return float(lat), float(lng)   # numpy 标量 → 原生 float（JSON 安全）

    p1, p2 = cal_pts[0], cal_pts[1]
    du = math.hypot(p2['dxf_x'] - p1['dxf_x'], p2['dxf_y'] - p1['dxf_y'])
    dlat = (p2['lat'] - p1['lat']) * 111320.0
    dlng = (p2['lng'] - p1['lng']) * 111320.0 * math.cos(
        math.radians((p1['lat'] + p2['lat']) / 2))
    meters_per_unit = math.hypot(dlat, dlng) / du if du else 1.0
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
    return _collect_geometry(doc.modelspace())


def _parse_cache():
    """``dxf:parse:*`` 缓存句柄 —— FileBasedCache，跨 gunicorn worker 共享。

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
    key = 'dxf:parse:' + token
    hit = cache.get(key)
    if hit is not None:
        return token, hit[0], hit[1], hit[2]
    parsed = _parse_dxf_geometry(content_bytes)
    try:
        cache.set(key, parsed, PARSE_CACHE_TTL)
    except Exception:
        pass   # 缓存写失败不影响功能
    return token, parsed[0], parsed[1], parsed[2]


def _collect_geometry(msp):
    """一次遍历 modelspace，按图层归集开放折线 / 阀门 INSERT / 文字标注。"""
    layers = {}   # layer -> {'polys': [[(x,y),...]], 'closed': n}
    valves = []   # {'block', 'x', 'y', 'attrs'}
    labels = []   # {'layer', 'text', 'x', 'y'}

    for e in msp:
        et = e.dxftype()
        layer = e.dxf.layer
        if et in ('LWPOLYLINE', 'POLYLINE'):
            if et == 'LWPOLYLINE':
                pts = [(round(p[0], 3), round(p[1], 3)) for p in e.get_points('xy')]
                closed = bool(e.closed)
            else:
                pts = [(round(v.dxf.location.x, 3), round(v.dxf.location.y, 3))
                       for v in e.vertices]
                closed = bool(e.is_closed)
            if len(pts) < 2:
                continue
            bucket = layers.setdefault(layer, {'polys': [], 'closed': 0})
            if closed and _polyline_len(pts) > 0:
                bucket['closed'] += 1
                # 封闭折线是边界/底图而非管道，跳过
                continue
            bucket['polys'].append(pts)
        elif et == 'LINE':
            a, b = e.dxf.start, e.dxf.end
            layers.setdefault(layer, {'polys': [], 'closed': 0})['polys'].append(
                [(round(a.x, 3), round(a.y, 3)), (round(b.x, 3), round(b.y, 3))])
        elif et == 'INSERT':
            valves.append({
                'block': e.dxf.name,
                'x': float(e.dxf.insert[0]), 'y': float(e.dxf.insert[1]),
                'attrs': {a.dxf.tag: a.dxf.text for a in e.attribs},
            })
        elif et in ('MTEXT', 'TEXT'):
            raw = e.text if et == 'MTEXT' else e.dxf.text
            plain = _mtext_plain(raw)
            if not plain:
                continue
            pos = e.dxf.insert if et == 'MTEXT' else (e.dxf.align_point if e.dxf.align_point else e.dxf.start)
            labels.append({'layer': layer, 'text': plain[:60],
                           'x': float(pos[0]), 'y': float(pos[1])})
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

def analyze_dxf_pipelines(uploaded_file=None, token=None):
    """解析上传的 DXF，返回页面所需的概览 + 预览几何（全部已转 lat/lng）。

    额外返回 ``token``（内容 hash）——导入阶段凭它复用本次解析结果。
    ``uploaded_file`` 为空且给了 ``token`` 时直接读解析缓存重建预览
    （三点校准保存后免重传刷新预览用）。
    """
    to_latlng, meters_per_unit = _local_to_latlng_fn()
    if to_latlng is None:
        return {'success': False, 'error': '缺少站点标定点，无法转换坐标'}

    if uploaded_file is not None:
        content = uploaded_file.read()
        if isinstance(content, str):
            content = content.encode('utf-8', errors='ignore')
        token, layers, valves, labels = _parsed_from_cache_or_file(content)
    elif token:
        hit = _parse_cache().get('dxf:parse:' + token)
        if hit is None:
            return {'success': False, 'error': '解析缓存已过期（15 分钟），请重新上传 DXF 文件'}
        layers, valves, labels = hit[0], hit[1], hit[2]
    else:
        return {'success': False, 'error': '请上传 .dxf 文件或提供解析 token'}

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
            'include_guess': _layer_diameter_guess(name) is not None
                             and not name.startswith('C-L'),
        })

    blocks = defaultdict(lambda: {'count': 0, 'attrs': set(), 'samples': []})
    for v in valves:
        blk = blocks[v['block']]
        blk['count'] += 1
        for val in v['attrs'].values():
            if val and len(blk['attrs']) < 6:
                blk['attrs'].add(val[:20])
        if len(blk['samples']) < 3:
            lat, lng = to_latlng(v['x'], v['y'])
            blk['samples'].append({'lat': lat, 'lng': lng})
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
        if len(b['points']) < 400:
            lat, lng = to_latlng(lb['x'], lb['y'])
            b['points'].append({'lat': round(lat, 6), 'lng': round(lng, 6), 'text': lb['text']})

    preview_layers = []
    for info in layer_infos[:12]:
        pts_list = layers[info['layer']]['polys']
        paths = []
        for pts in pts_list[:600]:
            paths.append([{'lat': round(la, 6), 'lng': round(ln, 6)}
                          for la, ln in (to_latlng(x, y) for x, y in pts)])
        preview_layers.append({'layer': info['layer'], 'paths': paths})
    preview_valves = []
    for v in valves:
        if len(preview_valves) >= 600:
            break
        lat, lng = to_latlng(v['x'], v['y'])
        preview_valves.append({'lat': round(lat, 6), 'lng': round(lng, 6), 'block': v['block']})

    extents = []
    for bucket in layers.values():
        for pts in bucket['polys'][:50]:
            extents.extend(pts)
    coord_info = ''
    if extents:
        xs = [p[0] for p in extents]; ys = [p[1] for p in extents]
        coord_info = f'本地坐标 X[{min(xs):.0f}..{max(xs):.0f}] Y[{min(ys):.0f}..{max(ys):.0f}]，已按站点标定转换'

    return {
        'success': True,
        'token': token,
        'coord_info': coord_info,
        'layers': layer_infos,
        'blocks': block_infos,
        'labels': [{'layer': k, 'count': v['count'], 'samples': v['samples'],
                    'points': v['points']} for k, v in label_layers.items()],
        'preview': {'layers': preview_layers, 'valves': preview_valves},
    }


# ── import：按用户映射落库 ────────────────────────────────────────────

def import_dxf_pipelines(layer_specs, block_specs, uploaded_file=None,
                         label_layers=None, valve_name_from_label=True,
                         offset=(0.0, 0.0), token=None, content=None,
                         batch_name=None, imported_by=None):
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
    from core.views import _auto_pipeline_name_code

    to_latlng, meters_per_unit = _local_to_latlng_fn()
    if to_latlng is None:
        raise ValueError('缺少站点标定点，无法转换坐标')

    if token:
        hit = _parse_cache().get('dxf:parse:' + token)
        if hit is not None:
            layers, valves, labels = hit
        else:
            token = None   # 缓存过期，退回文件解析
    if not token:
        if content is None:
            if uploaded_file is None:
                raise ValueError('缺少文件且解析缓存已过期，请重新上传解析')
            content = uploaded_file.read()
            if isinstance(content, str):
                content = content.encode('utf-8', errors='ignore')
        _, layers, valves, labels = _parsed_from_cache_or_file(content)

    usable_labels = [lb for lb in labels
                     if label_layers is None or lb['layer'] in label_layers]

    zone_rings, zone_info = _load_zone_data()

    from core.pipe_utils import _point_in_ring

    def zone_of(lat, lng):
        for zid, ring, bb in zone_rings:
            if bb[0] <= lat <= bb[1] and bb[2] <= lng <= bb[3]:
                if _point_in_ring(lat, lng, ring):
                    return zid
        return None

    off_lat, off_lng = float(offset[0] or 0), float(offset[1] or 0)

    # 名称唯一性判重：内存 set（一次 DB 读取），DB 唯一约束兜底并发
    used_names = set(Pipeline.objects.values_list('name', flat=True))
    used_codes = set(Pipeline.objects.values_list('code', flat=True))

    created_pipes = 0
    created_valves = 0
    labeled_valves = 0
    skipped_valves = 0
    layer_stats = []
    valve_rows = []
    order_by_pipe = defaultdict(int)
    all_paths = []   # (local_pts, diameter, pipeline)

    with _db_txn.atomic():
        # 批次在事务内创建：导入失败整体回滚，不留 0 管道的孤儿批次行
        batch = PipelineImportBatch.objects.create(
            name=(batch_name or 'DXF导入')[:200],
            imported_by=imported_by,
        )
        for layer, spec in layer_specs.items():
            if not spec.get('include'):
                continue
            bucket = layers.get(layer)
            if not bucket or not bucket['polys']:
                continue
            try:
                diameter = float(spec.get('diameter')) if spec.get('diameter') else None
            except (TypeError, ValueError):
                diameter = None
            ptype = spec.get('type') or 'irrigation'
            paths = _decompose_paths(bucket['polys'], JOIN_TOL_M, meters_per_unit or 1.0)
            n_paths = 0
            for pts in paths:
                ll = [{'lat': round(la + off_lat, 6), 'lng': round(ln + off_lng, 6)}
                      for la, ln in (to_latlng(x, y) for x, y in pts)]
                if len(ll) < 2:
                    continue
                # 内存穿越检测 + zone 属性查表（批量预计算，零 DB 访问）
                zids = _crossed_zone_ids([(p['lat'], p['lng']) for p in ll], zone_rings)
                name, code = _auto_pipeline_name_code(zids, ptype)
                if not name:
                    dl = f'DN{diameter:.0f}' if diameter else layer
                    name = f'{dl} 管段（DXF）'
                    code = f"{'IRR' if ptype == 'irrigation' else 'FLU'}-DXF"
                # 唯一性内存判重 + 截断到字段上限（超长在 PostgreSQL 会炸）
                base_name, base_code, n = name[:255], code[:50], 2
                while name in used_names or code in used_codes:
                    name = f'{base_name} ({n})'[:255]
                    code = f'{base_code}-{n}'[:50]
                    n += 1
                p = Pipeline.objects.create(
                    name=name, code=code,
                    pipeline_type=ptype,
                    main_diameter=diameter,
                    flow_direction=Pipeline.FLOW_FORWARD,
                    source_label=f'DXF导入 · 图层 {layer}',
                    line_points=ll,
                    import_batch=batch,
                )
                used_names.add(name)
                used_codes.add(code)
                if zids:
                    p.zones.set(zids)
                all_paths.append((pts, diameter, p))
                created_pipes += 1
                n_paths += 1
            layer_stats.append({'layer': layer, 'paths': n_paths,
                                'segments': len(bucket['polys'])})

        # 阀门吸附：网格空间索引 + 米制容差换算
        snap_units = SNAP_TOL_M / (meters_per_unit or 1.0)
        grid = _SegmentGrid(snap_units)
        for pi, (pts, _dia, _p) in enumerate(all_paths):
            for i in range(len(pts) - 1):
                grid.add((pi, i), pts[i], pts[i + 1])
        label_units = LABEL_RADIUS_M / (meters_per_unit or 1.0)
        label_idx = _LabelIndex(usable_labels) if usable_labels else None

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
                continue
            _, pi = best
            pts, diameter, pipe = all_paths[pi]
            lat, lng = to_latlng(v['x'], v['y'])
            lat += off_lat; lng += off_lng
            name = ''
            if label_idx:
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
                valve_type=vtype,
                diameter=vdia,
                order=order_by_pipe[pipe.id],
            ))
            created_valves += 1
        if valve_rows:
            PipeValve.objects.bulk_create(valve_rows)

    return {
        'pipelines': created_pipes,
        'valves': len(valve_rows),
        'labeled_valves': labeled_valves,
        'skipped_valves': skipped_valves,
        'layer_stats': layer_stats,
        'batch_id': batch.id,
    }
