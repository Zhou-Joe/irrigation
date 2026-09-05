/* DXF 管线导入 — 由 pipeline_dxf_import.html 内联脚本机械拆出（零逻辑改动）。
 * 页面引导块(window.__DXF__)必须在本文件之前加载。全局函数/变量共享，无模块系统。 */
// ── 🔧 精细编辑 + ⚙ 逐线/成组精调：手势/撤销/焊接/复制变换/落库 ──
function pdxfToggleEditMode() {
  pdxfEditMode = !pdxfEditMode;
  var btn = document.getElementById('pdxfEditBtn');
  var card = document.getElementById('pdxfEditCard');
  if (pdxfEditMode) {
    btn.style.background = 'var(--color-primary, #2D6A4F)'; btn.style.color = '#fff';
    card.style.display = '';
    card.classList.add('open');   // 进入编辑即展开卡片（否则选择目标开关藏在折叠里）
    if (pdxfCal.on) pdxfCalStop();           // 互斥：校准中不开编辑（点击会串台）
    if (pdxfAdjustOn) pdxfToggleAdjust();   // 互斥：微调与编辑不同时开
    // 编辑期间藏掉参照层/预览层：编辑层画的是同批管线，双份叠加在精调后
    // 就表现成"旧位置还留着一条线"（像复制粘贴而不是移动）
    if (pdxfRefLayer && pdxfMap.hasLayer(pdxfRefLayer)) pdxfMap.removeLayer(pdxfRefLayer);
    pdxfEditHidPreview = [];
    Object.keys(pdxfLayers).forEach(function (k) {
      if (pdxfMap.hasLayer(pdxfLayers[k])) { pdxfMap.removeLayer(pdxfLayers[k]); pdxfEditHidPreview.push(k); }
    });
    // 预览 pane 默认 pointer-events:none（微调拖动用）；编辑模式必须打开，
    // 否则 canvas 里的管线/阀门收不到点击事件。
    pdxfPreviewPane.style.pointerEvents = '';
    pdxfLoadEditData();
  } else {
    // 有未保存精调修改时先自动落库，成功再退出；失败则留在编辑模式
    var finishOff = function () {
      pdxfTuneExit(true);
      pdxfTune.dirty = {}; pdxfTune.undo = []; pdxfTune.lastXform = null;
      btn.style.background = ''; btn.style.color = '';
      card.style.display = 'none';
      pdxfPreviewPane.style.pointerEvents = 'none';
      pdxfClearEditLayers();
      pdxfSelected = null;
      // 底图参照层换成库里最新坐标（DB 变过则顺带撤掉过时的 DXF 预览层）
      var dbChanged = pdxfDbChanged;
      pdxfRefreshRefPipelines(dbChanged);
      // 库没变过的话，把进编辑时藏掉的 DXF 预览层放回来（analyze→导入流程可能还在进行）
      if (!dbChanged) pdxfEditHidPreview.forEach(function (k) {
        if (pdxfLayers[k] && !pdxfMap.hasLayer(pdxfLayers[k])) pdxfLayers[k].addTo(pdxfMap);
      });
    };
    if (Object.keys(pdxfTune.dirty).length) {
      pdxfTuneSaveAll({ noReload: true, silent: true }).then(function (n) {
        if (n >= 0) finishOff();
        else pdxfEditMode = true;   // 保存失败：撤销本次关闭
      });
    } else {
      finishOff();
    }
  }
}
function pdxfClearEditLayers() {
  if (pdxfEditLayers && pdxfMap.hasLayer(pdxfEditLayers)) pdxfMap.removeLayer(pdxfEditLayers);
  pdxfEditLayers = null;
}
function pdxfLoadEditData() {
  // 重载会用服务器数据覆盖内存里未保存的精调修改——先冲洗落库再取数；
  // 冲洗失败（dirty 仍有）时宁可放弃本次刷新，也不覆盖未保存的修改。
  // _saving 由 saveAll 内部管理（并发保存排队），这里只管发起。
  if (Object.keys(pdxfTune.dirty).length) {
    if (!pdxfTune._saving) {
      pdxfTuneSaveAll({ noReload: true, silent: true }).then(function (n) {
        if (n >= 0) pdxfLoadEditData();
      });
    }
    return;
  }
  document.getElementById('pdxfEditBody').innerHTML =
    '<p class="pdxf-hint">加载中…</p>';
  fetch("__DXF__.urls.editData", { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.success) throw new Error(d.error);
      pdxfEdit = d;
      pdxfRenderEditLayers();
      // 精调/点选还开着（如点了「保存修改」触发重载）：保持对应面板，
      // 否则撤销/保存按钮会被默认面板顶掉，看起来像"没生效"
      if (pdxfTune.on || pdxfTune.multi.on) {
        if (pdxfTune.multi.on)   // 重渲染会重置样式——把紫色选中重新画上
          Object.keys(pdxfTune.multi.ids).forEach(function (id) { pdxfTuneSetMultiStyle(+id, true); });
        pdxfTunePanel();
        return;
      }
      // 编辑模式=常驻成组点选：🔧 一开就能多选管线，拖动即开始精调
      if (window.pdxfEditMode) { pdxfTuneEnterGroup([]); return; }
      pdxfEditDefaultPanel();
    })
    .catch(function () {
      // 重载失败不整体退出编辑模式——精调/点选中保持当前面板可重试
      if (pdxfTune.on || pdxfTune.multi.on) { pdxfTunePanel(); return; }
      document.getElementById('pdxfEditBody').innerHTML =
        '<p class="pdxf-hint" style="color:#c0392b;">加载失败，请重试。</p>';
      pdxfToggleEditMode();
    });
}
// 编辑模式默认面板（选择目标过滤 + 统计提示）；精调开启/退出时各自渲染专属面板
function pdxfEditDefaultPanel() {
  document.getElementById('pdxfEditBody').innerHTML =
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:.8rem;">' +
    '<span style="color:#666;">选择目标：</span>' +
    '<label style="cursor:pointer;"><input type="radio" name="pdxfPickTarget" value="all"' +
    (pdxfEditPickTarget === 'all' ? ' checked' : '') + ' onchange="pdxfSetPickTarget(\'all\')"> 全部</label>' +
    '<label style="cursor:pointer;"><input type="radio" name="pdxfPickTarget" value="pipes"' +
    (pdxfEditPickTarget === 'pipes' ? ' checked' : '') + ' onchange="pdxfSetPickTarget(\'pipes\')"> 仅管道</label>' +
    '<span style="color:#999;font-size:.72rem;">（阀门太密选不中线时切「仅管道」）</span></div>' +
    '<p class="pdxf-hint">共 ' + pdxfEdit.pipelines.length + ' 条管道、' + pdxfEdit.valves.length +
    ' 个阀门。点击地图上的元素编辑；删除即从数据库移除。</p>';
}
function pdxfGoTune() {
  // 导入完成后的桥接：直接进入精细编辑（预览层与 DB 一致，先撤预览防重叠）
  Object.keys(pdxfLayers).forEach(function (k) {
    if (pdxfMap.hasLayer(pdxfLayers[k])) pdxfMap.removeLayer(pdxfLayers[k]);
  });
  if (!pdxfEditMode) pdxfToggleEditMode();
  document.getElementById('pdxfEditCard').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function pdxfSetPickTarget(t) {
  pdxfEditPickTarget = t;
  pdxfRenderEditLayers();   // 重渲染以应用阀门 interactive 开关
}
// 参照管线层刷新：编辑/精调后底图上还是页面加载时的旧坐标——从库里取最新
// 重画，否则退出编辑看起来像"改动作被撤销了"。wipePreview=true 时同时撤掉
// DXF 预览层（预览是导入前坐标，DB 变过后只会误导）。
function pdxfRefreshRefPipelines(wipePreview) {
  fetch("__DXF__.urls.editData", { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.success) return;
      if (pdxfRefLayer && pdxfMap.hasLayer(pdxfRefLayer)) pdxfMap.removeLayer(pdxfRefLayer);
      pdxfRefLayer = L.layerGroup().addTo(pdxfMap);
      d.pipelines.forEach(function (p) {
        var ll = (p.line_points || [])
          .filter(function (pt) { return pt && pt.lat !== undefined; })
          .map(function (pt) { return [pt.lat, pt.lng]; });
        if (ll.length < 2) return;
        var dia = parseFloat(p.diameter) || 0;
        L.polyline(ll, {
          color: p.color || '#CC3333',
          weight: dia ? Math.max(3, Math.min(9, 2 + dia / 15)) : 3,
          opacity: .85, interactive: false,
        }).addTo(pdxfRefLayer);
      });
      d.valves.forEach(function (v) {
        if (!v.point || !v.point[0]) return;
        L.circleMarker([v.point[0].lat, v.point[0].lng], {
          radius: 4, color: '#555', weight: 1, fillColor: '#ffd166', fillOpacity: .9,
          interactive: false,
        }).addTo(pdxfRefLayer);
      });
      if (wipePreview) {
        Object.keys(pdxfLayers).forEach(function (k) {
          if (pdxfMap.hasLayer(pdxfLayers[k])) pdxfMap.removeLayer(pdxfLayers[k]);
        });
        pdxfDbChanged = false;
      }
    }).catch(function () { /* 静默：参照层只是视觉辅助 */ });
}
function pdxfHoverCursor(on) {
  pdxfMap.getContainer().style.cursor = on ? 'pointer' : '';
}
function pdxfRenderEditLayers() {
  pdxfClearEditLayers();
  pdxfEditLayers = L.featureGroup();
  pdxfEditLineById = {};
  pdxfEditValveById = {};
  pdxfEdit.pipelines.forEach(function (p) {
    var ll = (p.line_points || [])
      .filter(function (pt) { return pt && pt.lat !== undefined; })
      .map(function (pt) { return [pt.lat, pt.lng]; });
    if (ll.length < 2) return;
    var line = L.polyline(ll, {
      color: p.color, weight: p.diameter ? Math.max(4, Math.min(8, 2 + p.diameter / 15)) : 4,
      opacity: .8, interactive: true, pane: 'pdxfPreview', renderer: pdxfPreviewRenderer,
    }).on('click', function () {
      if (pdxfTune.multi.on) { pdxfTuneToggleMulti(p.id); return; }
      pdxfSelect({ kind: 'pipeline', id: p.id });
    })
      .on('mouseover', function () { pdxfHoverCursor(true); })
      .on('mouseout', function () { pdxfHoverCursor(false); });
    pdxfEditLineById[p.id] = line;
    line.addTo(pdxfEditLayers);
  });
  pdxfEdit.valves.forEach(function (v) {
    var pt = Array.isArray(v.point) && v.point[0]
      ? [v.point[0].lat, v.point[0].lng] : null;
    if (!pt) return;
    var vm = L.circleMarker(pt, {
      radius: 6, color: '#333', weight: 2, fillColor: '#ffd166', fillOpacity: 1,
      // 阀门太密时会"盖住"线导致选不中管道——「选择目标」切到仅管道时
      // 阀门不参与点击命中（视觉仍在）。
      interactive: pdxfEditPickTarget !== 'pipes', pane: 'pdxfPreview', renderer: pdxfPreviewRenderer,
    }).on('click', function () {
      if (pdxfTune.multi.on) return;   // 点选模式中点阀门忽略（防误触清掉成组选择）
      pdxfSelect({ kind: 'valve', id: v.id });
    })
      .on('mouseover', function () { pdxfHoverCursor(true); })
      .on('mouseout', function () { pdxfHoverCursor(false); })
      .bindTooltip(pdxfEsc((v.name || '#' + v.id) + ' · ' + v.type_display), { direction: 'top' });
    pdxfEditValveById[v.id] = vm;
    vm.addTo(pdxfEditLayers);
  });
  pdxfEditLayers.addTo(pdxfMap);
}
// 退出精调：未保存的修改自动落库（用户预期"改完退出就该存上"）
function pdxfTuneExitAndSave() {
  if (Object.keys(pdxfTune.dirty).length) {
    pdxfTuneSaveAll({ noReload: true }).then(function (n) {
      if (n >= 0) {
        pdxfTuneExit(true);
        // 退回编辑模式默认面板——否则旧的精调按钮残留在面板上（点了没反应）
        pdxfEditDefaultPanel();
      }
      // 保存失败(-1)时保留精调态，dirty 仍在可重试
    });
  } else {
    pdxfTuneExit();
    pdxfEditDefaultPanel();
  }
}

function pdxfSelect(sel) {
  if (pdxfTune._boxSuppressClick) return;   // 刚拉完框，吞掉跟队的 click
  if (pdxfTune.on) {
    if (pdxfTune.multi.on) {   // 复制变换点选中
      if (sel.kind === 'pipeline') pdxfTuneToggleMulti(sel.id);
      return;
    }
    // 精调中点管道=成组增删：组外的点=加入，组内的点=移出（移空=回到点选状态）
    if (sel.kind === 'pipeline') {
      var ids = pdxfTuneGroupIds();
      if (pdxfTuneInGroup(sel.id)) ids = ids.filter(function (id) { return id !== sel.id; });
      else ids = ids.concat([sel.id]);
      pdxfTuneEnterGroup(ids);
      return;
    }
    // 点阀门等：切换编辑对象，未保存修改后台静默落库
    if (Object.keys(pdxfTune.dirty).length) pdxfTuneSaveAll({ noReload: true, silent: true });
    pdxfTuneExit(true);
  }
  pdxfSelected = sel;
  var body = document.getElementById('pdxfEditBody');
  var card = document.getElementById('pdxfEditCard');
  card.classList.add('open');
  if (sel.kind === 'pipeline') {
    var p = pdxfEdit.pipelines.find(function (x) { return x.id === sel.id; });
    if (!p) return;
      body.innerHTML =
      '<div style="font-size:.84rem;line-height:1.7;">' +
      '<b>' + pdxfEsc(p.name) + '</b><br>' +
      '类型: ' + pdxfEsc(p.type_display) + (p.diameter ? ' · DN' + p.diameter : '') + '<br>' +
      '编号: ' + pdxfEsc(p.code) + '<br>' +
      '<span style="color:#888;">' + pdxfEsc(p.source || '') + '</span></div>' +
      '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">' +
      '<button type="button" class="pdxf-btn pdxf-btn-primary" onclick="pdxfTuneEnter(' + p.id + ')">⚙ 逐线精调</button>' +
      '<button type="button" class="pdxf-btn pdxf-btn-primary" style="background:#c0392b;" onclick="pdxfDeleteSelected()">删除这条管道</button></div>';
  } else {
    var v = pdxfEdit.valves.find(function (x) { return x.id === sel.id; });
    if (!v) return;
    var pipe = pdxfEdit.pipelines.find(function (x) { return x.id === v.pipeline_id; });
    var zoneOpts = '<option value="">— 未指派 —</option>' + pdxfEdit.zones.map(function (z) {
      return '<option value="' + z.id + '"' + (z.id === v.zone_id ? ' selected' : '') + '>' + pdxfEsc(z.label) + '</option>';
    }).join('');
    body.innerHTML =
      '<div style="font-size:.84rem;line-height:1.7;">' +
      '<b>阀门 ' + (v.name ? pdxfEsc(v.name) : '#' + v.id) + '</b><br>' +
      '类型: ' + pdxfEsc(v.type_display) + (v.diameter ? ' · ' + v.diameter + 'mm' : '') + '<br>' +
      '所属管道: ' + (pipe ? pdxfEsc(pipe.name) : '—') + '<br>' +
      'Maxicom station: ' + (v.station_id || '无') + '</div>' +
      '<div style="margin-top:8px;">' +
      '<div class="pdxf-hint" style="margin:0 0 2px;">文字标注（清空即去除标注）</div>' +
      '<input type="text" id="pdxfValveName" class="pdxf-input" style="width:100%;" value="' + pdxfEsc(v.name) + '" data-orig="' + pdxfEsc(v.name) + '">' +
      '<div class="pdxf-hint" style="margin:8px 0 2px;">指派区域（自动挂接该 zone 的 Maxicom station，电磁阀同步口径）</div>' +
      '<input type="text" id="pdxfZoneFilter" class="pdxf-input" style="width:100%;margin-bottom:4px;" placeholder="输入编号过滤…（如 9-5）" oninput="pdxfFilterZoneOptions()">' +
      '<select id="pdxfValveZone" class="pdxf-select" style="width:100%;" data-cur="' + (v.zone_id || '') + '" data-orig="' + (v.zone_id || '') + '">' + zoneOpts + '</select>' +
      '<div style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;">' +
      '<button type="button" class="pdxf-btn pdxf-btn-primary" onclick="pdxfSaveValve(' + v.id + ')">保存</button>' +
      '<button type="button" class="pdxf-btn pdxf-btn-primary" style="background:#c0392b;" onclick="pdxfDeleteSelected()">删除这个阀门</button></div></div>';
  }
}
function pdxfFilterZoneOptions() {
  var q = (document.getElementById('pdxfZoneFilter').value || '').trim().toLowerCase();
  var sel = document.getElementById('pdxfValveZone');
  Array.prototype.forEach.call(sel.options, function (o) {
    if (!o.value) { o.style.display = ''; return; }
    o.style.display = (!q || o.textContent.toLowerCase().indexOf(q) >= 0) ? '' : 'none';
  });
  // 选回当前值（若被过滤隐藏则临时可见）
  var cur = sel.getAttribute('data-cur');
  if (cur && sel.value !== cur) sel.value = cur;
}
function pdxfPost(url, fd, done) {
  fetch(url, {
    method: 'POST',
    headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
    body: fd,
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.success) { alert(d.error || '操作失败'); return; }
    done(d);
  }).catch(function () { alert('网络错误'); });
}
function pdxfDeleteSelected() {
  if (!pdxfSelected) return;
  var isPipe = pdxfSelected.kind === 'pipeline';
  var msg = isPipe ? '删除这条管道？（其上的阀门会一并删除）' : '删除这个阀门？';
  if (!confirm(msg)) return;
  var url = isPipe
    ? "/pipelines/edit/pipeline/" + pdxfSelected.id + "/delete/"
    : "/pipelines/edit/valve/" + pdxfSelected.id + "/delete/";
  pdxfPost(url, new FormData(), function () {
    pdxfSelected = null;
    pdxfDbChanged = true;
    pdxfLoadEditData();
  });
}
function pdxfSaveValve(id) {
  // 只提交实际变更的字段——全量提交会把误置空的 zone 连带清掉 station 配对
  var fd = new FormData();
  var nameEl = document.getElementById('pdxfValveName');
  var sel = document.getElementById('pdxfValveZone');
  if (nameEl.dataset.orig !== undefined && nameEl.value !== nameEl.dataset.orig)
    fd.append('name', nameEl.value);
  if (sel.dataset.orig !== undefined && sel.value !== sel.dataset.orig)
    fd.append('zone_id', sel.value);
  if (!fd.has('name') && !fd.has('zone_id')) return;
  pdxfPost("/pipelines/edit/valve/" + id + "/update/", fd, function () {
    pdxfDbChanged = true;
    pdxfLoadEditData();
  });
}

// ── ⚙ 逐线精调：单条管道 平移/旋转/缩放 + 阀门沿线拖拽 + 复制变换 ────
var pdxfEditLineById = {};   // pipeline id → L.polyline（多选高亮用）
var pdxfEditValveById = {};  // valve id → L.circleMarker（精调提交时同步编辑层用）
var pdxfEditHidPreview = []; // 进编辑模式时藏掉的 DXF 预览层 key（退出且库未变时恢复）
var pdxfEditPickTarget = 'all';   // 'all' | 'pipes' — 选择目标过滤（阀门密集时选线用）
var pdxfTune = {
  on: false, pipeId: null,     // pipeId=首线（面板标题/兜底）
  group: [],                   // 成组精调的 pipeline id（含 pipeId）；单线=长度1
  layers: null,                // 本组高亮层：线 + 两端手柄
  lines: {},                   // pipeId → L.polyline（组内每条线的精调层）
  valveMarkers: [],            // [{id, marker}]
  gesture: null,               // 进行中的手势 {kind, ...}
  undo: [],                    // [快照] 快照=[{pipeId, pts, valvePts:[{id,lat,lng}]}] 最多50
  dirty: {},                   // pipeId → true（未保存）
  lastXform: null,             // {anchor, from, to}（[lat,lng]，复制变换用）
  multi: { on: false, ids: {} },   // 复制变换的点选模式
};
function pdxfTunePipe() {
  return pdxfEdit && pdxfEdit.pipelines.find(function (p) { return p.id === pdxfTune.pipeId; }) || null;
}
function pdxfTuneGroupIds() {
  return pdxfTune.group && pdxfTune.group.length
    ? pdxfTune.group : (pdxfTune.pipeId ? [pdxfTune.pipeId] : []);
}
function pdxfTuneInGroup(id) { return pdxfTuneGroupIds().indexOf(id) >= 0; }
function pdxfTuneValves() {
  var ids = {};
  pdxfTuneGroupIds().forEach(function (id) { ids[id] = true; });
  return (pdxfEdit ? pdxfEdit.valves : []).filter(function (v) { return ids[v.pipeline_id]; });
}

function pdxfTuneEnter(pipeId) { pdxfTuneEnterGroup([pipeId]); }
// 成组精调：一组线作为刚体一起平移/旋转/缩放——同一变换作用于每条线，
// 组内接口数学上不脱开；松手后组边界端点统一磁吸焊到组外的线。
function pdxfTuneEnterGroup(ids) {
  var seen = {}, pipes = [];
  (ids || []).forEach(function (id) {
    var p = pdxfTunePipeById(id);
    if (p && (p.line_points || []).length >= 2 && !seen[p.id]) { seen[p.id] = true; pipes.push(p); }
  });
  pdxfTuneExit(true);
  pdxfTuneLiveLines = null; pdxfTuneLiveValves = null;   // 清残留（中止手势的幽灵数据）
  pdxfTune.on = true;
  pdxfTune.pipeId = pipes.length ? pipes[0].id : null;   // 空组=点选状态（🔧 进入编辑模式的默认态）
  pdxfTune.group = pipes.map(function (p) { return p.id; });
  pdxfTune.lines = {};
  pdxfTune.layers = L.layerGroup();
  var base = pdxfTuneBase();
  base.forEach(function (rec) {
    var p = pdxfTunePipeById(rec.pipeId);
    var line = L.polyline(rec.pts, {
      color: '#e67e22', weight: Math.max(6, (p.diameter ? 2 + p.diameter / 15 : 4) + 2),
      opacity: .95, interactive: true, pane: 'pdxfPreview', renderer: pdxfPreviewRenderer,
    }).on('mousedown', function (e) { pdxfTuneStartGesture('translate', e, rec.pipeId); });
    pdxfTune.lines[rec.pipeId] = line;
    line.addTo(pdxfTune.layers);
  });
  // 每条线两端手柄：拖任一端（该线另一端锚定）= 整组旋转+缩放
  pdxfTuneHandles = [];
  base.forEach(function (rec) {
    [0, rec.pts.length - 1].forEach(function (idx) {
      var h = L.circleMarker(rec.pts[idx], {
        radius: 8, color: '#e67e22', weight: 3, fillColor: '#fff', fillOpacity: 1,
        interactive: true, pane: 'pdxfPreview', renderer: pdxfPreviewRenderer,
      }).on('mousedown', function (e) { pdxfTuneStartGesture('handle', e, { pipeId: rec.pipeId, idx: idx }); });
      h.addTo(pdxfTune.layers);
      pdxfTuneHandles.push({ pipeId: rec.pipeId, idx: idx, marker: h });
    });
  });
  // 阀门（绿）沿线可拖，吸附目标=组内所有线
  pdxfTune.valveMarkers = pdxfTuneValves().map(function (v) {
    var pt = v.point && v.point[0] ? [v.point[0].lat, v.point[0].lng] : null;
    if (!pt) return null;
    var m = L.circleMarker(pt, {
      radius: 7, color: '#1d4ed8', weight: 2, fillColor: '#7bed9f', fillOpacity: 1,
      interactive: true, pane: 'pdxfPreview', renderer: pdxfPreviewRenderer,
    }).on('mousedown', function (e) { pdxfTuneStartGesture('valve', e, v.id); })
      .bindTooltip(pdxfEsc(v.name || ('#' + v.id)) + ' · 拖动沿线滑动', { direction: 'top' });
    m.addTo(pdxfTune.layers);
    return { id: v.id, marker: m };
  }).filter(Boolean);
  pdxfTune.layers.addTo(pdxfMap);
  pdxfTunePanel();
}
var pdxfTuneHandles = [];
function pdxfTuneExit(silent) {
  if (pdxfTune.multi.on) pdxfTuneMultiEnd();
  if (pdxfTune.gesture) pdxfTuneEndGesture(true);
  if (pdxfTune.layers && pdxfMap.hasLayer(pdxfTune.layers)) pdxfMap.removeLayer(pdxfTune.layers);
  pdxfTune.layers = null; pdxfTune.lines = {}; pdxfTuneHandles = [];
  pdxfTune.valveMarkers = []; pdxfTune.on = false; pdxfTune.pipeId = null; pdxfTune.group = [];
  if (!silent && Object.keys(pdxfTune.dirty).length) pdxfTunePanel();
}

// 快照（手势开始前入撤销栈）：整组每条线的点 + 线上阀门
function pdxfTuneBase() {
  return pdxfTuneGroupIds().map(function (id) {
    var p = pdxfTunePipeById(id);
    if (!p) return null;
    return {
      pipeId: id,
      pts: (p.line_points || []).map(function (pt) { return [pt.lat, pt.lng]; }),
      valvePts: (pdxfEdit ? pdxfEdit.valves : []).filter(function (v) { return v.pipeline_id === id; })
        .map(function (v) { return v.point && v.point[0] ? { id: v.id, lat: v.point[0].lat, lng: v.point[0].lng } : null; })
        .filter(Boolean),
    };
  }).filter(Boolean);
}
function pdxfTuneUndo() {
  var snap = pdxfTune.undo.pop();
  if (!snap || !snap.length) { pdxfTunePanel(); return; }
  pdxfTuneApplySnapshot(snap);
  pdxfTunePanel();
}
// 撤销应用：快照=一组线的数据（也可作用于当前组之外的线）
function pdxfTuneApplySnapshot(snap) {
  var rebuild = false;
  snap.forEach(function (rec) {
    var p = pdxfTunePipeById(rec.pipeId);
    if (!p) return;
    p.line_points = rec.pts.map(function (pt) { return { lat: pt[0], lng: pt[1] }; });
    (rec.valvePts || []).forEach(function (u) {
      var v = pdxfEdit.valves.find(function (x) { return x.id === u.id; });
      if (v) v.point = [{ lat: u.lat, lng: u.lng }];
      var ev = pdxfEditValveById[u.id];
      if (ev) ev.setLatLng([u.lat, u.lng]);
    });
    pdxfTune.dirty[rec.pipeId] = true;
    var layer = pdxfEditLineById[rec.pipeId];
    if (layer) layer.setLatLngs(rec.pts);
    if (pdxfTune.on && pdxfTuneInGroup(rec.pipeId)) rebuild = true;
  });
  if (rebuild) pdxfTuneEnterGroup(pdxfTuneGroupIds());   // 重建手柄/阀门层
}

// 相似变换（绕 anchor）：from→to 的方向差=旋转、长度比=比例。
// 在 Web Mercator 投影像素空间（map.project/unproject）计算——全程浮点；
// 不能用 latLngToContainerPoint/containerPointToLatLng：容器像素在低缩放
// 级别有取整量化（zoom 14 时 1px≈2.4m），小像素段算旋转/比例会差出米级。
function pdxfTuneXform(originLLs, anchorLL, fromLL, toLL) {
  var z = pdxfMap.getZoom();
  var a = pdxfMap.project(anchorLL, z);
  var f = pdxfMap.project(fromLL, z);
  var t = pdxfMap.project(toLL, z);
  var ang = Math.atan2(t.y - a.y, t.x - a.x) - Math.atan2(f.y - a.y, f.x - a.x);
  var lf = Math.hypot(f.x - a.x, f.y - a.y), lt = Math.hypot(t.x - a.x, t.y - a.y);
  var s = lf > 1e-6 ? Math.max(0.02, lt / lf) : 1;   // 比例下限：手柄拖到锚点上整组塌成一点
  var cos = Math.cos(ang) * s, sin = Math.sin(ang) * s;
  return originLLs.map(function (ll) {
    var p = pdxfMap.project(ll, z);
    var np = pdxfMap.unproject(L.point(
      a.x + cos * (p.x - a.x) - sin * (p.y - a.y),
      a.y + sin * (p.x - a.x) + cos * (p.y - a.y)
    ), z);
    return [np.lat, np.lng];
  });
}
// 点到折线最近点（投影空间逐段垂足，夹到段内）
function pdxfTuneNearest(ll, pts) {
  var z = pdxfMap.getZoom();
  var p = pdxfMap.project(ll, z);
  var best = null, bestD = Infinity;
  for (var i = 1; i < pts.length; i++) {
    var a = pdxfMap.project(pts[i - 1], z);
    var b = pdxfMap.project(pts[i], z);
    var dx = b.x - a.x, dy = b.y - a.y, L2 = dx * dx + dy * dy;
    var t = L2 > 0 ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / L2 : 0;
    t = Math.max(0, Math.min(1, t));
    var cx = a.x + t * dx, cy = a.y + t * dy;
    var d = (p.x - cx) * (p.x - cx) + (p.y - cy) * (p.y - cy);
    if (d < bestD) { bestD = d; best = pdxfMap.unproject(L.point(cx, cy), z); }
  }
  return best ? [best.lat, best.lng] : null;
}

// ── 框选：Shift+拖拽（或「⬚ 框选」常开开关）拉框批量选线入组 ─────────
var pdxfTuneBox = { on: false, mode: false, rect: null, start: null };
function pdxfTuneBoxToggle() {
  pdxfTuneBox.mode = !pdxfTuneBox.mode;
  pdxfTunePanel();
}
function pdxfTuneBoxIntent(e) {
  return pdxfTuneBox.mode || (e && e.originalEvent && e.originalEvent.shiftKey);
}
function pdxfTuneBoxStart(e) {
  pdxfTuneBox.on = true;
  pdxfTuneBox.start = e.latlng;
  pdxfTuneBox.rect = L.rectangle([e.latlng, e.latlng], {
    color: '#2D6A4F', weight: 1.5, dashArray: '6 4', fillColor: '#2D6A4F', fillOpacity: .08,
    interactive: false, pane: 'pdxfPreview', renderer: pdxfPreviewRenderer,
  }).addTo(pdxfMap);
  pdxfMap.dragging.disable();
}
function pdxfTuneBoxMove(e) {
  if (!pdxfTuneBox.on || !pdxfTuneBox.rect) return;
  pdxfTuneBox.rect.setBounds(L.latLngBounds(pdxfTuneBox.start, e.latlng));
}
function pdxfTuneBoxEnd() {
  if (!pdxfTuneBox.on) return;
  pdxfTuneBox.on = false;
  if (!pdxfTuneBox.rect) return;
  var b = pdxfTuneBox.rect.getBounds();
  pdxfMap.removeLayer(pdxfTuneBox.rect);
  pdxfTuneBox.rect = null;
  pdxfMap.dragging.enable();
  // 没拉出面积=当普通点击处理（不吞 click，shift+点线仍能单选）
  if (b.getEast() - b.getWest() < 1e-7 && b.getNorth() - b.getSouth() < 1e-7) return;
  // 拉框后的 mouseup 会跟一次 click——短时吞掉，防止误切换组内成员
  pdxfTune._boxSuppressClick = true;
  setTimeout(function () { pdxfTune._boxSuppressClick = null; }, 150);
  // 框内扫到任一顶点即选中，与现有组取并集
  var ids = pdxfTuneGroupIds();
  var added = 0;
  pdxfEdit.pipelines.forEach(function (p) {
    if ((p.line_points || []).length < 2 || ids.indexOf(p.id) >= 0) return;
    var hit = (p.line_points || []).some(function (pt) { return b.contains([pt.lat, pt.lng]); });
    if (hit) { ids.push(p.id); added++; }
  });
  if (added) pdxfTuneEnterGroup(ids);
  else pdxfTunePanel();
}

function pdxfTuneStartGesture(kind, e, arg) {
  if (!pdxfTune.on || pdxfTune.multi.on) return;   // 复制变换点选模式下不做手势
  if (pdxfTuneBoxIntent(e)) return;   // 框选意图（Shift/常开）：拉框优先，不启精调手势
  L.DomEvent.stop(e);
  pdxfTune.gesture = {
    kind: kind, arg: arg, base: pdxfTuneBase(),
    startLL: [e.latlng.lat, e.latlng.lng],
    handle: kind === 'handle' ? arg : null,   // {pipeId, idx}
    valveId: kind === 'valve' ? arg : null,
    pushed: false,   // 首次真实移动才入撤销栈（纯点击不占额度）
  };
  pdxfMap.dragging.disable();
  pdxfMap.getContainer().style.cursor = 'grabbing';
  if (!pdxfTune._mm) {
    pdxfTune._mm = true;
    pdxfMap.on('mousemove', pdxfTuneOnMove);
    // mouseup 必须绑 document：Leaflet 只绑地图容器，拖出边界/侧栏上松手
    // 手势会悬死。同样不能直接挂 pdxfTuneEndGesture——事件对象 truthy 会被
    // 误判成 abort=true，手势永远不提交。
    pdxfTune._mu = function () { pdxfTuneEndGesture(); };
    L.DomEvent.on(document, 'mouseup', pdxfTune._mu);
  }
}
function pdxfTuneAllValvePts(base) {
  var out = [];
  base.forEach(function (rec) { out = out.concat(rec.valvePts || []); });
  return out;
}
// 多线最近点：吸附目标为组内所有线（阀门滑动跨线也贴线）
function pdxfTuneNearestMulti(ll, lines) {
  var best = null;
  lines.forEach(function (rec) {
    var s = pdxfTuneNearest(ll, rec.pts);
    if (!s) return;
    if (!best || pdxfMap.distance(ll, s) < pdxfMap.distance(ll, best)) best = s;
  });
  return best;
}
function pdxfTuneOnMove(e) {
  var g = pdxfTune.gesture;
  if (!g) return;
  if (!g.pushed) {   // 首次真实移动：此刻的 base 才是要撤销到的手势前状态
    g.pushed = true;
    pdxfTune.undo.push(g.base);
    if (pdxfTune.undo.length > 50) pdxfTune.undo.shift();
  }
  var cur = [e.latlng.lat, e.latlng.lng];
  if (g.kind === 'translate') {
    var dLat = cur[0] - g.startLL[0], dLng = cur[1] - g.startLL[1];
    var vs = pdxfTuneAllValvePts(g.base);
    pdxfTuneSetLive(g.base.map(function (rec) {
      return { pipeId: rec.pipeId, pts: rec.pts.map(function (pt) { return [pt[0] + dLat, pt[1] + dLng]; }) };
    }), vs.map(function (v) { return { id: v.id, latlng: [v.lat + dLat, v.lng + dLng] }; }));
  } else if (g.kind === 'handle') {
    var rec = g.base.find(function (r) { return r.pipeId === g.handle.pipeId; }) || g.base[0];
    var n = rec.pts.length;
    var anchorLL = g.handle.idx === 0 ? rec.pts[n - 1] : rec.pts[0];
    var fromLL = rec.pts[g.handle.idx];
    var vs2 = pdxfTuneAllValvePts(g.base);
    var vMoved = pdxfTuneXform(vs2.map(function (v) { return [v.lat, v.lng]; }), anchorLL, fromLL, cur);
    pdxfTuneSetLive(g.base.map(function (r) {
      return { pipeId: r.pipeId, pts: pdxfTuneXform(r.pts, anchorLL, fromLL, cur) };
    }), vs2.map(function (v, k) { return { id: v.id, latlng: vMoved[k] }; }));
    g._xform = { anchor: anchorLL, from: fromLL, to: cur };
  } else if (g.kind === 'valve') {
    // 跟手显示 + 松手吸附（吸附目标=组内所有线）
    var snapPt = pdxfTuneNearestMulti(cur, pdxfTuneLiveLines || g.base);
    pdxfTuneSetValveLive(g.valveId, snapPt || cur);
  }
}
function pdxfTuneEndGesture(abort) {
  var g = pdxfTune.gesture;
  if (!g) return;
  pdxfTune.gesture = null;
  pdxfMap.dragging.enable();
  pdxfMap.getContainer().style.cursor = '';
  if (abort) {   // 中止（如退出模式）：不提交，且必须清 live——否则残留坐标
    pdxfTuneLiveLines = null; pdxfTuneLiveValves = null;   // 会被之后的手势当结果提交
    return;
  }
  // 把 live 结果写回 pdxfEdit 数据 + dirty 标记 + 底下常驻的编辑层
  // （精调层移除后露出的是编辑层——不同步就会看起来"回退到原样"）
  (pdxfTuneLiveLines || []).forEach(function (rec) {
    var q = pdxfTunePipeById(rec.pipeId);
    if (!q) return;
    q.line_points = rec.pts.map(function (pt) { return { lat: pt[0], lng: pt[1] }; });
    pdxfTune.dirty[rec.pipeId] = true;
    var el = pdxfEditLineById[rec.pipeId];
    if (el) el.setLatLngs(rec.pts);
  });
  (pdxfTuneLiveValves || []).forEach(function (u) {
    var v = pdxfEdit.valves.find(function (x) { return x.id === u.id; });
    if (v) {
      v.point = [{ lat: u.latlng[0], lng: u.latlng[1] }]; pdxfTune.dirty[v.pipeline_id] = true;
      var ev = pdxfEditValveById[u.id];
      if (ev) ev.setLatLng(u.latlng);
    }
  });
  if (g.kind === 'handle' && g._xform) pdxfTune.lastXform = g._xform;
  pdxfTuneLiveLines = null; pdxfTuneLiveValves = null;
  // 手柄/平移手势结束：组边界端点统一磁吸焊接（整组同一平移量，组内不脱开）
  if (g.kind !== 'valve') pdxfTuneWeldGroup();
  // 手柄跟随新端点
  pdxfTuneRefreshHandles();
  pdxfTunePanel();
}
var pdxfTuneLiveLines = null, pdxfTuneLiveValves = null;
function pdxfTuneSetLive(linesLive, valveMoves) {
  pdxfTuneLiveLines = linesLive;
  pdxfTuneLiveValves = valveMoves || [];   // 阀门随线变换的位置也进提交数据（否则不写回）
  linesLive.forEach(function (rec) {
    var ln = pdxfTune.lines && pdxfTune.lines[rec.pipeId];
    if (ln) ln.setLatLngs(rec.pts);
  });
  (valveMoves || []).forEach(function (u) {
    var vm = pdxfTune.valveMarkers.find(function (m) { return m.id === u.id; });
    if (vm) vm.marker.setLatLng(u.latlng);
  });
  pdxfTuneRefreshHandles();
}
function pdxfTuneSetValveLive(vid, ll) {
  pdxfTuneLiveValves = [{ id: vid, latlng: ll }];
  var vm = pdxfTune.valveMarkers.find(function (m) { return m.id === vid; });
  if (vm) vm.marker.setLatLng(ll);
}
function pdxfTuneRefreshHandles() {
  if (!pdxfTuneLiveLines || !pdxfTuneHandles.length) return;
  var byId = {};
  pdxfTuneLiveLines.forEach(function (rec) { byId[rec.pipeId] = rec.pts; });
  pdxfTuneHandles.forEach(function (h) {
    var pts = byId[h.pipeId];
    if (pts && pts[h.idx]) h.marker.setLatLng(pts[h.idx]);
  });
}

// ── 端点磁吸焊接（成组·弹性端点版）：组整体停在用户拖放的位置，只有
// 边界端点【顶点】单独弯回吸附组外邻近端点（≤2m）──
// 若整组回拉会把小幅精调直接抵消掉（拖 1m 被吸回原位）；端点顶点吸收
// 差值后，接口视觉严丝合缝，组的其余部分保持用户放置的位置/比例/角度。
var PDXF_WELD_TOL_M = 2.0;
function pdxfTuneWeldGroup(ids) {
  ids = ids || pdxfTuneGroupIds();
  var inG = {};
  ids.forEach(function (id) { inG[id] = true; });
  var pipes = ids.map(function (id) { return pdxfTunePipeById(id); })
    .filter(function (p) { return p && (p.line_points || []).length >= 2; });
  if (!pipes.length) return 0;
  // 组外全部线的端点（首/尾）候选
  var ends = [];
  pdxfEdit.pipelines.forEach(function (q) {
    if (inG[q.id]) return;
    var ql = q.line_points || [];
    if (ql.length < 2) return;
    ends.push([ql[0].lat, ql[0].lng]);
    ends.push([ql[ql.length - 1].lat, ql[ql.length - 1].lng]);
  });
  if (!ends.length) return 0;
  // 先把重合的组端点聚成簇（多条组线共享同一接口顶点）：整簇共用同一吸附
  // 目标——否则各自找各自最近的会把组内接口撕开
  var clusters = [];
  pipes.forEach(function (p) {
    var last = p.line_points.length - 1;
    [0, last].forEach(function (endIdx) {
      var ep = [p.line_points[endIdx].lat, p.line_points[endIdx].lng];
      var key = ep[0].toFixed(9) + ',' + ep[1].toFixed(9);
      var cl = null;
      for (var i = 0; i < clusters.length; i++) if (clusters[i].key === key) { cl = clusters[i]; break; }
      if (!cl) { cl = { key: key, ep: ep, members: [] }; clusters.push(cl); }
      cl.members.push({ p: p, endIdx: endIdx });
    });
  });
  var welded = 0;
  var touched = {};   // pipeId → true（有端点被吸附，需刷新图层/手柄）
  clusters.forEach(function (cl) {
    var best = null, bestD = PDXF_WELD_TOL_M;
    ends.forEach(function (ee) {
      var d = pdxfMap.distance(cl.ep, ee);   // 地理距离（米）
      if (d < bestD) { bestD = d; best = ee; }
    });
    if (!best) return;
    cl.members.forEach(function (m) {
      m.p.line_points[m.endIdx] = { lat: best[0], lng: best[1] };
      touched[m.p.id] = true;
    });
    welded++;
    // 焊接反馈：绿圈闪一下
    var fm = L.circleMarker(best, { radius: 11, color: '#2ecc71', weight: 3,
      fillOpacity: 0, interactive: false, pane: 'pdxfPreview', renderer: pdxfPreviewRenderer });
    fm.addTo(pdxfMap);
    setTimeout(function () { pdxfMap.removeLayer(fm); }, 1200);
  });
  if (!welded) return 0;
  // 刷新被吸附线的数据图层/精调层/手柄
  Object.keys(touched).forEach(function (id) {
    var p = pdxfTunePipeById(+id);
    var ll = p.line_points.map(function (pt) { return [pt.lat, pt.lng]; });
    var layer = pdxfEditLineById[p.id];
    if (layer) layer.setLatLngs(ll);
    var ln = pdxfTune.lines && pdxfTune.lines[p.id];
    if (ln) ln.setLatLngs(ll);
    pdxfTuneHandles.forEach(function (h) {
      if (h.pipeId === p.id) h.marker.setLatLng(ll[h.idx]);
    });
  });
  return welded;
}

// ── 点选模式：复制变换（把 lastXform 应用到多选线）────────────────────
function pdxfTuneSetMultiStyle(pipeId, on) {
  var layer = pdxfEditLineById[pipeId];
  if (!layer) return;
  var p = pdxfTunePipeById(pipeId);
  // weight 用具体值回退：undefined 不会重置 canvas 线宽（线保持高亮的粗度）
  layer.setStyle({
    color: on ? '#7c4dff' : (p ? p.color : '#888'),
    weight: on ? 8 : (p && p.diameter ? Math.max(4, Math.min(8, 2 + p.diameter / 15)) : 4),
  });
}
function pdxfTuneMultiStart() {
  if (!pdxfTune.lastXform) { alert('还没有可复制的变换（先拖一次端点手柄）'); return; }
  pdxfTune.multi.on = true; pdxfTune.multi.ids = {};
  pdxfTunePanel();
}
function pdxfTuneToggleMulti(pipeId) {
  if (pdxfTune.multi.ids[pipeId]) delete pdxfTune.multi.ids[pipeId];
  else pdxfTune.multi.ids[pipeId] = true;
  pdxfTuneSetMultiStyle(pipeId, !!pdxfTune.multi.ids[pipeId]);
  pdxfTunePanel();
}
function pdxfTunePipeById(id) {
  return pdxfEdit.pipelines.find(function (x) { return x.id === id; }) || null;
}
function pdxfTuneMultiEnd() {
  Object.keys(pdxfTune.multi.ids).forEach(function (id) {
    pdxfTuneSetMultiStyle(+id, false);
  });
  pdxfTune.multi.on = false; pdxfTune.multi.ids = {};
  pdxfTunePanel();
}
function pdxfTuneMultiApply() {
  var xf = pdxfTune.lastXform;
  var ids = Object.keys(pdxfTune.multi.ids);
  if (!xf || !ids.length) return;
  // 先整批快照（一次应用=一步撤销），再统一施加变换
  var snap = [];
  ids.forEach(function (id) {
    id = +id;
    var p = pdxfTunePipeById(id);
    if (!p) return;
    var pts = (p.line_points || []).map(function (pt) { return [pt.lat, pt.lng]; });
    if (pts.length < 2) return;
    snap.push({
      pipeId: id, pts: pts,
      valvePts: pdxfEdit.valves.filter(function (v) { return v.pipeline_id === id; })
        .map(function (v) { return v.point && v.point[0] ? { id: v.id, lat: v.point[0].lat, lng: v.point[0].lng } : null; })
        .filter(Boolean),
    });
  });
  if (!snap.length) { pdxfTuneMultiEnd(); return; }
  pdxfTune.undo.push(snap);
  if (pdxfTune.undo.length > 50) pdxfTune.undo.shift();
  snap.forEach(function (rec) {
    var p = pdxfTunePipeById(rec.pipeId);
    if (!p) return;
    var moved = pdxfTuneXform(rec.pts, xf.anchor, xf.from, xf.to);
    var vMoved = pdxfTuneXform(rec.valvePts.map(function (v) { return [v.lat, v.lng]; }), xf.anchor, xf.from, xf.to);
    p.line_points = moved.map(function (pt) { return { lat: pt[0], lng: pt[1] }; });
    vMoved.forEach(function (ll, k) {
      var v = pdxfEdit.valves.find(function (x) { return x.id === rec.valvePts[k].id; });
      if (v) v.point = [{ lat: ll[0], lng: ll[1] }];
      var ev = pdxfEditValveById[rec.valvePts[k].id];
      if (ev) ev.setLatLng(ll);   // 编辑层阀门同步（否则视觉滞留旧位置）
    });
    pdxfTune.dirty[rec.pipeId] = true;
    var layer = pdxfEditLineById[rec.pipeId];
    if (layer) layer.setLatLngs(moved);
  });
  // 同一变换作用的线互为刚体——作为一组统一焊接，组内接口不脱开
  pdxfTuneWeldGroup(snap.map(function (rec) { return rec.pipeId; }));
  pdxfTuneMultiEnd();
}

// ── 保存：把 dirty 管道的几何写库 ─────────────────────────────────────
// opts.noReload=true 不重载编辑数据（后台保存/退出路径用）；opts.silent=true
// 失败不弹窗（面板仍显示待保存状态）。返回 Promise：成功 resolve(保存条数)，
// 失败 resolve(-1)。内部串行化：并发的保存（按钮/退出/重载冲洗）排队执行。
function pdxfTuneSaveAll(opts) {
  opts = opts || {};
  var ids = Object.keys(pdxfTune.dirty);
  if (!ids.length) return Promise.resolve(0);
  if (pdxfTune._saving) return pdxfTune._saving.then(function () { return pdxfTuneSaveAll(opts); });
  pdxfDbChanged = true;
  var err = null;
  function valvePayload(pid) {
    return JSON.stringify(
      pdxfEdit.valves.filter(function (v) { return v.pipeline_id === pid; })
        .filter(function (v) { return v.point && v.point[0]; })
        .map(function (v) { return { id: v.id, point: { lat: v.point[0].lat, lng: v.point[0].lng } }; }));
  }
  function ptsPayload(p) {
    return JSON.stringify((p.line_points || []).map(function (pt) { return { lat: pt.lat, lng: pt.lng }; }));
  }
  var chain = ids.reduce(function (acc, id) {
    return acc.then(function () {
      if (err) return null;   // 前一条失败即停，剩余 dirty 保留可重试
      var p = pdxfTunePipeById(+id);
      if (!p) { delete pdxfTune.dirty[id]; return null; }   // 幽灵管道（已被删）：清标，别卡退出
      var payload = ptsPayload(p) + '|' + valvePayload(+id);
      var fd = new FormData();
      fd.append('line_points', ptsPayload(p));
      fd.append('valves', valvePayload(+id));
      return fetch("/pipelines/edit/pipeline/" + id + "/geometry/", {
        method: 'POST',
        headers: { 'X-CSRFToken': pdxfCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
        body: fd,
      }).then(function (r) { return r.json(); }).then(function (d) {
        // 服务器拒绝（校验失败等）不算保存成功——绝不能清 dirty 假装存上了
        if (!d || d.success === false) {
          err = (d && d.error) || ('管道 ' + id + ' 被服务器拒绝');
        } else {
          // 保存期间同一条线又有新手势/阀门移动：响应晚到不能抹掉新修改的
          // dirty 标记——指纹一致才允许清
          var cur = pdxfTunePipeById(+id);
          if (!cur || ptsPayload(cur) + '|' + valvePayload(+id) === payload)
            delete pdxfTune.dirty[id];
        }
      });
    });
  }, Promise.resolve());
  var done = chain.then(function () {
    if (err) {
      if (!opts.silent) alert('保存失败：' + err + '\n未保存的修改已保留，可重试');
      else pdxfTunePanel();   // 静默失败也给出可见的待保存状态
      return -1;
    }
    // 注意：不清撤销栈——保存后仍可「撤销」回保存前的位置（再保存即回退落库）
    // 成功不弹窗：面板会切到「已保存 ✓」状态
    if (!opts.noReload) pdxfLoadEditData();
    return ids.length;
  }).catch(function () {
    if (!opts.silent) alert('保存失败（网络错误），修改仍在，可重试');
    else pdxfTunePanel();
    return -1;
  });
  pdxfTune._saving = done.then(function (n) { pdxfTune._saving = null; return n; });
  return pdxfTune._saving;
}
function pdxfTuneSave() { return pdxfTuneSaveAll(); }

// ── 面板 ──────────────────────────────────────────────────────────────
function pdxfTunePanel() {
  var body = document.getElementById('pdxfEditBody');
  var dirtyN = Object.keys(pdxfTune.dirty).length;
  // 点选模式（复制变换）优先渲染
  if (pdxfTune.multi.on) {
    var nPick = Object.keys(pdxfTune.multi.ids).length;
    body.innerHTML =
      '<div style="font-size:.84rem;line-height:1.6;"><b>复制变换 → 点选目标线</b><br>' +
      '<span style="color:#888;">在地图上点选要应用相同变换（绕同一锚点）的管道，选中变紫。</span></div>' +
      '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">' +
      '<button type="button" class="pdxf-btn pdxf-btn-primary" onclick="pdxfTuneMultiApply()">应用到选中的 ' + nPick + ' 条</button>' +
      '<button type="button" class="pdxf-btn" onclick="pdxfTuneMultiEnd()">取消</button></div>';
    return;
  }
  if (!pdxfTune.on && !dirtyN) return;
  if (!pdxfTune.on) {   // 已退出但还有未落库的修改（保存中/失败兜底）
    body.innerHTML =
      '<div style="font-size:.84rem;">有 <b>' + dirtyN + '</b> 条管道的精调修改待落库</div>' +
      '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">' +
      '<button type="button" class="pdxf-btn" onclick="pdxfTuneUndo()"' + (pdxfTune.undo.length ? '' : ' disabled') + '>撤销 (' + pdxfTune.undo.length + ')</button>' +
      '<button type="button" class="pdxf-btn pdxf-btn-primary" onclick="pdxfTuneSave()">立即保存</button></div>';
    return;
  }
  var p = pdxfTunePipe();
  var nGroup = pdxfTuneGroupIds().length;
  var pickRow =
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:.8rem;">' +
    '<span style="color:#666;">选择目标：</span>' +
    '<label style="cursor:pointer;"><input type="radio" name="pdxfPickTarget" value="all"' +
    (pdxfEditPickTarget === 'all' ? ' checked' : '') + ' onchange="pdxfSetPickTarget(\'all\')"> 全部</label>' +
    '<label style="cursor:pointer;"><input type="radio" name="pdxfPickTarget" value="pipes"' +
    (pdxfEditPickTarget === 'pipes' ? ' checked' : '') + ' onchange="pdxfSetPickTarget(\'pipes\')"> 仅管道</label>' +
    '<span style="color:#999;font-size:.72rem;">（阀门太密点不中线时切「仅管道」）</span></div>';
  var title = nGroup === 0 ? '点选要精调的管道（已选 0 条）'
    : nGroup > 1 ? '成组精调中：' + nGroup + ' 条线（刚体）'
    : '精调中：' + pdxfEsc(p ? p.name : '');
  var hint = nGroup === 0
    ? '点地图上的管道加入（<b>可连点多条成组</b>），或 <b>Shift+拖拽拉框批量选</b>；拖动任意已选线即开始调整。'
    : nGroup > 1
      ? '拖<b>任一线</b>=整组平移 · 拖<b>任一端点白点</b>=整组旋转+比例 · 组内接口始终不脱开。<b>点组外的线=加入，点组内的线=移出</b>（Shift+拖拽可拉框加线）；边界端点松手后 2m 内自动吸附组外的线'
      : '拖<b>线中段</b>=平移 · 拖<b>两端白点</b>=旋转+比例（另一端锚定） · 拖<b>绿点</b>=阀门沿线滑动。<b>点其他管道=加入成组一起调</b>（Shift+拖拽可拉框加线），点本线=移出；端点松手后 2m 内自动吸附相邻管道';
  body.innerHTML =
    pickRow +
    '<div style="font-size:.84rem;line-height:1.7;">' +
    '<b style="color:#e67e22;">⚙ ' + title + '</b><br>' +
    '<span style="color:#888;">' + hint + '</span></div>' +
    '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">' +
    '<button type="button" class="pdxf-btn' + (pdxfTuneBox.mode ? ' pdxf-btn-primary' : '') + '" onclick="pdxfTuneBoxToggle()">⬚ 框选' + (pdxfTuneBox.mode ? ' 已开（拖拽=拉框）' : '') + '</button>' +
    '<button type="button" class="pdxf-btn" onclick="pdxfTuneUndo()"' + (pdxfTune.undo.length ? '' : ' disabled') + '>撤销 (' + pdxfTune.undo.length + ')</button>' +
    '<button type="button" class="pdxf-btn" onclick="pdxfTuneMultiStart()"' + (pdxfTune.lastXform ? '' : ' disabled') + '>复制变换到其他线…</button>' +
    (dirtyN ? '<button type="button" class="pdxf-btn pdxf-btn-primary" onclick="pdxfTuneSave()">保存修改 (' + dirtyN + ')</button>' : '<span style="font-size:.76rem;color:#2D6A4F;align-self:center;">已保存 ✓</span>') +
    '</div>' +
    '<div class="pdxf-hint" style="margin-top:6px;">关掉右上角 🔧 会自动保存未保存的修改；撤销可回退到手势前（保存过也能继续撤）。</div>';
}
