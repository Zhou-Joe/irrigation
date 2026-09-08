"""站点标定数学：DXF 本地坐标(negY) ↔ WGS84 的拟合与逆变换。

纯函数模块（仅依赖标准库），客户端镜像在 static/js/dxf-import/dxf-cal-math.js。
方法：'sim' 相似最小二乘（2-N 点）· 'tps' 薄板样条（≥4 点精确过点）·
'mls' 移动最小二乘（边界稳定）；''/None 按点数自动选型。
"""
import math

# ─── Site Calibration ───
# Two reference points mapping local DXF coordinates to WGS84 (lat, lng).
# Update these when the surveyor's coordinate system changes.
SITE_CALIBRATION_POINTS = [
    {'dxf_x': 18199.4368, 'dxf_y': -10216.4603, 'lat': 31.1431589, 'lng': 121.6579836},
    {'dxf_x': 18220.5437, 'dxf_y': -10196.3886, 'lat': 31.1433414, 'lng': 121.6582022},
]



def iso_k(pairs):
    """经度归一因子 k = cos(平均纬度)。

    所有拟合都在 (lat, lng·k) 归一空间进行：两轴"每度米数"一致(≈111320)，
    等比/TPS/MLS 才能正确表达米制图纸的几何。直接在原始度空间拟合时，
    经度方向每度比纬度短 cos(φ)（上海 ≈14%），等比变换装不下这份各向
    异性，会被迫折成一个**虚假旋转角**——2 点标定在点上完全重合（零残差
    无警告），远离标定基线的区域偏移可达百米~公里级（甲方报告的"导入后
    与卫星图对不上"即此）。TPS/MLS 同样受益：不再需要用弯曲去补偿一个
    本可解析消除的线性各向异性。
    """
    return math.cos(math.radians(sum(p['lat'] for p in pairs) / len(pairs)))


def similarity_transform_ls(pairs, k=None):
    """N点(≥2)相似变换最小二乘：lat = a*x + b*y + c；lng·k = -b*x + a*y + d。

    与 ``_similarity_transform`` 同一变换形式；N≥3 时存在多余约束，可给出
    每点残差（米）与 RMS，用于标定质量评估。传入的 pairs 需与现有调用方
    一致（DXF y 已取反）。``k`` 为经度归一因子（None=按平均纬度自动）；
    目标不是经纬度（逆变换的反向拟合，目标=绘图单位）时显式传 1.0。
    返回 ``(transform_fn, stats)``；退化输入返回 ``(None, 错误消息)``。
    """
    import math
    if k is None:
        k = iso_k(pairs)
    n = len(pairs)
    if n < 2:
        return None, '标定点至少需要 2 个'
    mx = sum(p['dxf_x'] for p in pairs) / n
    my = sum(p['dxf_y'] for p in pairs) / n
    mlat = sum(p['lat'] for p in pairs) / n
    mlng = sum(p['lng'] * k for p in pairs) / n
    nr = ni = denom = 0.0
    for p in pairs:
        x, y = p['dxf_x'] - mx, p['dxf_y'] - my
        la, ln = p['lat'] - mlat, p['lng'] * k - mlng
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
        return (a * x + b * y + c, (-b * x + a * y + d) / k)

    # 残差（米）：先还原成真实度，再等距圆柱近似换算
    residuals = []
    for p in pairs:
        plat, plng = transform(p['dxf_x'], p['dxf_y'])
        dlatm = (p['lat'] - plat) * 111320.0
        dlngm = (p['lng'] - plng) * 111320.0 * math.cos(math.radians(p['lat']))
        residuals.append(math.hypot(dlatm, dlngm))
    rms = math.sqrt(sum(r * r for r in residuals) / n)
    stats = {
        'a': a, 'b': b, 'c': c, 'd': d, 'iso_k': k,
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


def tps_fit(pairs, k=None):
    """N点(≥4) TPS 拟合：pairs 同 similarity_transform_ls 格式。

    返回 (transform_fn, stats)。控制点零残差（精确落位），因此 stats 的
    residuals_m / rms_m 用**留一交叉验证**（LOO）：逐点用其余点重拟合、
    预测该点——这是 TPS 泛化误差的诚实度量（GIS 惯例：TPS 在控制点上
    残差恒为 0，展示残差没有意义）。退化输入返回 (None, 错误消息)。
    拟合在 (lat, lng·k) 归一空间（见 iso_k）；``k``=None 自动。
    """
    n = len(pairs)
    if n < 4:
        return None, 'TPS 至少需要 4 个标定点'
    if k is None:
        k = iso_k(pairs)
    src = [(p['dxf_x'], p['dxf_y']) for p in pairs]
    dst = [(p['lat'], p['lng'] * k) for p in pairs]
    coeffs = _tps_fit_core(src, dst)
    if coeffs is None:
        return None, '标定点过于集中或存在重复点，无法拟合 TPS'
    _raw_fn = tps_from_coeffs(coeffs)

    def fn(x, y):
        u, v = _raw_fn(x, y)
        return (u, v / k)

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
            pred = sub_fn(*src[i])
            residuals.append(_residual_m((pred[0], pred[1] / k),
                                         dst[i][0], pairs[i]['lng']))
    valid = [r for r in residuals if r is not None]
    rms = math.sqrt(sum(r * r for r in valid) / len(valid)) if valid else None

    # 对照：同样点数下的相似变换 RMS（用户能看到 TPS 带来多大改善）
    _sim_fn, sim_stats = similarity_transform_ls(pairs, k)
    stats = {
        'method': 'tps', 'n': n, 'iso_k': k,
        'coeffs': coeffs,
        'rms_m': rms,
        'residuals_m': [None if r is None else round(r, 2) for r in residuals],
        'sim_rms_m': sim_stats['rms_m'] if sim_stats else None,
        'scale': sim_stats['scale'] if sim_stats else None,
        'rotation_deg': sim_stats['rotation_deg'] if sim_stats else None,
    }
    return fn, stats


def mls_fit(pairs, k=None, _skip=None):
    """N点(≥2) MLS 相似变形（Moving Least Squares，Schaefer et al. 2006 的
    加权相似最小二乘等价形式）：对每个待求点 v，按 w_i = 1/(d_i²+ε²) 加权
    在控制点上拟合一个局部相似变换（中心化的相似 LS 闭式解）再作用于 v。

    与 TPS 的取舍：MLS 每个点只受**附近**控制点显著影响——控制点稀疏/
    覆盖区外的行为远比 TPS 稳定（远处自动退化成整体相似变换而不是外推
    发飘），单个坏点也只污染局部。控制点上近似精确落位（ε 很小时权重
    完全集中在自身）。无全局方程组、无需数值求解。评估 O(N)/点。

    ``_skip``：LOO 用——跳过该下标的控制点。拟合在 (lat, lng·k) 归一空间
    （见 iso_k）；``k``=None 自动。
    """
    n = len(pairs)
    if n - (1 if _skip is not None else 0) < 2:
        return None, 'MLS 至少需要 2 个标定点'
    if k is None:
        k = iso_k(pairs)
    px = [p['dxf_x'] for p in pairs]
    py = [p['dxf_y'] for p in pairs]
    plngn = [p['lng'] * k for p in pairs]
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
            slaw += w * pairs[i]['lat']; slnw += w * plngn[i]
        if sw <= 0:
            return None
        mx, my, mla, mln = sxw / sw, syw / sw, slaw / sw, slnw / sw
        for i in range(n):
            if _skip is not None and i == _skip:
                continue
            w = 1.0 / ((px[i] - x) ** 2 + (py[i] - y) ** 2 + eps2)
            cx, cy = px[i] - mx, py[i] - my
            cla, cln = pairs[i]['lat'] - mla, plngn[i] - mln
            nr += w * (cx * cla + cy * cln)
            ni += w * (cy * cla - cx * cln)
            den += w * (cx * cx + cy * cy)
        if den < 1e-18:
            return None
        a, b = nr / den, ni / den
        dx, dy = x - mx, y - my
        return (a * dx + b * dy + mla, (-b * dx + a * dy + mln) / k)

    fn = lambda x, y: transform(x, y)

    # LOO 残差：MLS 无需重拟合——评估时跳过自身即可，天然精确的留一验证
    residuals = []
    for j in range(n):
        pred = transform(px[j], py[j], _skip=j)
        residuals.append(None if pred is None else
                         _residual_m(pred, pairs[j]['lat'], pairs[j]['lng']))
    valid = [r for r in residuals if r is not None]
    rms = math.sqrt(sum(r * r for r in valid) / len(valid)) if valid else None
    _sf, sim_stats = similarity_transform_ls(pairs, k)
    stats = {
        'method': 'mls', 'n': n, 'iso_k': k,
        'rms_m': rms,
        'residuals_m': [None if r is None else round(r, 2) for r in residuals],
        'sim_rms_m': sim_stats['rms_m'] if sim_stats else None,
        'scale': sim_stats['scale'] if sim_stats else None,
        'rotation_deg': sim_stats['rotation_deg'] if sim_stats else None,
    }
    return fn, stats


def fit_calibration_transform(pairs, method=None, k=None):
    """按 method/点数选型：'sim' → 强制相似 LS；'mls' → MLS；''/None 自动
    （≥4 → TPS 橡皮筋；2-3 → 相似 LS）。

    所有标定链路（预览换算 / info / 保存校验 / 追溯应用）统一走这里，
    保证「保存时验证的变换」与「导入时使用的变换」是同一个。
    'sim' 显式强制：累积选点常带着 ≥4 组旧点，UI 选"三点最小二乘"时
    不能被自动选型静默升级成 TPS。
    ``k``：经度归一因子（None=自动）。目标不是经纬度（反向拟合的
    目标=绘图单位）时由调用方显式传 1.0，防止 auto 取 cos(绘图坐标)。
    """
    if method == 'sim' and len(pairs) >= 2:
        fn, stats = similarity_transform_ls(pairs, k)
        stats['method'] = 'similarity'
        return fn, stats
    if method == 'mls' and len(pairs) >= 2:
        return mls_fit(pairs, k)
    if len(pairs) >= 4:
        return tps_fit(pairs, k)
    return similarity_transform_ls(pairs, k)


def fit_calibration_inverse(pairs, method=None):
    """标定的反向变换 (lat,lng)→(dxf_x, dxf_y)。

    相似变换走**解析逆**（similarity_inverse——控制点上零误差，与
    active_calibration_info 给客户端的逆是同一套系数）；method='sim' 或
    ''/None 且 <4 点（正向即相似）同此。TPS/MLS 无解析逆——直接把点对
    调个方向重新拟合（GIS 常规做法，误差量级与正向一致）。

    系数均活在 (lat, lng·k) 归一空间：解析逆与反向拟合的**输入**经度
    都先乘 k，输出不再除回（目标就是绘图单位）。

    返回 inverse_fn 或 None。注意 pairs 的 dxf_y 已是取反后的 negY 空间
    （与 similarity_inverse 的返回语义一致：调用方再自行取反回 DXF y）。
    """
    k = iso_k(pairs)
    if method == 'sim' or (method in (None, '') and len(pairs) < 4):
        fn, stats = similarity_transform_ls(pairs, k)
        if not callable(fn):
            return None
        inv = similarity_inverse(stats['a'], stats['b'], stats['c'], stats['d'])
        if not inv:
            return None
        return lambda lat, lng: (inv['ia'] * lat + inv['ib'] * (lng * k) + inv['ic'],
                                 -inv['ib'] * lat + inv['ia'] * (lng * k) + inv['id'])
    rev = [{'dxf_x': p['lat'], 'dxf_y': p['lng'] * k,
            'lat': p['dxf_x'], 'lng': p['dxf_y']} for p in pairs]
    fn, _stats = fit_calibration_transform(rev, 'mls' if method == 'mls' else None, k=1.0)
    if callable(fn):
        return lambda lat, lng: fn(lat, lng * k)
    return None
