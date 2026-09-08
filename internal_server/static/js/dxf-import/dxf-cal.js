/* DXF 管线导入 — 由 pipeline_dxf_import.html 内联脚本机械拆出（零逻辑改动）。
 * 页面引导块(window.__DXF__)必须在本文件之前加载。全局函数/变量共享，无模块系统。 */
// ── 📍 比例校准状态机：选点/对比/保存/应用（依赖 dxf-cal-math.js） ──
function pdxfCalRenderCurrent() {
  var el = document.getElementById('pdxfCalCurrent');
  var i = pdxfCalInfo || {};
  if (!i.n) { el.textContent = '当前无生效标定（导入将不可用）。'; return; }
  var src = i.source === 'db' ? '用户标定' : '系统默认两点';
  var method = i.method === 'tps' ? ' TPS 橡皮筋' : i.method === 'mls' ? ' MLS 边界稳定' : '';
  var multi = i.method === 'tps' || i.method === 'mls';
  el.innerHTML = '当前标定：<b>' + src + method + ' · ' + i.n + ' 点</b>' +
    (multi && i.rms_m != null ? ' · 留一 RMS ' + i.rms_m.toFixed(2) + 'm' +
      (i.sim_rms_m != null ? '（等比 ' + i.sim_rms_m.toFixed(2) + 'm）' : '') : '') +
    (!multi && i.rotation_deg != null ? ' · 旋转 ' + i.rotation_deg.toFixed(3) + '°' : '') +
    (!multi && i.rms_m != null ? ' · RMS ' + i.rms_m.toFixed(2) + 'm' : '') +
    // 短基线警示：2 点标定的基线（点间距）远小于园区尺度时，锚点上的微小
    // 选点误差会被放大百倍。默认两点仅 ~29 m，是最危险的形态。
    (i.spread_m != null && i.n === 2 && i.spread_m < 500
      ? ' <span style="color:#c0392b;">⚠ 标定基线仅 ' + Math.round(i.spread_m) +
        ' m——远离基线的区域误差会放大，建议 ≥3 组点均匀撒满园区</span>' : '') +
    // 一键清空已存点：换新图纸时旧点的本地坐标对新图毫无意义（累计选点
    // 是为同一坐标系的多张图纸设计的），点这里回到干净起点重新校准。
    (i.source === 'db'
      ? ' <button type="button" onclick="pdxfCalClearSaved()" title="删除全部历史标定点，重新校准前用" ' +
        'style="margin-left:6px;padding:1px 8px;font-size:.72rem;border:1px solid #c8d6cd;' +
        'border-radius:10px;background:#fff;color:#b3261e;cursor:pointer;">🗑 清空已存点</button>'
      : '');
  document.getElementById('pdxfCalBadge').textContent = src + method;
}
pdxfCalRenderCurrent();

function pdxfCalStatusMsg(msg, isErr) {
  var el = document.getElementById('pdxfCalStatus');
  el.innerHTML = isErr ? '<span style="color:#c0392b;">' + pdxfEsc(msg) + '</span>' : pdxfEsc(msg);
}

// DXF 侧吸附候选：预览里的全部顶点 + 阀门点（lat/lng），首次使用时收集。
// 未上传图纸（无预览）时退回**已入库管道**——已导入的管线/阀门同样可以
// 作为校准取点对象，免重新上传取点。
function pdxfCalSnapCandidates() {
  if (pdxfCal.snapPts) return pdxfCal.snapPts;
  var pts = [];
  var pv = (pdxfData && pdxfData.preview) || {};
  (pv.layers || []).forEach(function (l) {
    (l.paths || []).forEach(function (path) {
      for (var k = 0; k < path.length && pts.length < 30000; k++) pts.push(path[k]);
    });
  });
  (pv.valves || []).forEach(function (v) { if (pts.length < 30000) pts.push(v); });
  if (!pts.length && window.pdxfEdit) {
    // 已入库数据：line_points/point 兼容 {lat,lng} 与 [lat,lng] 两种格式
    (pdxfEdit.pipelines || []).forEach(function (p) {
      (p.line_points || []).forEach(function (pt) {
        if (pts.length < 30000) {
          if (pt && typeof pt.lat === 'number') pts.push({ lat: pt.lat, lng: pt.lng });
          else if (pt && pt.length >= 2) pts.push({ lat: pt[0], lng: pt[1] });
        }
      });
    });
    (pdxfEdit.valves || []).forEach(function (v) {
      if (pts.length < 30000 && v.point) {
        if (typeof v.point.lat === 'number') pts.push({ lat: v.point.lat, lng: v.point.lng });
        else if (v.point.length >= 2) pts.push({ lat: v.point[0], lng: v.point[1] });
      }
    });
    pdxfCal.fromDb = true;
  }
  pdxfCal.snapPts = pts;
  return pts;
}

// 地图点击 → 25px 内最近的 DXF 预览点，附带其本地（原始 DXF）坐标。
function pdxfCalSnapDxf(ll) {
  var inv = pdxfCalInfo && pdxfCalInfo.inverse;
  if (!inv) { pdxfCalStatusMsg('当前标定不可逆（退化），无法吸附 DXF 点', true); return null; }
  var cand = pdxfCalSnapCandidates();
  var clickPt = pdxfMap.latLngToLayerPoint(ll);
  var best = null, bestDist = 25;   // px
  for (var i = 0; i < cand.length; i++) {
    var p = cand[i];
    var d = pdxfMap.latLngToLayerPoint([p.lat, p.lng]).distanceTo(clickPt);
    if (d < bestDist) { bestDist = d; best = p; }
  }
  if (!best) return null;
  // 逆变换回本地坐标（negY 空间）→ 原始 DXF（y 取反）。
  // TPS：反向系数 ((lat,lng·k)→(x, yNeg)) 核函数求值；相似：线性系数。
  // 逆系数/点对都活在 (lat, lng·k) 归一空间——输入经度先乘 iso_k
  // （与服务端 fit_calibration_inverse 一致；老载荷无 iso_k 时按 1 兜底）。
  var x, yNeg, lk = best.lng * ((inv.iso_k != null) ? inv.iso_k : 1);
  if (inv.type === 'tps') {
    var r = pdxfTpsApply(inv.coeffs, best.lat, lk);
    x = r[0]; yNeg = r[1];
  } else if (inv.type === 'mls') {
    // MLS 逆变换：点对直接加权求值（points 的经度已是归一值）
    var mp = inv.points.map(function (p) {
      return { dxfX: p[0], dxfY: -p[1], satLat: p[2], satLng: p[3] };
    });
    var mr = pdxfMlsApply(mp, best.lat, lk, null);
    if (!mr) return null;
    x = mr[0]; yNeg = mr[1];
  } else {
    x = inv.ia * best.lat + inv.ib * lk + inv.ic;
    yNeg = -inv.ib * best.lat + inv.ia * lk + inv.id;
  }
  return { lat: best.lat, lng: best.lng, dxfX: x, dxfY: -yNeg };
}

function pdxfCalStart() {
  if (!pdxfData || !pdxfToken) {
    // 未上传图纸：拉取已入库管道作为 DXF 侧取点对象（继续校准免重传重取点）
    if (window.pdxfEdit) { pdxfCalStartBody(); return; }
    pdxfCalStatusMsg('未上传图纸——加载已入库管道作为取点对象…');
    fetch(window.__DXF__.urls.editData, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.success || !((d.pipelines || []).length)) {
          pdxfCalStatusMsg('请先在①上传解析 DXF 图纸（或先完成一次导入）', true);
          return;
        }
        window.pdxfEdit = d;
        pdxfCalStartBody();
      })
      .catch(function () { pdxfCalStatusMsg('加载已入库管道失败，请上传 DXF 图纸', true); });
    return;
  }
  pdxfCalStartBody();
}
function pdxfCalStartBody() {
  // 整体微调的平移偏移会叠加在预览坐标上，而校准吸附/标记用原始坐标——
  // 进入校准前归零并重绘，两边才对得上（校准的最小二乘本身含平移，不损失）。
  if (pdxfOffset.dLat !== 0 || pdxfOffset.dLng !== 0) {
    pdxfOffset = { dLat: 0, dLng: 0 };
    pdxfUpdateAdjustHint();
    pdxfRefreshMap();
    pdxfCal.snapPts = null;   // 吸附候选按无偏移预览重建
  }
  pdxfCal.on = true; pdxfCal.phase = 'dxf'; pdxfCal.idx = 0; pdxfCal.pairs = []; pdxfCal.pending = null;
  pdxfCalLockMode(true);
  pdxfCal._fit = null;        // 清掉上一轮拟合残差，避免表格显示陈旧数值
  pdxfCal._valRes = null;     // 验证点偏差同样清零
  pdxfCal.snapPts = null;     // 吸附候选总是按当前预览重建
  pdxfCal.fromDb = false;     // 吸附来源：预览（有上传）或已入库管道（无上传）
  // 累计选点：预载当前生效标定的点——新一轮选点在旧点之上继续累加，
  // 保存时旧点+新点一起拟合（跨页面刷新/跨天也累计；不想要的旧点可在
  // 表格里删除）。否则第二次进页面选点保存会把上一批点整体替换掉。
  if (pdxfCalInfo && pdxfCalInfo.points && pdxfCalInfo.points.length >= 2) {
    pdxfCalInfo.points.forEach(function (p) {
      pdxfCal.pairs.push({
        dxfX: parseFloat(p.dxf_x), dxfY: parseFloat(p.dxf_y),
        dxfLat: parseFloat(p.lat), dxfLng: parseFloat(p.lng),
        satLat: parseFloat(p.lat), satLng: parseFloat(p.lng),
        seeded: true,
      });
    });
    pdxfCal.idx = pdxfCal.pairs.length;
  }
  if (pdxfCal.markers && pdxfMap.hasLayer(pdxfCal.markers)) pdxfMap.removeLayer(pdxfCal.markers);
  pdxfCal.markers = L.layerGroup().addTo(pdxfMap);
  // 已保存的点画绿色 ✓（它们在当前标定下已经重合），新选的点照常蓝/红
  pdxfCal.pairs.forEach(function (p, k) {
    if (p.seeded) {
      L.circleMarker([p.satLat, p.satLng], { radius: 8, color: '#2D6A4F', weight: 2, fillOpacity: 0 })
        .addTo(pdxfCal.markers).bindTooltip((k + 1) + ' ✓ 已保存');
    }
  });
  pdxfCal.prevPoints = (pdxfCalInfo && pdxfCalInfo.points) ? JSON.parse(JSON.stringify(pdxfCalInfo.points)) : null;
  // 恢复上次标定时要沿用当时的引擎——否则当前单选若停在别的模式，
  // 会把旧 TPS/MLS 点集按 'sim' 存库、悄悄换了拟合方法
  pdxfCal.prevMethod = (pdxfCalInfo && pdxfCalInfo.method === 'tps') ? 'tps'
    : (pdxfCalInfo && pdxfCalInfo.method === 'mls') ? 'mls' : 'sim';
  if (pdxfEditMode) pdxfToggleEditMode();   // 互斥
  if (pdxfAdjustOn) pdxfToggleAdjust();     // 互斥
  pdxfMap.getContainer().style.cursor = 'crosshair';
  pdxfMap.on('click', pdxfCalOnClick);
  document.getElementById('pdxfCalStartBtn').style.display = 'none';
  document.getElementById('pdxfCalStopBtn').style.display = '';
  // 累积选点预载的旧点可能已 ≥4 组——✓ 按钮可见性按当前点数重算，
  // 不能硬编码隐藏（否则只能靠加/删点触发重算，"完成选点"永远出不来）
  pdxfCalUpdateDoneBtn();
  document.getElementById('pdxfCalTable').style.display = '';
  document.getElementById('pdxfCalActions').style.display = 'none';
  pdxfCalStepMsg();
  pdxfCalRenderPairs();
  // 无图纸、在已入库管线上取点：库线活在「最近应用过的标定」下。当前
  // 生效标定若还没应用，用它反算取点坐标会算错——先提示去应用。
  // （source 非 db 时无标定可应用，不提示）
  if (!pdxfToken && pdxfCalInfo && pdxfCalInfo.source === 'db' && !pdxfCalInfo.applied_at) {
    pdxfCalStatusMsg('⚠ 当前标定尚未「应用到已保存的管道」——已入库管道仍活在上一标定下，'
                   + '现在在管线上取点的 DXF 坐标会算偏。请先应用当前标定，或上传 DXF 图纸校准。', true);
  } else {
    pdxfCalStatusMsg('');
  }
}

// tps/mls 都是多点模式（≥4 后可"完成选点"，上限 300）
function pdxfCalMulti() { var m = pdxfCalMode(); return m === 'tps' || m === 'mls'; }
// 当前模式的选点目标：多点模式 300 组，其余 3 组。
function pdxfCalTarget() { return pdxfCalMulti() ? 300 : 3; }
function pdxfCalUpdateDoneBtn() {
  var b = document.getElementById('pdxfCalDoneBtn');
  if (!b) return;
  b.style.display = (pdxfCal.on && pdxfCalMulti() && pdxfCal.pairs.length >= 4 &&
                     pdxfCal.phase !== 'done') ? '' : 'none';
}
// TPS 模式提前结束选点（≥4 组后可见）
function pdxfCalFinishPick() {
  if (pdxfCal.pairs.length < 4) return;
  pdxfCal.phase = 'done';
  pdxfMap.off('click', pdxfCalOnClick);
  // 选点完成 = 只读的拟合/对比/保存阶段：解锁算法单选，直接切换
  // TPS↔MLS 即可对比同一点集在两个引擎下的拟合结果，不必退出校准
  pdxfCalLockMode(false);
  pdxfCalUpdateDoneBtn();
  pdxfCalFitShow();
}
// 保存/完成选点后继续往现有配对上加点（不清空已选的点）
function pdxfCalResumePick() {
  if (pdxfCal.pairs.length >= pdxfCalTarget()) return;
  pdxfCal.on = true;
  pdxfCal.phase = 'dxf';
  pdxfCal.idx = pdxfCal.pairs.length;
  pdxfCal.pending = null;
  pdxfCalLockMode(true);   // 重新进入选点：锁单选（保存引擎 = 保存那一刻的选择）
  document.getElementById('pdxfCalStopBtn').style.display = '';
  document.getElementById('pdxfCalStartBtn').style.display = 'none';
  pdxfMap.getContainer().style.cursor = 'crosshair';
  pdxfMap.on('click', pdxfCalOnClick);
  pdxfCalUpdateDoneBtn();
  document.getElementById('pdxfCalMoreBtn').style.display = 'none';
  document.getElementById('pdxfCalActions').style.display = 'none';
  pdxfCalStepMsg();
}
// 「➕ 继续加点」按钮可见性：选点完成/保存后且未达上限时显示
function pdxfCalUpdateMoreBtn() {
  var b = document.getElementById('pdxfCalMoreBtn');
  if (!b) return;
  b.style.display = (pdxfCal.phase === 'done' && pdxfCal.on !== false &&
                     pdxfCal.pairs.length < pdxfCalTarget()) ? '' : 'none';
}
// 清空已存匹配点（服务端删除全部 SiteCalibration 历史）：换新图纸的本地
// 坐标系与旧点不匹配时一键回到干净起点。已入库水管不受影响（坐标已定），
// 清空后标定回落到系统默认两点，需重新选点保存才能再导入。
function pdxfCalClearSaved() {
  var i = pdxfCalInfo || {};
  if (i.source !== 'db' || !i.n) return;
  if (!confirm('清空已存的 ' + i.n + ' 个匹配点（含全部历史标定记录）？\n' +
      '已导入的水管不受影响；清空后需重新解析图纸、重新选点校准。')) return;
  if (pdxfCal.on) pdxfCalStop();          // 校准会话里的旧种子点一并作废
  var fd = new FormData();
  fetch(window.__DXF__.urls.calClear, {
    method: 'POST',
    headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
    body: fd,
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.success) { pdxfCalStatusMsg(d.error || '清空失败', true); return; }
    pdxfCalInfo = d.calibration;          // 回落系统默认两点（含逆变换系数）
    pdxfCal.pairs = []; pdxfCal.idx = 0; pdxfCal._fit = null; pdxfCal._valRes = null;
    document.getElementById('pdxfCalTable').style.display = 'none';
    document.getElementById('pdxfCalFit').innerHTML = '';
    pdxfCalRenderCurrent();
    pdxfCalStatusMsg(d.message || '已清空');
  }).catch(function () { pdxfCalStatusMsg('网络错误', true); });
}

function pdxfCalStop() {
  pdxfCal.on = false;
  pdxfCalLockMode(false);
  pdxfMap.off('click', pdxfCalOnClick);
  pdxfMap.getContainer().style.cursor = '';
  if (pdxfCal.markers && pdxfMap.hasLayer(pdxfCal.markers)) pdxfMap.removeLayer(pdxfCal.markers);
  pdxfCal.markers = null;
  document.getElementById('pdxfCalStartBtn').style.display = '';
  document.getElementById('pdxfCalStopBtn').style.display = 'none';
  document.getElementById('pdxfCalDoneBtn').style.display = 'none';
  document.getElementById('pdxfCalMoreBtn').style.display = 'none';
  document.getElementById('pdxfCalStep').textContent = '';
  if (!pdxfCal.pairs.length) {
    document.getElementById('pdxfCalTable').style.display = 'none';
    document.getElementById('pdxfCalFit').innerHTML = '';
  }
}
function pdxfCalStepMsg() {
  var el = document.getElementById('pdxfCalStep');
  if (!pdxfCal.on) { el.textContent = ''; return; }
  if (pdxfCal.phase === 'dxf') {
    var role = (pdxfCalMode() === 'exact2' && pdxfCal.idx === 2) ? '【验证点】' : '';
    var extra = (pdxfCalMulti() && pdxfCal.pairs.length >= 4)
      ? '（已够 ' + pdxfCal.pairs.length + ' 组，可点「✓ 完成选点」，也可继续加到 300 组更准）' : '';
    var obj = pdxfCal.fromDb ? '已入库管道上的一个点' : 'DXF 图上的一个管点';
    el.textContent = '第 ' + (pdxfCal.idx + 1) + ' 组 ' + role + '：点击 ' + obj + '（附近自动吸附）' + extra;
  }
  else if (pdxfCal.phase === 'sat') el.textContent = '第 ' + (pdxfCal.idx + 1) + ' 组：点击卫星图上的对应位置';
  else el.textContent = '';
}

function pdxfCalOnClick(e) {
  if (!pdxfCal.on) return;
  if (pdxfCal.phase === 'dxf') {
    var snap = pdxfCalSnapDxf(e.latlng);
    if (!snap) { pdxfCalStatusMsg('点击位置 25px 内没有 DXF 管点，请靠近管道线/阀门再点', true); return; }
    pdxfCal.pending = snap;
    L.circleMarker([snap.lat, snap.lng], { radius: 8, color: '#1d4ed8', weight: 2, fillOpacity: 0.9 })
      .addTo(pdxfCal.markers).bindTooltip('DXF ' + (pdxfCal.idx + 1));
    pdxfCal.phase = 'sat';
  } else if (pdxfCal.phase === 'sat') {
    var p = pdxfCal.pending;
    if (!p) { pdxfCal.phase = 'dxf'; pdxfCalStepMsg(); return; }
    pdxfCal.pairs.push({ dxfX: p.dxfX, dxfY: p.dxfY, dxfLat: p.lat, dxfLng: p.lng,
                         satLat: e.latlng.lat, satLng: e.latlng.lng });
    L.circleMarker([e.latlng.lat, e.latlng.lng], { radius: 6, color: '#dc2626', weight: 2, fillOpacity: 0.9 })
      .addTo(pdxfCal.markers).bindTooltip('卫星 ' + (pdxfCal.idx + 1));
    L.polyline([[p.lat, p.lng], [e.latlng.lat, e.latlng.lng]],
               { color: '#dc2626', weight: 1.5, dashArray: '4 4', opacity: 0.7 }).addTo(pdxfCal.markers);
    pdxfCal.idx += 1;
    pdxfCal.pending = null;
    pdxfCal.phase = pdxfCal.idx < pdxfCalTarget() ? 'dxf' : 'done';
    pdxfCalUpdateDoneBtn();
    // 三点模式选满自动完成：同样进入"只读对比"阶段，解锁单选可切引擎对比
    if (pdxfCal.phase === 'done') {
      pdxfMap.off('click', pdxfCalOnClick);
      pdxfCalLockMode(false);
      pdxfCalFitShow();
    }
  }
  pdxfCalStepMsg();
  pdxfCalRenderPairs();
}

function pdxfCalDropPair(i) {
  pdxfCal.pairs.splice(i, 1);
  pdxfCal.idx = pdxfCal.pairs.length;
  pdxfCal.phase = pdxfCal.idx < pdxfCalTarget() ? 'dxf' : 'done';
  if (pdxfCal.phase !== 'done' && pdxfCal.on) pdxfMap.on('click', pdxfCalOnClick);
  if (pdxfCal.phase === 'dxf' && pdxfCal.on) pdxfCalLockMode(true);   // 回到选点态：重新锁单选
  pdxfCalUpdateDoneBtn();
  if (!pdxfCal.on) { pdxfCalRenderPairs(); return; }   // 已退出校准：不再重建标记（避免复活的点）
  // 标记重建（比按索引删 marker 简单且不易错位）
  if (pdxfCal.markers && pdxfMap.hasLayer(pdxfCal.markers)) pdxfMap.removeLayer(pdxfCal.markers);
  pdxfCal.markers = L.layerGroup().addTo(pdxfMap);
  pdxfCal.pairs.forEach(function (p, k) {
    L.circleMarker([p.dxfLat, p.dxfLng], { radius: 8, color: '#1d4ed8', weight: 2, fillOpacity: 0.9 })
      .addTo(pdxfCal.markers).bindTooltip('DXF ' + (k + 1));
    L.circleMarker([p.satLat, p.satLng], { radius: 6, color: '#dc2626', weight: 2, fillOpacity: 0.9 })
      .addTo(pdxfCal.markers).bindTooltip('卫星 ' + (k + 1));
    L.polyline([[p.dxfLat, p.dxfLng], [p.satLat, p.satLng]],
               { color: '#dc2626', weight: 1.5, dashArray: '4 4', opacity: 0.7 }).addTo(pdxfCal.markers);
  });
  pdxfCalRenderPairs();
  if (pdxfCal.phase === 'done') pdxfCalFitShow(); else { pdxfCal._fit = null; document.getElementById('pdxfCalFit').innerHTML = ''; }
}

function pdxfCalMode() {
  var el = document.querySelector('input[name="pdxfCalMode"]:checked');
  return el ? el.value : 'ls3';
}
function pdxfCalModeChanged() {
  if (pdxfCal.phase === 'done') pdxfCalFitShow(); else pdxfCalRenderPairs();
}
// 选点会话期间锁定算法单选——中途切换会让"这组点按哪个引擎解释"变得
// 不可预测（保存用的引擎 = 保存那一刻的单选），要换引擎先退出再重进。
function pdxfCalLockMode(lock) {
  document.querySelectorAll('input[name="pdxfCalMode"]').forEach(function (r) {
    r.disabled = !!lock;
  });
}

function pdxfCalRenderPairs() {
  var mode = pdxfCalMode();
  var fit = pdxfCal._fit;
  var valRes = pdxfCal._valRes;
  var tb = document.getElementById('pdxfCalPairBody');
  tb.innerHTML = pdxfCal.pairs.map(function (p, i) {
    var role, res;
    if (mode === 'exact2') {
      if (i < 2) { role = '锚点'; res = '0（锚点）'; }
      else { role = '验证'; res = (valRes != null) ? '<b style="color:' + (valRes > 1 ? '#c0392b' : '#2D6A4F') + '">' + valRes.toFixed(2) + ' m</b>' : '—'; }
    } else if (mode === 'tps' || mode === 'mls') {
      role = '控制点';
      // TPS/MLS 控制点精确落位——展示留一交叉验证：拿掉这个点、用其余点
      // 重拟合后预测它，偏差即该点的"独立可信度"。
      res = (fit && fit.loo_m && fit.loo_m[i] != null)
        ? '<span style="color:' + (fit.loo_m[i] > 1 ? '#c0392b' : '#2D6A4F') + '">' + fit.loo_m[i].toFixed(2) + ' m</span>' : '—';
    } else {
      role = '';
      res = (fit && fit.residuals_m[i] != null) ? fit.residuals_m[i].toFixed(2) + ' m' : '—';
    }
    if (p.seeded) role = role ? role + '·已存' : '已存';
    return '<tr><td>' + (i + 1) + (role ? '<div style="font-size:.66rem;color:#8aa093;">' + role + '</div>' : '') + '</td>' +
      '<td style="font-family:monospace;font-size:.72rem;">(' + p.dxfX.toFixed(1) + ', ' + p.dxfY.toFixed(1) + ')</td>' +
      '<td style="font-family:monospace;font-size:.72rem;">(' + p.satLat.toFixed(6) + ', ' + p.satLng.toFixed(6) + ')</td>' +
      '<td>' + res + '</td>' +
      '<td><button type="button" class="pdxf-btn" style="padding:2px 8px;font-size:.72rem;" onclick="pdxfCalDropPair(' + i + ')">删除</button></td></tr>';
  }).join('');
}

// 与服务端 similarity_transform_ls 相同的最小二乘（negY 空间拟合）。
function pdxfCalFitShow() {
  var mode = pdxfCalMode();
  pdxfCal._valRes = null;
  // 两点精确模式：只用前两组配对拟合（完全重合）；第三组独立验证。
  if (mode === 'tps' || mode === 'mls') {
    var tfit = (mode === 'mls') ? pdxfMlsFit(pdxfCal.pairs) : pdxfTpsFit(pdxfCal.pairs);
    pdxfCal._fit = tfit;
    var tel = document.getElementById('pdxfCalFit');
    var tactions = document.getElementById('pdxfCalActions');
    if (!tfit) {
      tel.innerHTML = '<span style="color:#c0392b;">' + (mode === 'mls' ? 'MLS' : 'TPS') +
        ' 需 ≥4 组不重复的点（当前 ' + pdxfCal.pairs.length + ' 组）</span>';
      tactions.style.display = 'none'; pdxfCalRenderPairs(); return;
    }
    var mname = mode === 'mls' ? 'MLS 边界稳定' : 'TPS 橡皮筋';
    var tpsHtml = '<b>拟合结果（' + mname + ' · ' + tfit.n + ' 点）：</b>' +
      ' 留一交叉验证 RMS <b style="color:' + (tfit.rms_m > 1 ? '#c0392b' : '#2D6A4F') + '">' +
      tfit.rms_m.toFixed(2) + ' m</b>' +
      (tfit.sim_rms_m != null ? '（同点数等比变换 RMS ' + tfit.sim_rms_m.toFixed(2) + ' m' +
        (tfit.sim_rms_m > tfit.rms_m * 1.3 ? '，局部变形明显更贴合' : '') + '）' : '') +
      (mode === 'mls' ? ' · 控制点近似精确落位 · 边缘/稀疏区外推稳定' : ' · 控制点精确落位') +
      (tfit.rms_m > 1 ? '<span style="color:#c0392b;">（偏大：LOO 残差最大的点可能选偏，删掉重选）</span>' : '') +
      (mode === 'tps' ? '<div style="font-size:.72rem;color:#8aa093;margin-top:2px;">提示：点要撒满园区范围，范围外区域会外推不准。</div>'
                      : '<div style="font-size:.72rem;color:#8aa093;margin-top:2px;">MLS：每个点只受附近控制点影响，覆盖区外自动退化为整体变换，不发散。</div>');
    tel.innerHTML = tpsHtml;
    tactions.style.display = 'flex';
    document.getElementById('pdxfCalRevertBtn').style.display = 'none';
    pdxfCalUpdateMoreBtn();
    pdxfCalRenderPairs();
    return;
  }
  var fitPairs = (mode === 'exact2') ? pdxfCal.pairs.slice(0, 2) : pdxfCal.pairs;
  var fit = pdxfCalFitPairs(fitPairs);
  pdxfCal._fit = fit;
  if (fit && mode === 'exact2' && pdxfCal.pairs.length >= 3) {
    pdxfCal._valRes = pdxfCalResidualOf(fit, pdxfCal.pairs[2]);
  }
  var el = document.getElementById('pdxfCalFit');
  var actions = document.getElementById('pdxfCalActions');
  if (!fit) { el.innerHTML = '<span style="color:#c0392b;">点数不足或退化，无法拟合</span>'; actions.style.display = 'none'; pdxfCalRenderPairs(); return; }
  var oldScale = (pdxfCalInfo && pdxfCalInfo.scale) || null;
  var scalePct = oldScale ? ((fit.scale / oldScale - 1) * 100) : null;
  var oldRot = (pdxfCalInfo && pdxfCalInfo.rotation_deg != null) ? pdxfCalInfo.rotation_deg : null;
  var rotDiff = oldRot != null ? fit.rotation_deg - oldRot : null;
  var html = '<b>拟合结果（' + (mode === 'exact2' ? '两点精确' : '三点最小二乘') + '）：</b> 比例' +
    (scalePct != null ?
      ' <b style="color:' + (Math.abs(scalePct) > 0.5 ? '#c0392b' : '#2D6A4F') + '">' +
      (scalePct >= 0 ? '+' : '') + scalePct.toFixed(2) + '%</b>' : ' —') +
    ' · 旋转' + (rotDiff != null ? ' <b>' + (rotDiff >= 0 ? '+' : '') + rotDiff.toFixed(3) + '°</b>' : ' —');
  if (mode === 'exact2') {
    html += ' · <b>两锚点完全重合</b>';
    if (pdxfCal._valRes != null) {
      html += ' · 验证点偏差 <b style="color:' + (pdxfCal._valRes > 1 ? '#c0392b' : '#2D6A4F') + '">' +
              pdxfCal._valRes.toFixed(2) + ' m</b>' +
              (pdxfCal._valRes > 1 ? '<span style="color:#c0392b;">（偏大：图纸局部变形或某锚点选偏，可换三点最小二乘摊薄）</span>'
                                    : '<span style="color:#2D6A4F;">（良好）</span>');
    } else {
      html += ' · <span style="color:#8a7a55;">未选验证点</span>';
    }
  } else {
    html += ' · RMS <b>' + fit.rms_m.toFixed(2) + ' m</b>' +
      (fit.rms_m > 1 ? '<span style="color:#c0392b;">（偏大，建议删除残差最大的点重选）</span>' : '');
  }
  el.innerHTML = html;
  actions.style.display = 'flex';
  document.getElementById('pdxfCalRevertBtn').style.display = 'none';   // 保存后才可恢复
  pdxfCalUpdateMoreBtn();
  pdxfCalRenderPairs();
}

function pdxfCalSave(pairsOverride, methodOverride) {
  var pairs = pairsOverride || pdxfCal.pairs;
  var mode = pdxfCalMode();
  var minPts = pdxfCalMulti() ? 4 : 2;
  if (!pairs || pairs.length < minPts) { pdxfCalStatusMsg((pdxfCalMulti() ? '该模式至少需要 4 组点' : '至少需要 2 组点'), true); return; }
  // 两点精确模式只保存两个锚点（服务端对 2 点的 LS 即精确解）；验证点不入库。
  var toSave = (mode === 'exact2' && !pairsOverride && pairs.length >= 3) ? pairs.slice(0, 2) : pairs;
  var btn = document.getElementById('pdxfCalSaveBtn');
  btn.disabled = true; btn.textContent = '保存中…';
  var fd = new FormData();
  fd.append('pairs', JSON.stringify(toSave.map(function (p) {
    return { dxf_x: p.dxfX, dxf_y: p.dxfY, lat: p.satLat, lng: p.satLng };
  })));
  // ls3/exact2 显式传 'sim'：累积选点常带着 ≥4 组旧点，传 ''(自动)会被
  // 服务端按点数升级成 TPS——用户在 UI 上选的明明是"三点最小二乘"。
  // methodOverride：「恢复上次标定」用它沿用当时的引擎，不随当前单选漂移。
  fd.append('method', methodOverride || (mode === 'tps' || mode === 'mls' ? mode : 'sim'));
  fd.append('note', (mode === 'exact2' ? '两点精确' : mode === 'tps' ? ('TPS ' + toSave.length + '点')
    : mode === 'mls' ? ('MLS ' + toSave.length + '点') : '三点最小二乘') + '校准 ' + new Date().toLocaleString());
  fetch(window.__DXF__.urls.calSave, {
    method: 'POST',
    headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
    body: fd,
  }).then(function (r) { return r.json(); }).then(function (d) {
    btn.disabled = false; btn.textContent = '保存并刷新预览';
    if (!d.success) { pdxfCalStatusMsg(d.error || '保存失败', true); return; }
    // 无 token（基于已入库管道取点）：没有预览可刷新——已入库坐标要靠
    // 「应用到已保存的管道」按新标定重算。
    if (!pdxfToken) {
      pdxfCalInfo = d.calibration;
      pdxfCalRenderCurrent();
      if (pdxfCal.markers && pdxfMap.hasLayer(pdxfCal.markers)) pdxfMap.removeLayer(pdxfCal.markers);
      pdxfCal.markers = L.layerGroup().addTo(pdxfMap);
      pdxfCal.pairs.forEach(function (p, k) {
        L.circleMarker([p.satLat, p.satLng], { radius: 9, color: '#2D6A4F', weight: 2, fillOpacity: 0 })
          .addTo(pdxfCal.markers).bindTooltip((k + 1) + ' ✓');
      });
      pdxfCalStatusMsg('新标定已保存。已入库的管道坐标不会自动移动——点「应用到已保存的管道…」按新标定重算（会先自动备份）。');
      document.getElementById('pdxfCalApplyBtn').style.display = '';
      pdxfCalUpdateMoreBtn();
      return;
    }
    // token 重建预览（免重传）；成功后才替换 pdxfCalInfo——否则会出现
    // 新系数配旧预览，下轮校准的逆映射悄悄算错。
    var fd2 = new FormData();
    fd2.append('token', pdxfToken);
    return fetch(window.__DXF__.urls.analyze, {
      method: 'POST',
      headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
      body: fd2,
    }).then(function (r) { return r.json(); }).then(function (d2) {
      if (d2.success) {
        pdxfCalInfo = d.calibration;
        pdxfCalRenderCurrent();
        pdxfData = d2;
        pdxfOffset = { dLat: 0, dLng: 0 };   // 重新校准后从零偏移开始
        pdxfCal.snapPts = null;              // 吸附候选按新预览重建
        pdxfRefreshMap();
        // 旧选点标记（蓝点/虚线在标定前的位置）必须重建——管线已按新标定
        // 精确移到卫星点上，旧标记留着会显得"没对齐"。重画为绿色 ✓ 标记
        // 表达"控制点已重合"。
        if (pdxfCal.markers && pdxfMap.hasLayer(pdxfCal.markers)) pdxfMap.removeLayer(pdxfCal.markers);
        pdxfCal.markers = L.layerGroup().addTo(pdxfMap);
        pdxfCal.pairs.forEach(function (p, k) {
          L.circleMarker([p.satLat, p.satLng], { radius: 9, color: '#2D6A4F', weight: 2, fillOpacity: 0 })
            .addTo(pdxfCal.markers).bindTooltip((k + 1) + ' ✓ 已重合');
        });
        var loo = (d.calibration && d.calibration.method === 'tps' && d.calibration.rms_m != null)
          ? ' 留一 RMS ' + d.calibration.rms_m.toFixed(2) + 'm（表格里标红的点建议重选）。' : '';
        pdxfCalStatusMsg('新标定已保存，所有控制点已精确落位（图中绿色 ✓）。' + loo +
                         '不满意可「恢复上次标定」或删除残差大的点重选。');
      } else {
        pdxfCalStatusMsg('标定已保存，但预览刷新失败：' + (d2.error || '') +
                         '（请重新上传图纸后再校准）', true);
      }
      document.getElementById('pdxfCalRevertBtn').style.display =
        (pdxfCal.prevPoints && pdxfCal.prevPoints.length >= 2) ? '' : 'none';
      document.getElementById('pdxfCalApplyBtn').style.display = '';
      pdxfCalUpdateMoreBtn();   // 保存后可继续往这组点上加点（不清空）
    });
  }).catch(function () {
    btn.disabled = false; btn.textContent = '保存并刷新预览';
    pdxfCalStatusMsg('网络错误', true);
  });
}

function pdxfCalRevert() {
  if (!pdxfCal.prevPoints || pdxfCal.prevPoints.length < 2) return;
  // 沿用进入校准时的引擎（pdxfCal.prevMethod），不随当前单选漂移
  pdxfCalSave(pdxfCal.prevPoints.map(function (p) {
    return { dxfX: p.dxf_x, dxfY: p.dxf_y, satLat: p.lat, satLng: p.lng };
  }), pdxfCal.prevMethod || undefined);
}

function pdxfCalApplySaved(force) {
  if (!force && !confirm('把新标定追溯应用到数据库里全部已保存的管道/阀门坐标？\n' +
               '· 每批管道按其「导入时的生效标定」分别还原回本地坐标，再按新标定重新换算\n' +
               '· 执行前自动备份全部坐标到服务器 JSON 文件（可回滚）')) return;
  var btn = document.getElementById('pdxfCalApplyBtn');
  btn.disabled = true; btn.textContent = '应用中…';
  var fd = new FormData();
  fd.append('confirm', '1');
  if (force) fd.append('force', '1');
  fetch(window.__DXF__.urls.calApply, {
    method: 'POST',
    headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
    body: fd,
  }).then(function (r) { return r.json(); }).then(function (d) {
    btn.disabled = false; btn.textContent = '应用到已保存的管道…';
    if (!d.success && d.need_force) {
      if (confirm(d.error + '\n\n强制应用将移动全部已存坐标（有备份）。确定继续？')) pdxfCalApplySaved(true);
      return;
    }
    if (!d.success) { pdxfCalStatusMsg(d.error || '应用失败', true); return; }
    if (pdxfCalInfo) pdxfCalInfo.applied_at = new Date().toISOString();   // 防下轮 fromDb 取点误报"未应用"
    var ctrlMsg = (d.ctrl_max_m != null)
      ? ' 控制点核验：最大偏差 <b style="color:' + (d.ctrl_max_m > 0.5 ? '#c0392b' : '#2D6A4F') + '">' +
        d.ctrl_max_m + ' m</b>' +
        (d.ctrl_max_m > 0.5 ? '（有残差：多为标定点间区域的重排，可再保存应用一轮收敛；持续偏大请检查残差红的点）' : '（精确落位 ✓）') + '。'
      : ' ';
    pdxfCalStatusMsg('已重算 ' + d.pipelines + ' 条管道 / ' + d.valves + ' 个阀门' +
      '（比例 ' + (d.scale_change_pct >= 0 ? '+' : '') + d.scale_change_pct + '%，' +
      '旋转 ' + (d.rotation_change_deg >= 0 ? '+' : '') + d.rotation_change_deg + '°）。' +
      ctrlMsg +
      '坐标备份：' + d.backup + '。刷新首页地图即可看到修正后的管线。');
    if (pdxfEditMode) { pdxfToggleEditMode(); pdxfToggleEditMode(); }   // 重载编辑层
    // 应用后库坐标已变：参照层/取点缓存按新坐标重画——否则页面上看
    // 起来"没生效"（还是挪动前的旧图层）。wipePreview=true 顺带撤掉
    // 过时的 DXF 预览层。
    pdxfRefreshRefPipelines(true);
    pdxfCal.snapPts = null;
    window.pdxfEdit = null;
  }).catch(function () {
    btn.disabled = false; btn.textContent = '应用到已保存的管道…';
    pdxfCalStatusMsg('网络错误', true);
  });
}
