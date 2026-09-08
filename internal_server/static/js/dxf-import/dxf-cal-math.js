/* DXF 管线导入 — 由 pipeline_dxf_import.html 内联脚本机械拆出（零逻辑改动）。
 * 页面引导块(window.__DXF__)必须在本文件之前加载。全局函数/变量共享，无模块系统。 */
// ── 校准数学（core.dxf_utils 的客户端镜像：sim LS / TPS / MLS）——纯函数，可 node 单测 ──
// 所有拟合都在 (lat, lng·k) 归一空间（k=cos 平均纬度）：经度每度比纬度短
// cos(φ)，原始度空间的等比变换装不下这份各向异性，会折成虚假旋转角，
// 远离标定基线漂移可达百米~公里级。与服务端 core/calibration.py 完全一致。
function pdxfIsoK(pairs) {
  var s = 0;
  for (var i = 0; i < pairs.length; i++) s += pairs[i].satLat;
  return Math.cos(s / pairs.length / 180 * Math.PI);
}
function pdxfCalFitPairs(pairs) {
  var n = pairs.length;
  if (n < 2) return null;
  var k = pdxfIsoK(pairs);
  var mx = 0, my = 0, mla = 0, mln = 0;
  pairs.forEach(function (p) { mx += p.dxfX; my += -p.dxfY; mla += p.satLat; mln += p.satLng * k; });
  mx /= n; my /= n; mla /= n; mln /= n;
  var nr = 0, ni = 0, den = 0;
  pairs.forEach(function (p) {
    var x = p.dxfX - mx, y = -p.dxfY - my, la = p.satLat - mla, ln = p.satLng * k - mln;
    nr += x * la + y * ln; ni += y * la - x * ln; den += x * x + y * y;
  });
  if (den < 1e-12) return null;
  var a = nr / den, b = ni / den;
  var c = mla - a * mx - b * my, d = mln + b * mx - a * my;
  var residuals = pairs.map(function (p) {
    var pla = a * p.dxfX + b * (-p.dxfY) + c;
    var pln = (-b * p.dxfX + a * (-p.dxfY) + d) / k;
    var dlatm = (p.satLat - pla) * 111320;
    var dlngm = (p.satLng - pln) * 111320 * Math.cos(p.satLat / 180 * Math.PI);
    return Math.hypot(dlatm, dlngm);
  });
  var rms = Math.sqrt(residuals.reduce(function (s, r) { return s + r * r; }, 0) / n);
  return { a: a, b: b, c: c, d: d,
           scale: Math.hypot(a, b),
           rotation_deg: Math.atan2(-b, a) * 180 / Math.PI,
           residuals_m: residuals, rms_m: rms, n: n };
}

// 单点残差（米）：给定拟合系数算某配对点的偏差 — 验证点用。
function pdxfCalResidualOf(fit, p) {
  var k = pdxfIsoK([p]);
  var pla = fit.a * p.dxfX + fit.b * (-p.dxfY) + fit.c;
  var pln = (-fit.b * p.dxfX + fit.a * (-p.dxfY) + fit.d) / k;
  var dlatm = (p.satLat - pla) * 111320;
  var dlngm = (p.satLng - pln) * 111320 * Math.cos(p.satLat / 180 * Math.PI);
  return Math.hypot(dlatm, dlngm);
}

// ── TPS（薄板样条）客户端拟合 — 与服务端 core.dxf_utils 相同算法 ────────
function pdxfTpsKernel(r) { return r > 0 ? r * r * Math.log(r) : 0; }
function pdxfSolveLin(a, b) {
  var n = a.length, m = [];
  for (var i = 0; i < n; i++) m.push(a[i].slice().concat([b[i]]));
  for (var c = 0; c < n; c++) {
    var piv = c;
    for (var r = c + 1; r < n; r++) if (Math.abs(m[r][c]) > Math.abs(m[piv][c])) piv = r;
    if (Math.abs(m[piv][c]) < 1e-12) return null;
    var t = m[c]; m[c] = m[piv]; m[piv] = t;
    for (var r2 = c + 1; r2 < n; r2++) {
      var f = m[r2][c] / m[c][c];
      if (f) for (var cc = c; cc <= n; cc++) m[r2][cc] -= f * m[c][cc];
    }
  }
  var x = new Array(n);
  for (var i2 = n - 1; i2 >= 0; i2--) {
    var s = m[i2][n];
    for (var j = i2 + 1; j < n; j++) s -= m[i2][j] * x[j];
    x[i2] = s / m[i2][i2];
  }
  return x;
}
// pairs: [{dxfX, dxfY, satLat, satLng}]（dxfY 原始坐标，内部取反成 negY）
function pdxfTpsFitCore(src, dst) {
  var n = src.length;
  if (n < 3) return null;
  var cx = 0, cy = 0;
  src.forEach(function (p) { cx += p[0]; cy += p[1]; }); cx /= n; cy /= n;
  var s = 0;
  src.forEach(function (p) { s = Math.max(s, Math.hypot(p[0] - cx, p[1] - cy)); });
  if (s < 1e-9) return null;
  var norm = src.map(function (p) { return [(p[0] - cx) / s, (p[1] - cy) / s]; });
  var size = n + 3, mat = [];
  for (var i = 0; i < size; i++) mat.push(new Array(size).fill(0));
  for (var a = 0; a < n; a++) {
    for (var b = 0; b < n; b++) {
      if (a !== b) mat[a][b] = pdxfTpsKernel(Math.hypot(norm[a][0] - norm[b][0], norm[a][1] - norm[b][1]));
    }
    mat[a][n] = 1; mat[a][n + 1] = norm[a][0]; mat[a][n + 2] = norm[a][1];
    mat[n][a] = 1; mat[n + 1][a] = norm[a][0]; mat[n + 2][a] = norm[a][1];
  }
  var out = { cx: cx, cy: cy, s: s, n: n, src: src.map(function (p) { return [p[0], p[1]]; }) };
  for (var ax = 0; ax < 2; ax++) {
    var key = ax === 0 ? 'u' : 'v';
    var rhs = dst.map(function (p) { return p[ax]; }).concat([0, 0, 0]);
    var sol = pdxfSolveLin(mat, rhs);
    if (!sol) return null;
    out[key + 'w'] = sol.slice(0, n);
    out[key + 'a'] = sol.slice(n);
  }
  return out;
}
function pdxfTpsApply(c, x, y) {
  var ux = (x - c.cx) / c.s, uy = (y - c.cy) / c.s;
  var su = c.ua[0] + c.ua[1] * ux + c.ua[2] * uy;
  var sv = c.va[0] + c.va[1] * ux + c.va[2] * uy;
  for (var i = 0; i < c.n; i++) {
    var k = pdxfTpsKernel(Math.hypot(ux - (c.src[i][0] - c.cx) / c.s,
                                      uy - (c.src[i][1] - c.cy) / c.s));
    if (k) { su += c.uw[i] * k; sv += c.vw[i] * k; }
  }
  return [su, sv];
}
// 完整 TPS 拟合（含 LOO 残差，negY 空间）— 返回与服务端 stats 对应的结构。
// n>30 时 JS 端跳过 LOO（n 次重拟合在浏览器里太慢），保存时服务端会算全量。
// 拟合在 (lat, lng·k) 归一空间（与服务端一致）。
function pdxfTpsFit(pairs) {
  var n = pairs.length;
  if (n < 4) return null;
  var k = pdxfIsoK(pairs);
  var src = pairs.map(function (p) { return [p.dxfX, -p.dxfY]; });
  var dst = pairs.map(function (p) { return [p.satLat, p.satLng * k]; });
  var c = pdxfTpsFitCore(src, dst);
  if (!c) return null;
  var loo = [];
  if (n <= 30) {
    for (var i = 0; i < n; i++) {
      var s2 = src.slice(0, i).concat(src.slice(i + 1));
      var d2 = dst.slice(0, i).concat(dst.slice(i + 1));
      var sub = pdxfTpsFitCore(s2, d2);
      if (!sub) { loo.push(null); continue; }
      var pred = pdxfTpsApply(sub, src[i][0], src[i][1]);
      var dlatm = (dst[i][0] - pred[0]) * 111320;
      var dlngm = (dst[i][1] / k - pred[1] / k) * 111320 * Math.cos(dst[i][0] / 180 * Math.PI);
      loo.push(Math.hypot(dlatm, dlngm));
    }
  }
  var valid = loo.filter(function (r) { return r != null; });
  var rms = valid.length ? Math.sqrt(valid.reduce(function (s3, r) { return s3 + r * r; }, 0) / valid.length) : null;
  var sim = (n <= 60) ? pdxfCalFitPairs(pairs) : null;   // 对照：等比变换在同点数下的 RMS
  return { method: 'tps', coeffs: c, n: n, loo_m: loo, rms_m: rms,
           sim_rms_m: sim ? sim.rms_m : null };
}

// ── MLS（移动最小二乘相似变形）客户端 — 与服务端 core.dxf_utils.mls_fit 相同 ──
// 对每个待求点按 1/(d²+ε²) 加权拟合局部相似变换；LOO 直接跳过自身评估。
// 输入 pairs/query 的经度均为**归一值**（satLng·k）——与服务端约定一致，
// 由调用方（pdxfMlsFit 本地拟合 / 服务端 inverse 点对）负责乘 k。
function pdxfMlsApply(pairs, x, y, skip) {
  var n = pairs.length;
  var minx = 1e18, maxx = -1e18, miny = 1e18, maxy = -1e18;
  for (var i = 0; i < n; i++) {
    var px = pairs[i].dxfX, py = -pairs[i].dxfY;
    minx = Math.min(minx, px); maxx = Math.max(maxx, px);
    miny = Math.min(miny, py); maxy = Math.max(maxy, py);
  }
  var eps2 = Math.pow(Math.max(maxx - minx, maxy - miny, 1) * 1e-4, 2);
  var W = function (i) {
    var px = pairs[i].dxfX, py = -pairs[i].dxfY;
    return 1 / ((px - x) * (px - x) + (py - y) * (py - y) + eps2);
  };
  var sw = 0, sxw = 0, syw = 0, slaw = 0, slnw = 0;
  for (var j = 0; j < n; j++) {
    if (skip != null && j === skip) continue;
    var w = W(j);
    sw += w; sxw += w * pairs[j].dxfX; syw += w * (-pairs[j].dxfY);
    slaw += w * pairs[j].satLat; slnw += w * pairs[j].satLng;
  }
  if (sw <= 0) return null;
  var mx = sxw / sw, my = syw / sw, mla = slaw / sw, mln = slnw / sw;
  var nr = 0, ni = 0, den = 0;
  for (var k2 = 0; k2 < n; k2++) {
    if (skip != null && k2 === skip) continue;
    var w2 = W(k2);
    var cx = pairs[k2].dxfX - mx, cy = (-pairs[k2].dxfY) - my;
    var cla = pairs[k2].satLat - mla, cln = pairs[k2].satLng - mln;
    nr += w2 * (cx * cla + cy * cln);
    ni += w2 * (cy * cla - cx * cln);
    den += w2 * (cx * cx + cy * cy);
  }
  if (den < 1e-18) return null;
  var a = nr / den, b = ni / den, dx = x - mx, dy = y - my;
  return [a * dx + b * dy + mla, -b * dx + a * dy + mln];
}
function pdxfMlsFit(pairs) {
  var n = pairs.length;
  if (n < 2) return null;
  var k = pdxfIsoK(pairs);
  var np = pairs.map(function (p) { return { dxfX: p.dxfX, dxfY: p.dxfY, satLat: p.satLat, satLng: p.satLng * k }; });
  var loo = [];
  for (var i = 0; i < n; i++) {
    var pred = pdxfMlsApply(np, np[i].dxfX, -np[i].dxfY, i);
    if (!pred) { loo.push(null); continue; }
    var dlatm = (pairs[i].satLat - pred[0]) * 111320;
    var dlngm = (pairs[i].satLng - pred[1] / k) * 111320 * Math.cos(pairs[i].satLat / 180 * Math.PI);
    loo.push(Math.hypot(dlatm, dlngm));
  }
  var valid = loo.filter(function (r) { return r != null; });
  var rms = valid.length ? Math.sqrt(valid.reduce(function (s, r) { return s + r * r; }, 0) / valid.length) : null;
  var sim = (n <= 60) ? pdxfCalFitPairs(pairs) : null;
  return { method: 'mls', n: n, loo_m: loo, rms_m: rms,
           sim_rms_m: sim ? sim.rms_m : null };
}

