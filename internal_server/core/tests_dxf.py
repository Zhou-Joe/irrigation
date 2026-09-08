"""DXF 管线导入：标定数学 / bulge 细分 / 逐批追溯应用 / 导入冒烟 的数值回归。

对应实现：core/calibration.py（数学）、core/dxf_pipeline_utils.py（解析+导入）、
core/dxf_views.py（apply 端点）、static/js/dxf-import/dxf-cal-math.js（客户端镜像）。
历史背景：逐批 apply 修复了「多轮保存+应用叠加漂移」，曾引入过事务内中途
return 的部分提交缺陷（现已在写入前统一解析逆变换）——此处全部固化为断言。
"""
import json
import unittest
import math
import os

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from core.calibration import (
    SITE_CALIBRATION_POINTS, fit_calibration_transform, fit_calibration_inverse,
    similarity_inverse, similarity_transform_ls, tps_fit,
)
from core.dxf_pipeline_utils import _bulge_arc_points, _polyline_pts, import_dxf_pipelines

DXF_PATH = os.path.join(os.path.dirname(settings.BASE_DIR), 'Test dxf.dxf')
SKIP_DXF = not os.path.exists(DXF_PATH)


def _cal(pairs):
    return [{'dxf_x': p['dxf_x'], 'dxf_y': -p['dxf_y'], 'lat': p['lat'], 'lng': p['lng']}
            for p in pairs]


def _mk(dlat, dlng):
    """一对平移的标定点（本地坐标同点、卫星点偏移 dlat/dlng）。"""
    return [{'dxf_x': 100.0, 'dxf_y': -200.0, 'lat': 31.1000 + dlat, 'lng': 121.6000 + dlng},
            {'dxf_x': 300.0, 'dxf_y': -400.0, 'lat': 31.1020 + dlat, 'lng': 121.6020 + dlng}]


LOCAL_PTS = [(150, -250), (250, -350)]


class CalibrationMathTests(SimpleTestCase):
    """core/calibration.py 的方法语义与逆变换一致性。"""

    # sim 一致数据：negY 空间标准相似 + 第 5 点 3e-6°(≈0.3m) 不一致。
    # lng 在**归一空间**生成（÷k）：拟合自 2026-09 起在 (lat, lng·k) 空间
    # 进行（经度各向异性修复），一致数据必须按同一空间构造。
    A, B, C, D = 9e-6, 2e-6, 31.0, 121.0

    @classmethod
    def sim5(cls):
        grid = [(0, 0), (100, 0), (0, 100), (100, 100), (50, 30)]
        lats = [cls.A * x + cls.B * yn + cls.C for x, yn in grid]
        k = math.cos(math.radians(sum(lats) / len(lats)))
        pts = []
        for (x, yn), la in zip(grid, lats):
            pts.append({'dxf_x': float(x), 'dxf_y': float(-yn),
                        'lat': la,
                        'lng': (-cls.B * x + cls.A * yn + cls.D) / k})
        pts[4]['lat'] += 3e-6
        return pts

    def test_sim_inverse_is_analytic_and_exact(self):
        """'sim'（含 ≥4 点）的逆必须是解析逆：inv∘fwd 恒等，控制点反解零残差。"""
        cal = _cal(self.sim5())
        fwd, st = fit_calibration_transform(cal, 'sim')
        inv = fit_calibration_inverse(cal, 'sim')
        self.assertEqual(st['method'], 'similarity', '≥4 点强制 sim 不得升级为 TPS')
        rt = max(abs(inv(*fwd(x, -y))[0] - x) + abs(inv(*fwd(x, -y))[1] + y)
                 for x, y in [(37, 11), (120, 90), (0, 0)])
        self.assertLess(rt, 1e-5)
        cp = max(abs(inv(p['lat'], p['lng'])[0] - p['dxf_x']) for p in self.sim5())
        self.assertLess(cp, 1.0, '控制点反解偏差应≈注入残差(0.3 单位)')

    def test_tps_exact_at_controls(self):
        pts = self.sim5() + [
            {'dxf_x': 20.0, 'dxf_y': -60.0, 'lat': 31.0009, 'lng': 121.0013}]
        fn, stats = tps_fit(_cal(pts))
        self.assertIsNotNone(fn)
        self.assertEqual(stats['method'], 'tps')
        err = max(math.hypot(fn(p['dxf_x'], -p['dxf_y'])[0] - p['lat'],
                             fn(p['dxf_x'], -p['dxf_y'])[1] - p['lng'])
                  for p in pts)
        self.assertLess(err, 1e-9, 'TPS 控制点必须精确过点')

    def test_similarity_inverse_roundtrip(self):
        fn, st = similarity_transform_ls(_cal(SITE_CALIBRATION_POINTS))
        inv = similarity_inverse(st['a'], st['b'], st['c'], st['d'])
        p = (18000.0, -10100.0)
        la, ln = fn(*p)
        x, y = inv['ia'] * la + inv['ib'] * ln * st['iso_k'] + inv['ic'], \
               -inv['ib'] * la + inv['ia'] * ln * st['iso_k'] + inv['id']
        self.assertAlmostEqual(x, p[0], places=6)
        self.assertAlmostEqual(y, p[1], places=6)

    # ── 经度各向异性回归（甲方报告：DXF 导入后与卫星图对不上）──────────
    # 物理自洽构造：地面 EN(米) → DXF 绘图坐标(x, y_raw)与 WGS84。旧代码
    # 直接在原始度空间拟合等比变换，装不下「经度每度比纬度短 cos(φ)」的
    # 各向异性 → 折成虚假旋转角（2 点标定零残差静默通过，3 km 外偏 4 km）。
    X0, Y0_RAW, LAT0, LNG0 = 18199.4368, 10216.4603, 31.1431589, 121.6579836

    @classmethod
    def enu(cls, E, N, theta=0.0):
        """E/N=东/北米制，theta=图幅相对北的旋转角（度）。"""
        t = math.radians(theta)
        return {
            'dxf_x': cls.X0 + E * math.cos(t) + N * math.sin(t),
            'dxf_y': cls.Y0_RAW - E * math.sin(t) + N * math.cos(t),   # 原始 DXF y（北正）
            'lat': cls.LAT0 + N / 111320.0,
            'lng': cls.LNG0 + E / (111320.0 * math.cos(math.radians(cls.LAT0))),
        }

    @staticmethod
    def _err_m(got, want, lat_ref):
        cos = math.cos(math.radians(lat_ref))
        return math.hypot((got[0] - want[0]) * 111320.0,
                          (got[1] - want[1]) * 111320.0 * cos)

    def test_sim_absorbs_lng_anisotropy_far_from_baseline(self):
        """2 点等比标定：任意图幅旋转下，远离基线的点必须亚厘米级命中。"""
        for theta in (0.0, 15.0, -30.0):
            cal = _cal([self.enu(-2000, -1500, theta), self.enu(2000, 1500, theta)])
            fn, st = similarity_transform_ls(cal)
            self.assertAlmostEqual(st['rms_m'], 0.0, places=6)
            worst = 0.0
            for E, N in [(3000, 0), (0, 3000), (3536, 3536), (-3200, 2400)]:
                p = self.enu(E, N, theta)
                worst = max(worst, self._err_m(
                    fn(p['dxf_x'], -p['dxf_y']), (p['lat'], p['lng']), p['lat']))
            self.assertLess(worst, 0.01,
                            f'θ={theta}° 远点 {worst:.2f} m（旧度空间拟合此处为 km 级）')

    def test_short_baseline_two_point_stays_accurate(self):
        """29 m 短基线 2 点（默认标定形态）：3 km 外仍须亚厘米。"""
        cal = _cal([self.enu(0, 0), self.enu(21.1, 20.1)])
        fn, _st = similarity_transform_ls(cal)
        worst = max(self._err_m(fn(p['dxf_x'], -p['dxf_y']), (p['lat'], p['lng']), p['lat'])
                    for p in [self.enu(3000, 0), self.enu(0, 3000), self.enu(-2500, -1800)])
        self.assertLess(worst, 0.05, f'短基线远点 {worst:.2f} m')

    def test_tps_mls_far_point_and_inverse_roundtrip(self):
        """TPS/MLS 5 点标定（旋转 15°）：控制点外 5 km 远点 <1 m，逆变换往返成立。"""
        cal = _cal([self.enu(e, n, 15.0) for e, n in
                    [(-2000, -1500), (2000, -1500), (-2000, 1500), (2000, 1500), (0, 0)]])
        far = self.enu(3536, 3536, 15.0)
        for method in ('tps', 'mls'):
            fn, _st = fit_calibration_transform(cal, method)
            err = self._err_m(fn(far['dxf_x'], -far['dxf_y']),
                              (far['lat'], far['lng']), far['lat'])
            self.assertLess(err, 1.0, f'{method} 远点 {err:.2f} m')
            inv = fit_calibration_inverse(cal, method)
            rt = max(max(abs(inv(*fn(p['dxf_x'], -p['dxf_y']))[i] - v)
                         for i, v in enumerate((p['dxf_x'], -p['dxf_y'])))
                     for p in cal)
            self.assertLess(rt, 0.05, f'{method} 逆变换控制点往返 {rt:.3f} 单位')


class BulgeTessellationTests(SimpleTestCase):
    """折线 bulge 弧段细分：方向/圆性。"""

    def test_direction_matches_ezdxf_baseline(self):
        """bulge=+1 走下半圆、-1 走上半圆（与 ezdxf make_path 基准一致）。"""
        up = _bulge_arc_points((0, 0), (1, 0), -1.0)
        dn = _bulge_arc_points((0, 0), (1, 0), 1.0)
        apex_up = max(p[1] for p in up)
        apex_dn = min(p[1] for p in dn)
        self.assertTrue(0.4 < apex_up < 0.6, f'bulge=-1 弧顶应在弦上方≈+0.5, got {apex_up}')
        self.assertTrue(-0.6 < apex_dn < -0.4, f'bulge=+1 弧顶应在弦下方≈-0.5, got {apex_dn}')

    def test_points_on_circle(self):
        from ezdxf.math import bulge_to_arc
        a, b, bulge = (18019.52, -10048.88), (18018.85, -10048.04), 0.0936
        pts = _bulge_arc_points(a, b, bulge)
        c, sa, ea, r = bulge_to_arc(a, b, bulge)
        worst = max(abs(math.hypot(px - c[0], py - c[1]) - r) for px, py in pts)
        self.assertLess(worst, 1e-3, '细分点必须落在真实圆上（容差=坐标 3 位小数舍入）')

    def test_polyline_pts_expands_arcs(self):
        raw = [(0.0, 0.0, 1.0), (10.0, 0.0, 0.0)]
        pts = _polyline_pts(raw)
        self.assertGreater(len(pts), 5, '半圆弧应细分出多个点')
        self.assertEqual(pts[0], (0.0, 0.0))
        self.assertEqual(pts[-1], (10.0, 0.0))


@override_settings(ALLOWED_HOSTS=['testserver'])
class ApplyPerBatchTests(TestCase):
    """逐批旧标定推导 + 不可逆零写入（曾出现过的 P0 回归网）。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('dxf_admin', 'a@b.c', 'x')
        cls.rf = RequestFactory()

    def _apply(self):
        from core import dxf_views
        req = self.rf.post('/x/', {'confirm': '1', 'force': '1'})
        req.user = self.user
        resp = dxf_views.pipeline_dxf_calibration_apply(req)
        return resp.status_code, json.loads(resp.content)

    @staticmethod
    def _line(pairs, pts):
        fn, _ = fit_calibration_transform(_cal(pairs), 'sim')
        return [{'lat': round(v[0], 7), 'lng': round(v[1], 7)}
                for v in (fn(x, -y) for x, y in pts)]

    def test_batch_remaps_by_its_import_time_calibration(self):
        """批次导入时生效标定 A，保存 B（未应用）→ apply 后应精确落在 B(local)。"""
        from core.models import Pipeline, PipelineImportBatch, SiteCalibration
        SiteCalibration.objects.create(points=_mk(0, 0), method='sim')
        batch = PipelineImportBatch.objects.create(name='t')
        p = Pipeline.objects.create(
            name='t-p', code='TP', import_batch=batch, line_points=self._line(_mk(0, 0), LOCAL_PTS))
        SiteCalibration.objects.create(points=_mk(0.0008, 0.0012), method='sim')

        status, d = self._apply()
        self.assertEqual(status, 200, d)
        self.assertTrue(d['success'], d)
        want = self._line(_mk(0.0008, 0.0012), LOCAL_PTS)
        p.refresh_from_db()
        got = max(abs(a['lat'] - b['lat']) + abs(a['lng'] - b['lng'])
                  for a, b in zip(p.line_points, want))
        self.assertLess(got, 1e-6, '批次管道应精确重算到新标定（不叠加）')

    def test_irreversible_old_row_aborts_with_zero_writes(self):
        """旧标定不可逆 → 400 且全库零写入（atomic 内 return 会提交的 P0）。"""
        from core.models import Pipeline, PipelineImportBatch, SiteCalibration
        SiteCalibration.objects.create(points=_mk(0, 0), method='sim')
        # 4 点含精确重复 DXF 点的 'tps'（正向 TPS 奇异 → 逆=None）——必须先于批次创建，
        # 才是「批次导入时刻的生效标定」
        bad = [{'dxf_x': 500.0, 'dxf_y': -500.0, 'lat': 31.20, 'lng': 121.70},
               {'dxf_x': 500.0, 'dxf_y': -500.0, 'lat': 31.2001, 'lng': 121.7001},
               {'dxf_x': 600.0, 'dxf_y': -600.0, 'lat': 31.2011, 'lng': 121.7011},
               {'dxf_x': 700.0, 'dxf_y': -700.0, 'lat': 31.2021, 'lng': 121.7021}]
        fnb, _ = fit_calibration_transform(_cal(bad), None)
        self.assertFalse(callable(fnb), '构造前提：坏行正向 TPS 应不可拟合')
        SiteCalibration.objects.create(points=bad, method='tps')
        batch = PipelineImportBatch.objects.create(name='t2')
        frozen = [{'lat': 31.21, 'lng': 121.71}, {'lat': 31.2101, 'lng': 121.7101}]
        p = Pipeline.objects.create(name='t-bad', code='TB', import_batch=batch,
                                    line_points=[dict(x) for x in frozen])
        SiteCalibration.objects.create(points=_mk(0, 0), method='sim')

        status, d = self._apply()
        self.assertEqual(status, 400)
        self.assertFalse(d['success'])
        self.assertIn('不可逆', d['error'])
        p.refresh_from_db()
        self.assertEqual(p.line_points, frozen, '中止时不得有任何写入')


@override_settings(ALLOWED_HOSTS=['testserver'])
@unittest.skipUnless(not SKIP_DXF, '仓库根目录缺少 Test dxf.dxf')
class AnalyzeImportSmokeTests(TestCase):
    """端到端冒烟：analyze 接口（含 bulge 细分）+ import 行数锚点。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('dxf_smoke', 'a@b.c', 'x')

    def test_analyze_and_import(self):
        from django.test import Client
        c = Client()
        c.force_login(self.user)
        with open(DXF_PATH, 'rb') as f:
            r = c.post('/pipelines/dxf/analyze/', {'file': f})
        d = r.json()
        self.assertTrue(d['success'], d.get('error'))
        self.assertEqual(d['token'], 'd6b96e7916d1e8b0cd08b529ec3933db')  # 内容 hash 锚点
        ad = next(pl for pl in d['preview']['layers'] if pl['layer'] == 'AD-I-LL')
        self.assertGreaterEqual(sum(len(p) for p in ad['paths']), 140,
                                'AD-I-LL 的 bulge 弧应已细分（旧值 100 顶点）')
        # 导入：测试库无 SiteCalibration 行 → 默认两点标定，计数确定
        specs_layers = {l['layer']: {'include': l['layer'] in ('100', '75', '150')}
                        for l in d['layers']}
        specs_blocks = {b['block']: {'include': True} for b in d['blocks']}
        res = import_dxf_pipelines(specs_layers, specs_blocks, token=d['token'],
                                   batch_name='smoke', imported_by=self.user)
        self.assertEqual(res['pipelines'], 324 + 69 + 12)
        self.assertEqual(res['layer_stats'][0]['layer'], '100')
