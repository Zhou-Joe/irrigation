/* Geometry-preserving alignment math, mirroring core/calibration.py similarity.
 * Independent check points are evaluated separately and never enter this fit. */
// 所有拟合都在 (lat, lng·k) 归一空间（k=cos 平均纬度）：经度每度比纬度短
// cos(φ)，原始度空间的等比变换装不下这份各向异性，会折成虚假旋转角，
// 远离标定基线漂移可达百米~公里级。与服务端 core/calibration.py 完全一致。
function pdxfIsoK(pairs) {
  var s = 0;
  for (var i = 0; i < pairs.length; i++) s += pairs[i].satLat;
  return Math.cos((s / pairs.length / 180) * Math.PI);
}
function pdxfCalFitPairs(pairs) {
  var n = pairs.length;
  if (n < 2) return null;
  var k = pdxfIsoK(pairs);
  var mx = 0,
    my = 0,
    mla = 0,
    mln = 0;
  pairs.forEach(function (p) {
    mx += p.dxfX;
    my += -p.dxfY;
    mla += p.satLat;
    mln += p.satLng * k;
  });
  mx /= n;
  my /= n;
  mla /= n;
  mln /= n;
  var nr = 0,
    ni = 0,
    den = 0;
  pairs.forEach(function (p) {
    var x = p.dxfX - mx,
      y = -p.dxfY - my,
      la = p.satLat - mla,
      ln = p.satLng * k - mln;
    nr += x * la + y * ln;
    ni += y * la - x * ln;
    den += x * x + y * y;
  });
  if (den < 1e-12) return null;
  var a = nr / den,
    b = ni / den;
  var c = mla - a * mx - b * my,
    d = mln + b * mx - a * my;
  var residuals = pairs.map(function (p) {
    var pla = a * p.dxfX + b * -p.dxfY + c;
    var pln = (-b * p.dxfX + a * -p.dxfY + d) / k;
    var dlatm = (p.satLat - pla) * 111320;
    var dlngm =
      (p.satLng - pln) * 111320 * Math.cos((p.satLat / 180) * Math.PI);
    return Math.hypot(dlatm, dlngm);
  });
  var rms = Math.sqrt(
    residuals.reduce(function (s, r) {
      return s + r * r;
    }, 0) / n,
  );
  return {
    a: a,
    b: b,
    c: c,
    d: d,
    iso_k: k,
    scale: Math.hypot(a, b),
    rotation_deg: (Math.atan2(-b, a) * 180) / Math.PI,
    residuals_m: residuals,
    rms_m: rms,
    n: n,
  };
}

// 单点残差（米）：给定拟合系数算某配对点的偏差 — 验证点用。
// 反归一化必须用拟合时的 k（fit.iso_k）：经度绝对值 ~121.6°，用别的 k
// （如验证点自身纬度的 cos）等于给预测经度乘上 k_fit/k_p，每米纬向
// 偏移放大出 ~1.1m 假残差。老 fit 对象无 iso_k 时退回单点估计（仅兜底）。
function pdxfCalResidualOf(fit, p) {
  var k = fit.iso_k != null ? fit.iso_k : pdxfIsoK([p]);
  var pla = fit.a * p.dxfX + fit.b * -p.dxfY + fit.c;
  var pln = (-fit.b * p.dxfX + fit.a * -p.dxfY + fit.d) / k;
  var dlatm = (p.satLat - pla) * 111320;
  var dlngm = (p.satLng - pln) * 111320 * Math.cos((p.satLat / 180) * Math.PI);
  return Math.hypot(dlatm, dlngm);
}

// Preview projection and coarse adjustment never mutate original CAD coordinates.
function pdxfProjectPoint(fit, point) {
  if (!fit) return null;
  var lat = fit.a * point.dxf_x - fit.b * point.dxf_y + fit.c;
  var lng = (-fit.b * point.dxf_x - fit.a * point.dxf_y + fit.d) / fit.iso_k;
  return Number.isFinite(lat) &&
    Number.isFinite(lng) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lng) <= 180
    ? [lat, lng]
    : null;
}
function pdxfMoveFit(fit, point, latlng) {
  return Object.assign({}, fit, {
    c: latlng[0] - fit.a * point.dxf_x + fit.b * point.dxf_y,
    d: latlng[1] * fit.iso_k + fit.b * point.dxf_x + fit.a * point.dxf_y,
  });
}
function pdxfAdjustFit(fit, center, degrees, factor) {
  var anchor = pdxfProjectPoint(fit, center);
  if (!anchor) return null;
  var angle = (degrees * Math.PI) / 180;
  var changed = Object.assign({}, fit, {
    a: factor * (fit.a * Math.cos(angle) - fit.b * Math.sin(angle)),
    b: factor * (fit.a * Math.sin(angle) + fit.b * Math.cos(angle)),
    scale: fit.scale * factor,
  });
  return pdxfMoveFit(changed, center, anchor);
}
