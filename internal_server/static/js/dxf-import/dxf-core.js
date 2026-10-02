/* Guided CAD import. Original drawing coordinates and satellite coordinates stay separate. */
var pdxfData = null,
  pdxfToken = null,
  pdxfFile = null,
  pdxfStep = 1,
  pdxfImported = false,
  pdxfBusy = false;
var pdxfMap = null,
  pdxfCadMap = null,
  pdxfLayers = {},
  pdxfCadLayers = {},
  pdxfPreviewPane = null,
  pdxfPreviewRenderer = null;
var pdxfRefLayer = null,
  pdxfDbChanged = false,
  pdxfCalInfo = window.__DXF__.cal,
  pdxfDraftFit = null,
  pdxfAlignmentDirty = false;
var pdxfBatchMode = false,
  pdxfEdit = null;
var pdxfCal = {
  on: false,
  phase: "cad",
  pairs: [],
  pending: null,
  markers: null,
  cadMarkers: null,
};
var pdxfColorOf = {},
  pdxfLegendCtl = null;
var LAYER_COLORS = [
  "#2383ac",
  "#cc514a",
  "#499154",
  "#8870b7",
  "#d39342",
  "#5d98aa",
  "#bc657e",
  "#29897d",
];
var VALVE_LABELS = {
  solenoid: "电磁阀",
  gate: "闸阀",
  angle: "角阀",
  washdown: "冲洗阀",
  qcv: "取水阀",
  pullbox: "拉线箱",
};
var LINE_TYPE_LABELS = {
  irrigation: "灌溉管",
  flush: "冲洗管",
  toilet: "冲厕管",
  casing: "过路套管",
  control: "控制线",
  comm: "通讯线",
};
function pdxfEl(id) {
  return document.getElementById(id);
}
function pdxfEsc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
    return {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c];
  });
}
function pdxfCsrf() {
  var m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? m[1] : "";
}
function pdxfStatus(id, message, error) {
  var el = pdxfEl(id);
  el.textContent = message || "";
  el.classList.toggle("error", !!error);
}
function pdxfPost(url, body) {
  return fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": pdxfCsrf() },
    body: body,
  })
    .then(function (r) {
      return r.json();
    })
    .then(function (d) {
      if (!d.success) throw new Error(d.error || "操作失败，请重试");
      return d;
    });
}
function pdxfReady() {
  return !!(
    pdxfData &&
    pdxfData.alignment &&
    pdxfData.alignment.ready &&
    !pdxfAlignmentDirty
  );
}
function pdxfToggle(id) {
  pdxfEl(id).classList.toggle("open");
}
function pdxfGoStep(n) {
  if (pdxfBusy) return;
  if (n < 1 || n > 4) return;
  if (n > 1 && !pdxfData) return;
  if (n === 2 && pdxfBatchMode) return;
  if (n === 4 && (!pdxfReady() || pdxfBatchMode)) return;
  if (pdxfCal.on && n !== 3) pdxfCalStop();
  pdxfStep = n;
  document.querySelectorAll("[data-step]").forEach(function (el) {
    el.hidden = Number(el.dataset.step) !== n;
  });
  for (var i = 1; i <= 4; i++) {
    pdxfEl("pdxfStep" + i).classList.toggle("on", i === n);
    pdxfEl("pdxfStep" + i).setAttribute(
      "aria-current",
      i === n ? "step" : "false",
    );
  }
  pdxfEl("pdxfBackBtn").hidden = n === 1;
  pdxfEl("pdxfNextBtn").hidden = n === 4 || pdxfImported || pdxfBatchMode;
  document.querySelector(".pdxf-panels").scrollTop = 0;
  if (n === 4) pdxfRenderReview();
  pdxfUpdateWorkflow();
  pdxfCadMap.invalidateSize();
  pdxfMap.invalidateSize();
}
function pdxfSetStep(n) {
  pdxfGoStep(n);
}
function pdxfUpdateWorkflow() {
  var specs = pdxfData
    ? pdxfCollectSpecs()
    : { layers: {}, blocks: {}, labelLayers: [] };
  var selected = Object.values(specs.layers).some(function (s) {
    return s.include;
  });
  var ready = pdxfReady();
  pdxfEl("pdxfStep1").disabled = pdxfBusy;
  pdxfEl("pdxfStep2").disabled = pdxfBusy || !pdxfData || pdxfBatchMode;
  pdxfEl("pdxfStep3").disabled = pdxfBusy || !pdxfData;
  pdxfEl("pdxfStep4").disabled =
    pdxfBusy || !ready || !selected || pdxfBatchMode;
  pdxfEl("pdxfBackBtn").disabled = pdxfBusy;
  pdxfEl("pdxfFile").disabled = pdxfBusy;
  pdxfEl("pdxfCalBatch").disabled = pdxfBusy;
  document
    .querySelectorAll(
      "#pdxfMapCard input, #pdxfMapCard select, #pdxfCalCard input",
    )
    .forEach(function (el) {
      el.disabled = pdxfBusy;
    });
  pdxfEl("pdxfReviewSummary").hidden = pdxfImported;
  pdxfEl("pdxfReviewConfirmed").parentElement.hidden = pdxfImported;
  pdxfEl("pdxfImportBtn").hidden = pdxfImported;
  pdxfEl("pdxfReviewTitle").textContent = pdxfImported
    ? "导入完成"
    : "检查并导入";
  pdxfEl("pdxfImportCard").querySelector(".pdxf-hint").textContent =
    pdxfImported
      ? "管线、设备与完整原图已保留。可前往地图处理待挂接设备。"
      : "核对卫星图中的位置与所选内容，再创建管网。";
  pdxfEl("pdxfNextBtn").disabled =
    pdxfBusy ||
    pdxfImported ||
    !pdxfData ||
    (pdxfStep === 2 && !selected) ||
    (pdxfStep === 3 && !ready);
  pdxfEl("pdxfImportBtn").disabled =
    pdxfBusy ||
    pdxfImported ||
    !ready ||
    !selected ||
    !pdxfEl("pdxfReviewConfirmed").checked;
  pdxfEl("pdxfNextBtn").textContent =
    pdxfStep === 2
      ? "下一步：对齐位置"
      : pdxfStep === 3
        ? "下一步：检查并导入"
        : "下一步";
  pdxfEl("pdxfWorkflowHint").textContent = pdxfImported
    ? "导入完成，待挂接设备已保留"
    : pdxfStep === 1
      ? "先上传并解析图纸"
      : pdxfStep === 2
        ? "未选择的原图内容仍会保留作参考"
        : pdxfStep === 3
          ? ready
            ? "对齐与独立检查已通过"
            : "至少 3 个对齐点 + 1 个独立检查点"
          : "勾选确认后创建管网";
  pdxfPlacementControls();
}
function pdxfFileChanged() {
  if (pdxfBusy) return;
  pdxfFile = pdxfEl("pdxfFile").files[0] || null;
  pdxfInvalidateDrawing();
  pdxfEl("pdxfFileInfo").hidden = !pdxfFile;
  pdxfEl("pdxfFileInfo").textContent = pdxfFile
    ? pdxfFile.name + " · " + (pdxfFile.size / 1024 / 1024).toFixed(2) + " MB"
    : "";
  pdxfEl("pdxfAnalyzeBtn").disabled = !pdxfFile;
  pdxfStatus("pdxfAnalyzeStatus", "");
}
function pdxfInvalidateDrawing() {
  if (pdxfCal.on) pdxfCalStop();
  pdxfData = null;
  pdxfToken = null;
  pdxfBatchMode = false;
  pdxfImported = false;
  pdxfDraftFit = null;
  pdxfAlignmentDirty = false;
  pdxfCal.pairs = [];
  pdxfCal.pending = null;
  pdxfPlacementReset();
  document.querySelector(
    'input[name="pdxfPickRole"][value="control"]',
  ).checked = true;
  ["pdxfPointX", "pdxfPointY", "pdxfPointLat", "pdxfPointLng"].forEach(
    function (id) {
      pdxfEl(id).value = "";
    },
  );
  document.querySelector(".pdxf-coordinates").open = false;
  pdxfEl("pdxfReviewConfirmed").checked = false;
  if (pdxfCadMap) {
    pdxfClearGroups(pdxfCadMap, pdxfCadLayers);
    pdxfCadLayers = {};
    pdxfClearGroups(pdxfMap, pdxfLayers);
    pdxfLayers = {};
    pdxfCalDrawMarkers();
  }
  pdxfEl("pdxfCadEmpty").hidden = false;
  pdxfEl("pdxfDrawingName").textContent = "CAD 原图与地图";
  pdxfEl("pdxfMapStatus").textContent = "等待上传图纸";
  pdxfEl("pdxfSatelliteHint").textContent = "解析后先显示初步叠图，再选点对齐";
  pdxfEl("pdxfResultBox").innerHTML = "";
  pdxfEl("pdxfImportBtn").textContent = "确认导入管网";
  pdxfGoStep(1);
}
function pdxfRings(bp) {
  if (!bp || !bp.length) return [];
  if (!Array.isArray(bp[0]))
    return [
      bp
        .filter(function (p) {
          return p && p.lat !== undefined;
        })
        .map(function (p) {
          return [p.lat, p.lng];
        }),
    ];
  return bp.reduce(function (a, r) {
    return a.concat(pdxfRings(r));
  }, []);
}
function pdxfInitMap() {
  pdxfMap = L.map("pdxfMap", { preferCanvas: true }).setView(
    [31.143, 121.658],
    17,
  );
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "&copy; Esri", maxNativeZoom: 19, maxZoom: 22 },
  ).addTo(pdxfMap);
  pdxfCadMap = L.map("pdxfCadMap", {
    crs: L.CRS.Simple,
    preferCanvas: true,
    minZoom: -12,
    maxZoom: 6,
  }).setView([0, 0], 0);
  pdxfPreviewPane = pdxfMap.createPane("pdxfPreview");
  pdxfPreviewPane.style.zIndex = 450;
  pdxfPreviewPane.style.pointerEvents = "none";
  pdxfPreviewRenderer = L.canvas({ pane: "pdxfPreview" });
  pdxfRefLayer = L.layerGroup();
  var bounds = [];
  (window.__DXF__.zones || []).forEach(function (z) {
    pdxfRings(z.boundary_points).forEach(function (ring) {
      if (ring.length < 3) return;
      bounds = bounds.concat(ring);
      L.polygon(ring, {
        weight: 1,
        color: "#528467",
        fillOpacity: 0.02,
        interactive: false,
      }).addTo(pdxfMap);
    });
  });
  (window.__DXF__.pipelines || []).forEach(function (p) {
    var ll = (p.line_points || [])
      .filter(function (pt) {
        return pt && pt.lat !== undefined;
      })
      .map(function (pt) {
        return [pt.lat, pt.lng];
      });
    if (ll.length < 2) return;
    bounds = bounds.concat(ll);
    L.polyline(ll, {
      color: "#97a5ac",
      weight: 2,
      opacity: 0.65,
      dashArray: "5 5",
      interactive: false,
    }).addTo(pdxfRefLayer);
  });
  if (bounds.length) pdxfMap.fitBounds(L.latLngBounds(bounds).pad(0.1));
  pdxfCadMap.on("click", pdxfCalCadClick);
  pdxfMap.on("click", pdxfCalSatClick);
  pdxfCadMap.on("zoomend", function () {
    if (pdxfData && pdxfEl("pdxfShowNotes").checked) pdxfRefreshMap();
  });
  pdxfMap.on("zoomend", function () {
    if (pdxfData && pdxfEl("pdxfShowNotes").checked) pdxfRefreshMap();
  });
  window.addEventListener("resize", function () {
    pdxfMap.invalidateSize();
    pdxfCadMap.invalidateSize();
  });
  var drop = pdxfEl("pdxfDropZone");
  ["dragenter", "dragover"].forEach(function (name) {
    drop.addEventListener(name, function (e) {
      e.preventDefault();
      drop.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (name) {
    drop.addEventListener(name, function (e) {
      e.preventDefault();
      drop.classList.remove("dragover");
    });
  });
  drop.addEventListener("drop", function (e) {
    if (pdxfBusy) return;
    if (!e.dataTransfer.files.length) return;
    pdxfEl("pdxfFile").files = e.dataTransfer.files;
    pdxfFileChanged();
  });
  pdxfCalRenderCurrent();
  pdxfUpdateWorkflow();
}
function pdxfAnalyze() {
  if (pdxfBusy) return;
  if (!pdxfFile || !pdxfFile.name.toLowerCase().endsWith(".dxf")) {
    pdxfStatus("pdxfAnalyzeStatus", "请选择 .dxf 文件", true);
    return;
  }
  pdxfBusy = true;
  pdxfUpdateWorkflow();
  pdxfEl("pdxfAnalyzeBtn").disabled = true;
  pdxfEl("pdxfAnalyzeBtn").textContent = "正在解析…";
  pdxfStatus("pdxfAnalyzeStatus", "正在提取管线、设备和完整标注…");
  var fd = new FormData();
  fd.append("file", pdxfFile);
  pdxfPost(window.__DXF__.urls.analyze, fd)
    .then(function (d) {
      pdxfData = d;
      pdxfToken = d.token;
      pdxfCalInfo = d.calibration;
      pdxfPlacementSeed();
      pdxfDbChanged = false;
      pdxfEl("pdxfDrawingName").textContent = pdxfFile.name;
      pdxfEl("pdxfCadEmpty").hidden = true;
      pdxfRenderTables();
      pdxfRenderDiagnostics(d);
      pdxfCalSeed();
      pdxfRefreshMap();
      pdxfFitDrawing();
      pdxfBusy = false;
      pdxfGoStep(2);
    })
    .catch(function (err) {
      pdxfStatus("pdxfAnalyzeStatus", err.message || "网络错误，请重试", true);
    })
    .finally(function () {
      pdxfBusy = false;
      pdxfEl("pdxfAnalyzeBtn").disabled = false;
      pdxfEl("pdxfAnalyzeBtn").textContent = "解析并叠到地图";
      pdxfUpdateWorkflow();
    });
}
function pdxfRenderTables() {
  var pipes = pdxfData.layers.filter(function (l) {
    return !l.layer.startsWith("块·");
  });
  pdxfData.layers.forEach(function (l, i) {
    pdxfColorOf[l.layer] = LAYER_COLORS[i % LAYER_COLORS.length];
  });
  pdxfEl("pdxfLayerBody").innerHTML = pipes
    .map(function (l) {
      var name = pdxfEsc(l.layer);
      return (
        '<tr data-filter="' +
        name.toLowerCase() +
        '"><td><input aria-label="导入图层 ' +
        name +
        '" type="checkbox" class="pdxf-layer-include" data-layer="' +
        name +
        '"' +
        (l.include_guess ? " checked" : "") +
        ' onchange="pdxfMappingChanged()"></td><td><button class="pdxf-layer-name" onclick="pdxfZoomLayer(this.dataset.layer)" data-layer="' +
        name +
        '"><span class="pdxf-sw" style="background:' +
        pdxfColorOf[l.layer] +
        '"></span>' +
        name +
        '</button><span class="pdxf-sub">' +
        l.segments +
        ' 段</span></td><td><input aria-label="' +
        name +
        ' 管径毫米" type="number" min="1" step="any" class="pdxf-input pdxf-layer-dia" data-layer="' +
        name +
        '" value="' +
        (l.diameter_guess || "") +
        '" onchange="pdxfMappingChanged()"></td><td><select aria-label="' +
        name +
        ' 管线用途" class="pdxf-select pdxf-layer-type" data-layer="' +
        name +
        '" onchange="pdxfMappingChanged()">' +
        Object.keys(LINE_TYPE_LABELS)
          .map(function (t) {
            return (
              '<option value="' +
              t +
              '"' +
              (l.type_guess === t ? " selected" : "") +
              ">" +
              LINE_TYPE_LABELS[t] +
              "</option>"
            );
          })
          .join("") +
        "</select></td></tr>"
      );
    })
    .join("");
  pdxfEl("pdxfBlockBody").innerHTML = pdxfData.blocks
    .map(function (b) {
      var name = pdxfEsc(b.block);
      return (
        '<tr data-filter="' +
        name.toLowerCase() +
        '"><td><input aria-label="导入设备 ' +
        name +
        '" type="checkbox" class="pdxf-block-include" data-block="' +
        name +
        '"' +
        (b.include_guess ? " checked" : "") +
        ' onchange="pdxfMappingChanged()"></td><td>' +
        name +
        '<span class="pdxf-sub">' +
        b.count +
        " 个" +
        (b.attrs.length ? " · " + pdxfEsc(b.attrs.join(", ")) : "") +
        '</span></td><td><select aria-label="' +
        name +
        ' 设备类型" class="pdxf-select pdxf-block-type" data-block="' +
        name +
        '" onchange="pdxfMappingChanged()">' +
        Object.keys(VALVE_LABELS)
          .map(function (t) {
            return (
              '<option value="' +
              t +
              '"' +
              (b.valve_type_guess === t ? " selected" : "") +
              ">" +
              VALVE_LABELS[t] +
              "</option>"
            );
          })
          .join("") +
        "</select></td></tr>"
      );
    })
    .join("");
  pdxfEl("pdxfLabelBox").innerHTML = pdxfData.labels
    .map(function (l, i) {
      var name = pdxfEsc(l.layer);
      return (
        '<label data-filter="' +
        name.toLowerCase() +
        '"><input type="checkbox" class="pdxf-label-use" data-layer="' +
        name +
        '"' +
        (l.layer === "设备编号" || i === 0 ? " checked" : "") +
        ' onchange="pdxfMappingChanged()"> ' +
        name +
        '<span class="pdxf-sub">' +
        l.count +
        " 条 · 如 " +
        pdxfEsc(l.samples[0] || "") +
        "</span></label>"
      );
    })
    .join("");
  pdxfEl("pdxfSymbolHint").textContent =
    pdxfData.layers.length -
    pipes.length +
    " 个块符号图层保留为 CAD 参考，不作为水管导入。";
  pdxfEl("pdxfPipeTab").textContent = "管线 " + pipes.length;
  pdxfEl("pdxfDeviceTab").textContent = "设备 " + pdxfData.blocks.length;
  pdxfEl("pdxfNoteTab").textContent = "标注 " + pdxfData.labels.length;
  pdxfEl("pdxfMappingSearch").value = "";
  pdxfMappingTab("pipes");
  pdxfMappingChanged();
}
function pdxfMappingTab(tab) {
  ["pipes", "devices", "notes"].forEach(function (key, i) {
    pdxfEl(["pdxfPipePanel", "pdxfDevicePanel", "pdxfNotePanel"][i]).hidden =
      key !== tab;
    pdxfEl(["pdxfPipeTab", "pdxfDeviceTab", "pdxfNoteTab"][i]).setAttribute(
      "aria-selected",
      key === tab ? "true" : "false",
    );
  });
  pdxfFilterMapping();
}
function pdxfFilterMapping() {
  var value = pdxfEl("pdxfMappingSearch").value.trim().toLowerCase();
  document.querySelectorAll("[data-filter]").forEach(function (el) {
    el.hidden = !el.dataset.filter.includes(value);
  });
}
function pdxfCollectSpecs() {
  var layers = {},
    blocks = {};
  document.querySelectorAll(".pdxf-layer-include").forEach(function (cb) {
    layers[cb.dataset.layer] = { include: cb.checked };
  });
  document.querySelectorAll(".pdxf-layer-dia").forEach(function (el) {
    if (layers[el.dataset.layer]) layers[el.dataset.layer].diameter = el.value;
  });
  document.querySelectorAll(".pdxf-layer-type").forEach(function (el) {
    if (layers[el.dataset.layer]) layers[el.dataset.layer].type = el.value;
  });
  document.querySelectorAll(".pdxf-block-include").forEach(function (cb) {
    blocks[cb.dataset.block] = { include: cb.checked };
  });
  document.querySelectorAll(".pdxf-block-type").forEach(function (el) {
    if (blocks[el.dataset.block])
      blocks[el.dataset.block].valve_type = el.value;
  });
  return {
    layers: layers,
    blocks: blocks,
    labelLayers: Array.from(
      document.querySelectorAll(".pdxf-label-use:checked"),
    ).map(function (cb) {
      return cb.dataset.layer;
    }),
  };
}
function pdxfSelectionCounts() {
  var specs = pdxfCollectSpecs(),
    count = {
      layers: 0,
      paths: 0,
      devices: 0,
      labels: pdxfData.coverage.labels,
    };
  pdxfData.layers.forEach(function (l) {
    if (specs.layers[l.layer] && specs.layers[l.layer].include) {
      count.layers++;
      count.paths += l.segments;
    }
  });
  pdxfData.blocks.forEach(function (b) {
    if (specs.blocks[b.block] && specs.blocks[b.block].include)
      count.devices += b.count;
  });
  return count;
}
function pdxfMappingChanged() {
  if (!pdxfData) return;
  pdxfEl("pdxfReviewConfirmed").checked = false;
  var c = pdxfSelectionCounts();
  pdxfEl("pdxfSelectionSummary").innerHTML =
    "<span><b>" +
    c.layers +
    "</b> 个管线图层</span><span><b>" +
    c.paths +
    "</b> 段源线</span><span><b>" +
    c.devices +
    "</b> 个设备候选</span><span><b>" +
    c.labels +
    "</b> 条标注保留</span>";
  pdxfRefreshMap();
  pdxfUpdateWorkflow();
}
function pdxfClearGroups(map, groups) {
  Object.values(groups).forEach(function (g) {
    if (map.hasLayer(g)) map.removeLayer(g);
  });
}
function pdxfGeographic(point) {
  if (pdxfReady() && typeof point.lat === "number")
    return [point.lat, point.lng];
  return pdxfProjectPoint(pdxfOverlayFit(), point);
}
function pdxfRefreshMap() {
  if (!pdxfMap || !pdxfData) return;
  pdxfClearGroups(pdxfCadMap, pdxfCadLayers);
  pdxfCadLayers = {};
  pdxfClearGroups(pdxfMap, pdxfLayers);
  pdxfLayers = {};
  var specs = pdxfCollectSpecs(),
    reference = pdxfEl("pdxfShowReference").checked,
    devices = pdxfEl("pdxfShowDevices").checked,
    notes = pdxfEl("pdxfShowNotes").checked,
    opacity = Number(pdxfEl("pdxfOpacity").value) / 100;
  pdxfData.preview.layers.forEach(function (layer) {
    var selected = !!(
      specs.layers[layer.layer] && specs.layers[layer.layer].include
    );
    if (!selected && !reference) return;
    var raw = L.featureGroup().addTo(pdxfCadMap),
      geo = L.featureGroup().addTo(pdxfMap);
    layer.paths.forEach(function (path) {
      L.polyline(
        path.map(function (p) {
          return [p.dxf_y, p.dxf_x];
        }),
        {
          color: selected ? pdxfColorOf[layer.layer] : "#a1b8aa",
          weight: selected ? 2 : 1,
          opacity: selected ? 0.9 : 0.4,
          interactive: false,
        },
      ).addTo(raw);
      var ll = path.map(pdxfGeographic);
      if (ll.length && ll.every(Boolean))
        L.polyline(ll, {
          color: selected ? pdxfColorOf[layer.layer] : "#b9c7bd",
          weight: selected ? 3 : 1,
          opacity: selected ? opacity : 0.3,
          interactive: false,
          pane: "pdxfPreview",
          renderer: pdxfPreviewRenderer,
        }).addTo(geo);
    });
    pdxfCadLayers["layer:" + layer.layer] = raw;
    pdxfLayers["layer:" + layer.layer] = geo;
  });
  if (devices) {
    var raw = L.layerGroup().addTo(pdxfCadMap),
      geo = L.layerGroup().addTo(pdxfMap);
    pdxfData.preview.valves.forEach(function (v) {
      if (
        !(specs.blocks[v.block] && specs.blocks[v.block].include) &&
        !reference
      )
        return;
      var style = {
        radius: 3.5,
        color: "#ad6142",
        weight: 1.2,
        fillColor: "#fff",
        fillOpacity: 1,
        interactive: !pdxfCal.on,
      };
      L.circleMarker([v.dxf_y, v.dxf_x], style)
        .bindTooltip(pdxfEsc(v.block))
        .addTo(raw);
      var ll = pdxfGeographic(v);
      if (ll)
        L.circleMarker(
          ll,
          Object.assign({}, style, {
            pane: "pdxfPreview",
            renderer: pdxfPreviewRenderer,
          }),
        )
          .bindTooltip(pdxfEsc(v.block))
          .addTo(geo);
    });
    pdxfCadLayers.valves = raw;
    pdxfLayers.valves = geo;
  }
  if (notes) {
    var raw = L.layerGroup().addTo(pdxfCadMap),
      geo = L.layerGroup().addTo(pdxfMap);
    pdxfData.labels.forEach(function (layer) {
      layer.points.forEach(function (p) {
        var icon = L.divIcon({
          className: "",
          html:
            '<span class="pdxf-symbol-label">' +
            pdxfEsc(p.text.length > 28 ? p.text.slice(0, 28) + "…" : p.text) +
            "</span>",
        });
        var options = { icon: icon, interactive: !pdxfCal.on };
        if (pdxfCadMap.getZoom() >= 0)
          L.marker([p.dxf_y, p.dxf_x], options)
            .bindPopup(pdxfEsc(p.text).replace(/\n/g, "<br>"))
            .addTo(raw);
        var ll = pdxfGeographic(p);
        if (ll && pdxfMap.getZoom() >= 19)
          L.marker(ll, Object.assign({}, options, { pane: "pdxfPreview" }))
            .bindPopup(pdxfEsc(p.text).replace(/\n/g, "<br>"))
            .addTo(geo);
      });
    });
    pdxfCadLayers.notes = raw;
    pdxfLayers.notes = geo;
  }
  pdxfEl("pdxfMapStatus").textContent = pdxfBatchMode
    ? "重新定位所选批次"
    : pdxfReady()
      ? "位置已验证 · 可继续检查并导入"
      : pdxfCal.pairs.length
        ? "对齐草稿 · 尚未验证保存"
        : "初步叠图 · 位置待验证";
  pdxfToggleOverlay();
  pdxfCalDrawMarkers();
  pdxfCalStepMsg();
}
function pdxfFitDrawing() {
  if (!pdxfData) return;
  var geo = [];
  pdxfData.preview.layers.forEach(function (layer) {
    layer.paths.forEach(function (path) {
      path.forEach(function (p) {
        var ll = pdxfGeographic(p);
        if (ll) geo.push(ll);
      });
    });
  });
  if (pdxfEl("pdxfOriginalDialog").open) pdxfFitOriginal();
  if (geo.length) pdxfMap.fitBounds(L.latLngBounds(geo).pad(0.1));
}
function pdxfZoomLayer(name) {
  var group = pdxfCadLayers["layer:" + name];
  if (pdxfEl("pdxfOriginalDialog").open && group && group.getLayers().length)
    pdxfCadMap.fitBounds(group.getBounds().pad(0.15));
  var mapped = pdxfLayers["layer:" + name];
  if (mapped && mapped.getLayers().length)
    pdxfMap.fitBounds(mapped.getBounds().pad(0.15));
}
function pdxfRenderDiagnostics(data) {
  var c = data.coverage;
  pdxfEl("pdxfCoverage").textContent =
    "完整提取 " +
    c.paths +
    " 条线、" +
    c.blocks +
    " 个块、" +
    c.labels +
    " 条标注。";
  pdxfEl("pdxfCoordInfo").textContent =
    "图纸单位：" +
    ({ 0: "未声明", 1: "英寸", 2: "英尺", 4: "毫米", 5: "厘米", 6: "米" }[
      data.metadata.units
    ] || "代码 " + data.metadata.units) +
    "；位置需通过对应点验证。";
  var issues = data.metadata.diagnostics || [];
  pdxfEl("pdxfDiagnostics").innerHTML = issues.length
    ? "<p>" +
      issues.length +
      " 个实体未作为管线或标注解析：</p>" +
      issues
        .map(function (i) {
          return (
            "<p>" +
            pdxfEsc(i.source_id) +
            " · " +
            pdxfEsc(i.layer) +
            " · " +
            pdxfEsc(i.type) +
            "：" +
            pdxfEsc(i.reason) +
            "</p>"
          );
        })
        .join("")
    : "所有支持的实体已提取。";
}
function pdxfRenderReview() {
  if (!pdxfData) return;
  var c = pdxfSelectionCounts(),
    a = pdxfData.alignment;
  var rows = [
    ["图纸", pdxfFile ? pdxfFile.name : "所选批次"],
    ["管线", c.layers + " 层 · " + c.paths + " 段源线"],
    ["设备候选", c.devices + " 个，未匹配设备将保留"],
    ["完整标注", c.labels + " 条"],
    ["对齐点", a.control_count + " 个"],
    [
      "独立检查",
      a.check_count + " 个 · 最大误差 " + a.check_max_m.toFixed(2) + " m",
    ],
    ["拟合误差", a.rms_m.toFixed(2) + " m"],
  ];
  pdxfEl("pdxfReviewSummary").innerHTML = rows
    .map(function (r) {
      return (
        '<div class="pdxf-review-row"><span>' +
        r[0] +
        "</span><b>" +
        pdxfEsc(r[1]) +
        "</b></div>"
      );
    })
    .join("");
}
function pdxfImport() {
  if (
    !pdxfReady() ||
    pdxfBusy ||
    pdxfImported ||
    !pdxfEl("pdxfReviewConfirmed").checked
  )
    return;
  pdxfBusy = true;
  pdxfUpdateWorkflow();
  pdxfEl("pdxfImportBtn").textContent = "正在创建管网…";
  pdxfStatus("pdxfImportStatus", "正在创建管线与设备，保留原图及完整标注…");
  var specs = pdxfCollectSpecs(),
    fd = new FormData();
  if (pdxfFile) fd.append("file", pdxfFile);
  fd.append("token", pdxfToken);
  fd.append("preview_token", pdxfData.preview_token);
  fd.append("filename", pdxfFile ? pdxfFile.name : "DXF导入");
  fd.append("layers_json", JSON.stringify(specs.layers));
  fd.append("blocks_json", JSON.stringify(specs.blocks));
  fd.append("label_layers", JSON.stringify(specs.labelLayers));
  pdxfPost(window.__DXF__.urls.importSubmit, fd)
    .then(function (d) {
      pdxfImported = true;
      pdxfEdit = null;
      pdxfEl("pdxfImportBtn").textContent = "已导入";
      pdxfStatus("pdxfImportStatus", "导入完成。原图和未挂接设备已保留。");
      var option = document.createElement("option");
      option.value = d.batch_id;
      option.textContent = pdxfFile ? pdxfFile.name : "本次导入";
      option.dataset.token = pdxfToken;
      pdxfEl("pdxfCalBatch").appendChild(option);
      pdxfEl("pdxfCalBatch").value = d.batch_id;
      pdxfEl("pdxfResultBox").innerHTML =
        '<div class="pdxf-result"><b>管网已创建</b><p>' +
        d.pipelines +
        " 条管线 · " +
        d.valves +
        " 个已挂接设备<br>" +
        d.skipped_valves +
        " 个设备保留待挂接 · " +
        pdxfData.coverage.labels +
        ' 条完整标注保留</p><a href="' +
        window.__DXF__.urls.dashboard +
        '" target="_blank">查看地图与待挂接设备 →</a><p><button class="pdxf-btn pdxf-btn-secondary" onclick="pdxfNewImport()">导入另一张图纸</button></p></div>';
      pdxfRenderImportIssues(d);
      document.querySelector(".pdxf-panels").scrollTop = 0;
    })
    .catch(function (err) {
      pdxfStatus("pdxfImportStatus", err.message || "导入失败，请重试", true);
      pdxfEl("pdxfImportBtn").textContent = "重试导入";
    })
    .finally(function () {
      pdxfBusy = false;
      pdxfUpdateWorkflow();
    });
}
function pdxfNewImport() {
  pdxfEl("pdxfFile").value = "";
  pdxfFileChanged();
}
function pdxfRenderImportIssues(data) {
  var items = data.unmatched_valves || [];
  if (!items.length) return;
  var box = document.createElement("details");
  box.className = "pdxf-issues";
  box.innerHTML =
    "<summary>" + items.length + " 个设备待挂接 · 点击定位查看</summary>";
  items.forEach(function (item) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "pdxf-btn pdxf-btn-secondary";
    button.textContent =
      item.block + " · " + item.source_id + "：" + item.reason;
    button.onclick = function () {
      var p = pdxfData.preview.valves.find(function (v) {
        return v.source_id === item.source_id;
      });
      if (p) {
        pdxfCadMap.setView([p.dxf_y, p.dxf_x], 3);
        var ll = pdxfGeographic(p);
        if (ll) pdxfMap.setView(ll, 21);
      }
    };
    box.appendChild(button);
  });
  pdxfEl("pdxfResultBox").appendChild(box);
}
function pdxfBatchChanged() {
  if (pdxfBatchMode) pdxfInvalidateDrawing();
}
function pdxfLoadBatch() {
  if (pdxfBusy) return;
  var id = pdxfEl("pdxfCalBatch").value;
  if (!id) {
    pdxfStatus("pdxfAnalyzeStatus", "请选择导入批次", true);
    return;
  }
  pdxfBusy = true;
  pdxfUpdateWorkflow();
  pdxfStatus("pdxfAnalyzeStatus", "正在加载原始 CAD 坐标…");
  fetch(window.__DXF__.urls.editData + "?batch_id=" + encodeURIComponent(id), {
    credentials: "same-origin",
  })
    .then(function (r) {
      return r.json();
    })
    .then(function (d) {
      if (!d.success || !d.cad_source)
        throw new Error("该旧批次没有保留原图，请重新上传原始 DXF。");
      pdxfInvalidateDrawing();
      pdxfBatchMode = true;
      pdxfEdit = d;
      pdxfCalInfo = d.batch_calibrations[id];
      var source = d.cad_source;
      var options = d.cad_options || {};
      var layers = Object.keys(source.layers || {}).map(function (name) {
        var bucket = source.layers[name];
        var spec = (options.layers || {})[name] || {};
        return {
          layer: name,
          segments: bucket.polys.length,
          include_guess: !!spec.include,
          type_guess: spec.type || "irrigation",
          diameter_guess: spec.diameter || null,
        };
      });
      var names = {};
      (source.valves || []).forEach(function (v) {
        names[v.block] = (names[v.block] || 0) + 1;
      });
      var blocks = Object.keys(names).map(function (name) {
        var spec = (options.blocks || {})[name] || {};
        return {
          block: name,
          count: names[name],
          attrs: [],
          include_guess: !!spec.include,
          valve_type_guess: spec.valve_type || "solenoid",
        };
      });
      var labels = {};
      (source.labels || []).forEach(function (lb) {
        (labels[lb.layer] || (labels[lb.layer] = [])).push({
          dxf_x: lb.x,
          dxf_y: lb.y,
          text: lb.text,
        });
      });
      pdxfData = {
        calibration: pdxfCalInfo,
        alignment: pdxfCalInfo.alignment,
        metadata: source.metadata || { units: 0, diagnostics: [] },
        layers: layers,
        blocks: blocks,
        labels: Object.keys(labels).map(function (name) {
          return {
            layer: name,
            count: labels[name].length,
            samples: [labels[name][0].text],
            points: labels[name],
          };
        }),
        coverage: {
          paths: layers.reduce(function (n, l) {
            return n + l.segments;
          }, 0),
          blocks: (source.valves || []).length,
          labels: (source.labels || []).length,
        },
        preview: {
          layers: layers.map(function (l) {
            return {
              layer: l.layer,
              paths: source.layers[l.layer].polys.map(function (path) {
                return path.map(function (p) {
                  return { dxf_x: p[0], dxf_y: p[1] };
                });
              }),
            };
          }),
          valves: (source.valves || []).map(function (v) {
            return {
              block: v.block,
              dxf_x: v.x,
              dxf_y: v.y,
              source_id: v.source_id,
            };
          }),
        },
      };
      pdxfEl("pdxfDrawingName").textContent =
        pdxfEl("pdxfCalBatch").selectedOptions[0].textContent;
      pdxfEl("pdxfCadEmpty").hidden = true;
      pdxfPlacementSeed();
      pdxfRenderTables();
      document.querySelectorAll(".pdxf-label-use").forEach(function (input) {
        input.checked =
          !options.label_layers ||
          options.label_layers.includes(input.dataset.layer);
      });
      pdxfCalSeed();
      pdxfRefreshMap();
      pdxfFitDrawing();
      pdxfBusy = false;
      pdxfGoStep(3);
      pdxfStatus("pdxfCalStatus", "对齐完成后只应用到所选批次。");
    })
    .catch(function (err) {
      pdxfStatus("pdxfAnalyzeStatus", err.message, true);
    })
    .finally(function () {
      pdxfBusy = false;
      pdxfUpdateWorkflow();
    });
}

function pdxfRefreshRefPipelines() {
  fetch(window.__DXF__.urls.editData, { credentials: "same-origin" })
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      if (!data.success) return;
      pdxfRefLayer.clearLayers();
      data.pipelines.forEach(function (pipe) {
        var line = (pipe.line_points || []).map(function (p) {
          return [p.lat, p.lng];
        });
        if (line.length > 1)
          L.polyline(line, {
            color: "#97a5ac",
            weight: 2,
            opacity: 0.65,
            dashArray: "5 5",
            interactive: false,
          }).addTo(pdxfRefLayer);
      });
    })
    .catch(function () {
      pdxfStatus(
        "pdxfCalStatus",
        "坐标已更新，但参照层刷新失败；请刷新页面查看。",
        true,
      );
    });
}

function pdxfShowExisting() {
  if (pdxfEl("pdxfShowExisting").checked) pdxfRefLayer.addTo(pdxfMap);
  else pdxfMap.removeLayer(pdxfRefLayer);
}
