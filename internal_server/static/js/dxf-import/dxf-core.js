/* DXF 管线导入 — 由 pipeline_dxf_import.html 内联脚本机械拆出（零逻辑改动）。
 * 页面引导块(window.__DXF__)必须在本文件之前加载。全局函数/变量共享，无模块系统。 */
// ── 基础：全局状态 / 地图初始化 / ①解析 ②映射 ③预览 ④导入 / 整体微调 ──

// ── state ────────────────────────────────────────────────────────────
var pdxfData = null;          // analyze result
var pdxfToken = null;         // analyze 返回的内容 hash（解析缓存）
var pdxfMap = null;
var pdxfLayers = {};          // Leaflet layer groups: preview id → group
var pdxfLegendCtl = null;
var pdxfPreviewPane = null;   // 独立 pane：整组预览元素可一起拖动微调
var pdxfPreviewRenderer = null;
var pdxfOffset = { dLat: 0, dLng: 0 };   // 微调偏移（度），导入时叠加
var pdxfAdjustOn = false;
var pdxfRefLayer = null;        // 常驻参照管线层（独立 group，编辑后可刷新）
var pdxfDbChanged = false;      // 本次预览之后 DB 是否又被改过（决定退出编辑时是否撤掉旧预览层）
var pdxfCalInfo = window.__DXF__.cal;   // 当前生效标定（服务端注入）
var pdxfCal = { on: false, phase: 'dxf', idx: 0, pairs: [], pending: null,
                markers: null, prevPoints: null, snapPts: null };
var pdxfEditMode = false;
var pdxfEdit = null;        // {pipelines, valves, zones} from edit-data endpoint
var pdxfEditLayers = null;  // L.featureGroup of interactive edit layers
var pdxfSelected = null;    // {kind:'pipeline'|'valve', id}
var pdxfDrag = null;
var pdxfColorOf = {};         // layer name → css color (legend + map)
var LAYER_COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#8c564b', '#e377c2', '#17becf', '#bcbd22', '#7f7f7f', '#c49c94', '#98df8a'];
function pdxfEsc(t) {
  return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
var VALVE_LABELS = { solenoid: '电磁阀(Zone自控)', gate: '闸阀(手动)', angle: '角阀(手动)', washdown: '冲洗阀(WD)', qcv: '取水阀(QCV)', pullbox: '拉线箱' };
var LINE_TYPE_LABELS = { irrigation: '灌溉主管', flush: '冲洗主管', toilet: '冲厕主管', casing: '过路套管', control: '控制线', comm: '通讯线' };

function pdxfCsrf() {
  var m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? m[1] : '';
}
function pdxfSetStep(n) {
  for (var i = 1; i <= 4; i++)
    document.getElementById('pdxfStep' + i).classList.toggle('on', i <= n);
}
function pdxfToggle(id) {
  document.getElementById(id).classList.toggle('open');
  if (pdxfMap) setTimeout(function () { pdxfMap.invalidateSize(); }, 50);
}

// 地图常驻：页面加载即初始化，底图 + 淡色参照（现有 zone / 水管）。
// boundary_points 支持平面点/多环/嵌套组格式，递归展开成环列表再画
// （直接按平面点画嵌套格式会喂出 undefined，Leaflet 抛 Polyline 错误）。
function pdxfRings(bp) {
  if (!bp || !bp.length) return [];
  if (!Array.isArray(bp[0])) {
    return [bp.filter(function (p) { return p && p.lat !== undefined; })
               .map(function (p) { return [p.lat, p.lng]; })];
  }
  return bp.reduce(function (acc, r) { return acc.concat(pdxfRings(r)); }, []);
}
function pdxfInitMap() {
  pdxfMap = L.map('pdxfMap', { preferCanvas: true });
  // 与首页/管线表单同一套瓦片：Esri 卫星 + GeoQ 高层级补底（OSM 国内不可达）
  var satTile = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: '&copy; Esri', maxNativeZoom: 19, maxZoom: 22,
  });
  var fallbackTile = L.tileLayer('https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}', {
    attribution: '&copy; GeoQ', minZoom: 19, maxZoom: 22, opacity: 0.7,
  });
  L.layerGroup([satTile, fallbackTile]).addTo(pdxfMap);
  // 预览专用 pane（管线 canvas + 阀门 + 标注都挂进来），微调拖动只动这个 pane
  pdxfPreviewPane = pdxfMap.createPane('pdxfPreview');
  pdxfPreviewPane.style.zIndex = 450;
  pdxfPreviewPane.style.pointerEvents = 'none';
  pdxfPreviewRenderer = L.canvas({ pane: 'pdxfPreview' });
  pdxfInitAdjust();
  try {
    var rz = (window.__DXF__.zones || []);
    var zb = [];
    rz.forEach(function (z) {
      pdxfRings(z.boundary_points).forEach(function (ring) {
        if (ring.length < 3) return;
        zb = zb.concat(ring);
        L.polygon(ring,
          { color: z.boundary_color || '#52B788', weight: 1, opacity: .35, fillOpacity: .05, interactive: false })
          .addTo(pdxfMap);
      });
    });
    var rp = (window.__DXF__.pipelines || []);
    pdxfRefLayer = L.layerGroup().addTo(pdxfMap);
    rp.forEach(function (p) {
      var ll = (p.line_points || [])
        .filter(function (pt) { return pt && pt.lat !== undefined; })
        .map(function (pt) { return [pt.lat, pt.lng]; });
      if (ll.length < 2) return;
      zb = zb.concat(ll);
      // 与首页同款可见度：类型配色实线 + 管径映射线宽（卫星底图上淡虚线看不见）
      var dia = parseFloat(p.main_diameter) || 0;
      L.polyline(ll, {
        color: p.line_color || '#CC3333',
        weight: dia ? Math.max(3, Math.min(9, 2 + dia / 15)) : 3,
        opacity: .85, interactive: false,
      }).addTo(pdxfRefLayer);
    });
    if (zb.length) pdxfMap.fitBounds(L.latLngBounds(zb).pad(0.05));
  } catch (e) { /* 参照层可选 */ }
  // 框选事件链：mousedown 判定意图 → mousemove 拉框 → document mouseup 收框选线
  pdxfMap.on('mousedown', function (e) {
    if (!pdxfEditMode || !pdxfTune.on || pdxfTune.multi.on || pdxfTune.gesture) return;
    if (!pdxfTuneBoxIntent(e)) return;
    pdxfTuneBoxStart(e);
  });
  pdxfMap.on('mousemove', pdxfTuneBoxMove);
  L.DomEvent.on(document, 'mouseup', function () { pdxfTuneBoxEnd(); });
  window.addEventListener('resize', function () { pdxfMap.invalidateSize(); });
}

// ── ① analyze ────────────────────────────────────────────────────────
function pdxfAnalyze() {
  var f = document.getElementById('pdxfFile').files[0];
  var st = document.getElementById('pdxfAnalyzeStatus');
  if (!f) { st.innerHTML = '<span style="color:#c0392b;">请先选择 .dxf 文件</span>'; return; }
  var btn = document.getElementById('pdxfAnalyzeBtn');
  btn.disabled = true; btn.textContent = '解析中…';
  st.innerHTML = '正在解析（大图约需几秒）…';
  var fd = new FormData();
  fd.append('file', f);
  fetch("__DXF__.urls.analyze", {
    method: 'POST',
    headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
    body: fd,
  }).then(function (r) { return r.json(); }).then(function (d) {
    btn.disabled = false; btn.textContent = '解析图纸';
    if (!d.success) { st.innerHTML = '<span style="color:#c0392b;">' + (d.error || '解析失败') + '</span>'; return; }
    pdxfData = d;
    pdxfDbChanged = false;
    pdxfToken = d.token || null;         // 解析缓存 token：导入免重传/免重解析
    pdxfOffset = { dLat: 0, dLng: 0 };   // 新图纸从零偏移开始
    var totalBlocks = d.blocks.reduce(function (s, b) { return s + b.count; }, 0);
    var totalLabels = d.labels.reduce(function (s, l) { return s + l.count; }, 0);
    st.innerHTML = '解析完成：<span class="pdxf-chip">' + d.layers.length + ' 个线图层</span>' +
      '<span class="pdxf-chip">' + totalBlocks + ' 个块实例</span>' +
      '<span class="pdxf-chip">' + totalLabels + ' 条文字标注</span>';
    document.getElementById('pdxfUploadBadge').textContent = '已解析';
    document.getElementById('pdxfMapBadge').textContent = d.layers.length + ' 图层';
    document.getElementById('pdxfCoordInfo').textContent = d.coord_info || '';
    pdxfRenderTables();
    pdxfRefreshMap();
    document.getElementById('pdxfMapCard').classList.add('open');
    document.getElementById('pdxfImportCard').classList.add('open');
    document.getElementById('pdxfUploadCard').classList.remove('open');
    pdxfSetStep(3);
  }).catch(function () {
    btn.disabled = false; btn.textContent = '解析图纸';
    st.innerHTML = '<span style="color:#c0392b;">网络错误</span>';
  });
}

// ── ② mapping tables ─────────────────────────────────────────────────
function pdxfRenderTables() {
  var lb = document.getElementById('pdxfLayerBody');
  lb.innerHTML = pdxfData.layers.map(function (l, i) {
    pdxfColorOf[l.layer] = LAYER_COLORS[i % LAYER_COLORS.length];
    var dia = l.diameter_guess != null ? l.diameter_guess : '';
    var lname = pdxfEsc(l.layer);
    return '<tr>' +
      '<td><input type="checkbox" class="pdxf-layer-include" data-layer="' + lname + '"' + (l.include_guess ? ' checked' : '') + ' onchange="pdxfRefreshMap()"></td>' +
      '<td class="l-left"><span class="pdxf-layer-legend-color" data-zoom-layer="' + lname + '"><span class="sw" style="background:' + pdxfColorOf[l.layer] + '"></span>' + lname + '</span></td>' +
      '<td>' + l.segments + '</td><td>' + l.total_len + '</td>' +
      '<td><input type="number" min="0" step="1" class="pdxf-input pdxf-layer-dia" data-layer="' + lname + '" value="' + dia + '" style="width:72px;"></td>' +
      '<td><select class="pdxf-select pdxf-layer-type" data-layer="' + lname + '">' +
        Object.keys(LINE_TYPE_LABELS).map(function (t) {
          return '<option value="' + t + '"' + (l.type_guess === t ? ' selected' : '') + '>' + LINE_TYPE_LABELS[t] + '</option>';
        }).join('') + '</select></td>' +
      '</tr>';
  }).join('');

  document.getElementById('pdxfBlockBody').innerHTML = pdxfData.blocks.map(function (b) {
    var bname = pdxfEsc(b.block);
    return '<tr>' +
      '<td><input type="checkbox" class="pdxf-block-include" data-block="' + bname + '"' + (b.include_guess ? ' checked' : '') + ' onchange="pdxfRefreshMap()"></td>' +
      '<td>' + bname + '</td><td>' + b.count + '</td>' +
      '<td class="l-left" style="font-size:.7rem;color:#888;">' + (b.attrs.length ? pdxfEsc(b.attrs.join(', ')) : '—') + '</td>' +
      '<td><select class="pdxf-select pdxf-block-type" data-block="' + bname + '">' +
        Object.keys(VALVE_LABELS).map(function (t) {
          return '<option value="' + t + '"' + (b.valve_type_guess === t ? ' selected' : '') + '>' + VALVE_LABELS[t] + '</option>';
        }).join('') + '</select></td>' +
      '</tr>';
  }).join('');

  // 图层名点击缩放走 data 属性委托（拼 onclick 字符串会被引号逃逸）
  document.getElementById('pdxfLayerBody').addEventListener('click', function (e) {
    var el = e.target.closest('[data-zoom-layer]');
    if (el) pdxfZoomLayer(el.getAttribute('data-zoom-layer'));
  });
  document.getElementById('pdxfLabelBox').innerHTML = pdxfData.labels.map(function (l, i) {
    var checked = l.layer === '设备编号' || i === 0 ? ' checked' : '';
    var lname = pdxfEsc(l.layer);
    return '<label class="pdxf-chip" style="cursor:pointer;"><input type="checkbox" class="pdxf-label-use" data-layer="' + lname + '"' + checked + ' onchange="pdxfRefreshMap()"> ' + lname + '（' + l.count + '，如 ' + pdxfEsc(l.samples[0] || '') + '）</label>';
  }).join('');
}

// ── ③ preview overlays（在常驻底图上叠加/刷新） ─────────────────────
function pdxfRefreshMap() {
  if (!pdxfMap || !pdxfData) return;
  Object.values(pdxfLayers).forEach(function (g) { if (pdxfMap.hasLayer(g)) pdxfMap.removeLayer(g); });
  pdxfLayers = {};
  var all = [];
  var included = {};
  document.querySelectorAll('.pdxf-layer-include').forEach(function (cb) {
    included[cb.dataset.layer] = cb.checked;
  });
  var blocksOn = {};
  document.querySelectorAll('.pdxf-block-include').forEach(function (cb) {
    blocksOn[cb.dataset.block] = cb.checked;
  });

  var labelsOn = {};
  document.querySelectorAll('.pdxf-label-use').forEach(function (cb) {
    labelsOn[cb.dataset.layer] = cb.checked;
  });

  pdxfData.preview.layers.forEach(function (pl) {
    var on = included[pl.layer];
    var g = L.layerGroup([], { pane: 'pdxfPreview' });
    var color = pdxfColorOf[pl.layer] || '#666';
    pl.paths.forEach(function (path) {
      var ll = path.map(function (p) { return [p.lat + pdxfOffset.dLat, p.lng + pdxfOffset.dLng]; });
      all = all.concat(ll);
      L.polyline(ll, { color: on ? color : '#bbb', weight: on ? 3 : 1.5, opacity: on ? .9 : .35,
                       interactive: false, pane: 'pdxfPreview', renderer: pdxfPreviewRenderer }).addTo(g);
    });
    g.addTo(pdxfMap);
    pdxfLayers['layer:' + pl.layer] = g;
  });

  var vg = L.layerGroup([], { pane: 'pdxfPreview' });
  pdxfData.preview.valves.forEach(function (v) {
    if (!blocksOn[v.block]) return;
    L.circleMarker([v.lat + pdxfOffset.dLat, v.lng + pdxfOffset.dLng], {
      radius: 3.5, color: '#c0392b', weight: 1.5, fillColor: '#fff', fillOpacity: 1,
      pane: 'pdxfPreview', renderer: pdxfPreviewRenderer,
    }).bindTooltip(pdxfEsc(v.block), { direction: 'top' }).addTo(vg);
  });
  vg.addTo(pdxfMap);
  pdxfLayers['valves'] = vg;

  pdxfData.labels.forEach(function (lb) {
    if (!labelsOn[lb.layer]) return;   // 取消勾选的标注层不画（此前漏读勾选状态的 bug）
    var g = L.layerGroup([], { pane: 'pdxfPreview' });
    lb.points.slice(0, 200).forEach(function (p) {
      L.marker([p.lat + pdxfOffset.dLat, p.lng + pdxfOffset.dLng], {
        icon: L.divIcon({ className: '', html: '<span style="font-size:10px;color:#333;background:rgba(255,255,255,.75);padding:0 2px;border-radius:3px;white-space:nowrap;">' + pdxfEsc(p.text) + '</span>' }),
        interactive: false, pane: 'pdxfPreview',
      }).addTo(g);
    });
    g.addTo(pdxfMap);
    pdxfLayers['labels:' + lb.layer] = g;
  });

  pdxfRenderLegend(included, blocksOn);
}

function pdxfRenderLegend(included, blocksOn) {
  var html = pdxfData.layers.map(function (l) {
    return '<div><span class="sw" style="background:' + (pdxfColorOf[l.layer] || '#666') + '"></span>' +
      (included[l.layer] ? '' : '<s style="color:#aaa;">') + pdxfEsc(l.layer) +
      (included[l.layer] ? '' : '</s>') + '</div>';
  }).join('');
  var totalV = pdxfData.blocks.reduce(function (s, b) { return s + (blocksOn[b.block] ? b.count : 0); }, 0);
  html += '<div style="border-top:1px solid #eee;margin-top:4px;padding-top:4px;">🔴 阀门 ' + totalV + ' 个</div>';
  if (!pdxfLegendCtl) {
    pdxfLegendCtl = L.control({ position: 'bottomleft' });
    pdxfLegendCtl.onAdd = function () {
      var d = L.DomUtil.create('div', 'pdxf-legend');
      d.id = 'pdxfLegend';
      return d;
    };
    pdxfLegendCtl.addTo(pdxfMap);
  }
  var el = document.getElementById('pdxfLegend');
  if (el) el.innerHTML = html;
}

function pdxfZoomLayer(layer) {
  var g = pdxfLayers['layer:' + layer];
  if (g && pdxfMap) pdxfMap.fitBounds(g.getBounds().pad(0.15));
}

// ── ④ import ────────────────────────────────────────────────────────
function pdxfCollectSpecs() {
  var layers = {}, blocks = {};
  document.querySelectorAll('.pdxf-layer-include').forEach(function (cb) {
    layers[cb.dataset.layer] = { include: cb.checked };
  });
  document.querySelectorAll('.pdxf-layer-dia').forEach(function (inp) {
    if (layers[inp.dataset.layer]) layers[inp.dataset.layer].diameter = inp.value;
  });
  document.querySelectorAll('.pdxf-layer-type').forEach(function (sel) {
    if (layers[sel.dataset.layer]) layers[sel.dataset.layer].type = sel.value;
  });
  document.querySelectorAll('.pdxf-block-include').forEach(function (cb) {
    blocks[cb.dataset.block] = { include: cb.checked };
  });
  document.querySelectorAll('.pdxf-block-type').forEach(function (sel) {
    if (blocks[sel.dataset.block]) blocks[sel.dataset.block].valve_type = sel.value;
  });
  var labelLayers = Array.prototype.map.call(
    document.querySelectorAll('.pdxf-label-use:checked'), function (cb) { return cb.dataset.layer; });
  return { layers: layers, blocks: blocks, labelLayers: labelLayers };
}

function pdxfImport() {
  var f = document.getElementById('pdxfFile').files[0];
  var st = document.getElementById('pdxfImportStatus');
  if (!pdxfData) { st.innerHTML = '<span style="color:#c0392b;">请先解析图纸</span>'; return; }
  var specs = pdxfCollectSpecs();
  var anyLayer = Object.values(specs.layers).some(function (s) { return s.include; });
  if (!anyLayer) { st.innerHTML = '<span style="color:#c0392b;">请至少勾选一个管道图层</span>'; return; }
  var btn = document.getElementById('pdxfImportBtn');
  btn.disabled = true; btn.textContent = '导入中…'; st.textContent = '正在创建水管与阀门…';
  var fd = new FormData();
  if (f) fd.append('file', f);                 // 优先走 token 缓存，文件仅兜底
  if (pdxfToken) fd.append('token', pdxfToken);
  if (f) fd.append('filename', f.name);        // 批次名（token 导入时无文件对象）
  fd.append('layers_json', JSON.stringify(specs.layers));
  fd.append('blocks_json', JSON.stringify(specs.blocks));
  fd.append('label_layers', JSON.stringify(specs.labelLayers));
  fd.append('offset_lat', String(pdxfOffset.dLat));
  fd.append('offset_lng', String(pdxfOffset.dLng));
  fetch("__DXF__.urls.importSubmit", {
    method: 'POST',
    headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
    body: fd,
  }).then(function (r) { return r.json(); }).then(function (d) {
    btn.disabled = false; btn.textContent = '确认导入';
    if (!d.success) { st.innerHTML = '<span style="color:#c0392b;">' + (d.error || '导入失败') + '</span>'; return; }
    pdxfSetStep(4);
    document.getElementById('pdxfImportBadge').textContent = '已完成';
    var stats = (d.layer_stats || []).map(function (s) {
      return '<span class="pdxf-chip">' + s.layer + '：' + s.segments + ' 段 → ' + s.paths + ' 条</span>';
    }).join('');
    pdxfDbChanged = false;
    document.getElementById('pdxfResultBox').innerHTML =
      '<div class="pdxf-result"><b>导入完成</b>：创建水管 <b>' + d.pipelines + '</b> 条、阀门 <b>' + d.valves + '</b> 个' +
      '（' + d.labeled_valves + ' 个带标注名，' + d.skipped_valves + ' 个距管线过远未挂接）<div style="margin-top:6px;">' + stats + '</div>' +
      '<div style="margin-top:8px;"><button type="button" class="pdxf-btn pdxf-btn-primary" onclick="pdxfGoTune()">🔧 去精调（逐线对齐卫星图）</button>　' +
      '<a href="__DXF__.urls.dashboard" target="_blank">→ 查看地图</a>　' +
      '<a href="__DXF__.urls.settings" target="_blank">→ 水管管理列表</a></div></div>';
    st.textContent = '';
  }).catch(function () {
    btn.disabled = false; btn.textContent = '确认导入';
    st.innerHTML = '<span style="color:#c0392b;">网络错误</span>';
  });
}

// ── 整体微调：开启后拖动地图 = 平移整组预览元素（不动画地图本体） ────
// 拖动过程用 CSS transform 移动预览 pane（顺滑），松手换算成经纬度偏移
// 并按偏移重绘；偏移会随导入一起提交，最终落库坐标即所见。
function pdxfInitAdjust() {
  var ctl = L.control({ position: 'topright' });
  ctl.onAdd = function () {
    var d = L.DomUtil.create('div', 'pdxf-adjust leaflet-bar leaflet-control');
    d.innerHTML =
      '<button type="button" id="pdxfEditBtn" title="精细编辑：点击地图上的管道/阀门进行删除、清标注、指派 zone">🔧 精细编辑</button>' +
      '<button type="button" id="pdxfAdjustBtn" title="开启后按住地图拖动，整体平移管线/阀门/标注">✥ 整体微调</button>' +
      '<button type="button" id="pdxfAdjustReset" title="清除微调偏移">↺</button>';
    L.DomEvent.disableClickPropagation(d);
    d.querySelector('#pdxfEditBtn').addEventListener('click', pdxfToggleEditMode);
    d.querySelector('#pdxfAdjustBtn').addEventListener('click', pdxfToggleAdjust);
    d.querySelector('#pdxfAdjustReset').addEventListener('click', function () {
      pdxfOffset = { dLat: 0, dLng: 0 };
      pdxfUpdateAdjustHint();
      pdxfRefreshMap();
    });
    return d;
  };
  ctl.addTo(pdxfMap);

  var container = pdxfMap.getContainer();
  container.addEventListener('mousedown', function (e) {
    if (!pdxfAdjustOn || e.button !== 0) return;
    e.preventDefault();
    pdxfDrag = { x: e.clientX, y: e.clientY };
  });
  window.addEventListener('mousemove', function (e) {
    if (!pdxfDrag) return;
    var dx = e.clientX - pdxfDrag.x, dy = e.clientY - pdxfDrag.y;
    pdxfPreviewPane.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
  });
  window.addEventListener('mouseup', function (e) {
    if (!pdxfDrag) return;
    var dx = e.clientX - pdxfDrag.x, dy = e.clientY - pdxfDrag.y;
    pdxfDrag = null;
    pdxfPreviewPane.style.transform = '';
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
    var a = pdxfMap.containerPointToLatLng([0, 0]);
    var b = pdxfMap.containerPointToLatLng([dx, dy]);
    pdxfOffset.dLat += b.lat - a.lat;
    pdxfOffset.dLng += b.lng - a.lng;
    pdxfUpdateAdjustHint();
    pdxfRefreshMap();   // 按新偏移重绘（提交这次拖动）
  });
}
function pdxfToggleAdjust() {
  pdxfAdjustOn = !pdxfAdjustOn;
  var btn = document.getElementById('pdxfAdjustBtn');
  if (pdxfAdjustOn) {
    if (pdxfCal.on) pdxfCalStop();   // 互斥：校准中不开微调（点击会串台）
    btn.style.background = 'var(--color-primary, #2D6A4F)';
    btn.style.color = '#fff';
    pdxfMap.dragging.disable();
    pdxfMap.getContainer().style.cursor = 'move';
  } else {
    btn.style.background = '';
    btn.style.color = '';
    pdxfMap.dragging.enable();
    pdxfMap.getContainer().style.cursor = '';
  }
  pdxfUpdateAdjustHint();
}

// ── 📍 三点比例校准：DXF 管点 ↔ 卫星图对应点，最小二乘拟合相似变换 ──
function pdxfUpdateAdjustHint() {
  var btn = document.getElementById('pdxfAdjustBtn');
  if (!btn) return;
  var mLat = pdxfOffset.dLat * 111320,
      mLng = pdxfOffset.dLng * 111320 * Math.cos(31.14 / 180 * Math.PI);
  btn.title = (pdxfAdjustOn ? '微调中：按住地图拖动整体平移；再点关闭' : '开启后按住地图拖动，整体平移管线/阀门/标注') +
    (Math.abs(mLat) > 0.05 || Math.abs(mLng) > 0.05 ? '（当前偏移 ↑%.1fm →%.1fm，导入时生效）'.replace('%.1f', mLat.toFixed(1)).replace('%.1f', mLng.toFixed(1)) : '');
}

// ── 精细编辑模式：加载已入库的管线/阀门，点击单个元素在侧栏编辑 ──────
