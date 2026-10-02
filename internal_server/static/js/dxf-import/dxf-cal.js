/* One alignment workflow: similarity with three or more controls and independent checks. */
function pdxfCalLimit() {
  return (
    (pdxfCalInfo && pdxfCalInfo.alignment && pdxfCalInfo.alignment.limit_m) || 5
  );
}
function pdxfCalRenderCurrent() {
  var info = pdxfCalInfo || {},
    ready = info.alignment && info.alignment.ready;
  var el = pdxfEl("pdxfCalCurrent");
  el.className = "pdxf-note " + (ready ? "success" : "warning");
  el.textContent = ready
    ? "已保存对齐：" +
      info.alignment.control_count +
      " 个对齐点 · " +
      info.alignment.check_count +
      " 个独立检查点，最大误差 " +
      info.alignment.check_max_m.toFixed(2) +
      " m。"
    : "尚未验证定位。" +
      ((info.alignment && info.alignment.error) ||
        "请在 CAD 叠图与卫星底图中选择对应点。");
  pdxfEl("pdxfAccuracyLimit").textContent = pdxfCalLimit();
}
function pdxfCalSeed() {
  pdxfCalStop();
  pdxfCal.pairs = [];
  pdxfCal.pending = null;
  pdxfDraftFit = null;
  pdxfAlignmentDirty = false;
  if (pdxfCalInfo && pdxfCalInfo.alignment && pdxfCalInfo.alignment.ready) {
    (pdxfCalInfo.points || []).forEach(function (p) {
      pdxfCal.pairs.push({
        dxfX: p.dxf_x,
        dxfY: p.dxf_y,
        satLat: p.lat,
        satLng: p.lng,
        role: "control",
      });
    });
    (pdxfCalInfo.check_points || []).forEach(function (p) {
      pdxfCal.pairs.push({
        dxfX: p.dxf_x,
        dxfY: p.dxf_y,
        satLat: p.lat,
        satLng: p.lng,
        role: "check",
      });
    });
    pdxfDraftFit = pdxfCalFitPairs(
      pdxfCal.pairs.filter(function (p) {
        return p.role === "control";
      }),
    );
  }
  pdxfCalRenderCurrent();
  pdxfCalRenderPairs();
  pdxfCalFitShow();
  pdxfCalDrawMarkers();
}
function pdxfCalRole() {
  var role = document.querySelector('input[name="pdxfPickRole"]:checked');
  return role ? role.value : "control";
}
function pdxfCalRoleChanged() {
  pdxfCal.pending = null;
  pdxfCal.phase = "cad";
  pdxfEl("pdxfShowOverlay").checked = true;
  pdxfToggleOverlay();
  pdxfStatus("pdxfCalStatus", "");
  pdxfCalDrawMarkers();
  pdxfCalStepMsg();
}
function pdxfCalStart() {
  if (!pdxfData || pdxfBusy) return;
  pdxfCal.on = true;
  pdxfCal.phase = "cad";
  pdxfCal.pending = null;
  pdxfPlacementMoving = false;
  pdxfPlacementControls();
  pdxfEl("pdxfShowOverlay").checked = true;
  pdxfEl("pdxfCalStartBtn").hidden = true;
  pdxfEl("pdxfCalStopBtn").hidden = false;
  pdxfCadMap.getContainer().style.cursor = "crosshair";
  pdxfMap.getContainer().style.cursor = "crosshair";
  pdxfCalStepMsg();
  pdxfRefreshMap();
  if (window.matchMedia("(max-width: 760px)").matches)
    pdxfEl("pdxfMap")
      .closest(".pdxf-map-panel")
      .scrollIntoView({ block: "start" });
}
function pdxfCalStop() {
  if (pdxfCal.pending) {
    pdxfEl("pdxfShowOverlay").checked = true;
    if (pdxfPreviewPane) pdxfToggleOverlay();
  }
  pdxfCal.on = false;
  pdxfCal.pending = null;
  pdxfCal.phase = "cad";
  pdxfEl("pdxfCalStartBtn").hidden = false;
  pdxfEl("pdxfCalStopBtn").hidden = true;
  if (pdxfCadMap) {
    pdxfCadMap.getContainer().style.cursor = "";
    pdxfMap.getContainer().style.cursor = "";
  }
  pdxfCalStepMsg();
}
function pdxfCalStepMsg() {
  var el = pdxfEl("pdxfCalStep");
  pdxfEl("pdxfSatelliteHint").textContent = pdxfCal.on
    ? pdxfCal.phase === "sat"
      ? "② 点底图的对应位置 · CAD 已隐藏"
      : "① 点 CAD 叠图上的角点或设备"
    : pdxfReady()
      ? "已验证的 CAD 叠图"
      : pdxfCal.pairs.length
        ? "草稿叠图，检查通过后再保存"
        : "初步摆放，仅用于辨认对应位置";
  pdxfEl("pdxfCalRetryBtn").hidden = !pdxfCal.on || !pdxfCal.pending;
  if (!pdxfCal.on) {
    el.textContent = pdxfCal.pairs.length
      ? "选点已暂停，可继续选点或验证并保存。"
      : "点击“开始选点”，先点 CAD 叠图，再点卫星底图的同一位置。";
    return;
  }
  var role = pdxfCal.pending ? pdxfCal.pending.role : pdxfCalRole();
  el.textContent =
    (role === "check" ? "独立检查点" : "对齐点") +
    " · " +
    (pdxfCal.phase === "sat"
      ? "② CAD 已临时隐藏，请在卫星底图点同一位置（可切换 CAD 叠图查看）"
      : "① 在地图上的 CAD 叠图中点一个角点或设备点");
}
function pdxfCalCandidates() {
  var points = [];
  if (!pdxfData) return points;
  var specs = pdxfCollectSpecs(),
    reference = pdxfEl("pdxfShowReference").checked;
  pdxfData.preview.layers.forEach(function (layer) {
    if (
      !(specs.layers[layer.layer] && specs.layers[layer.layer].include) &&
      !reference
    )
      return;
    layer.paths.forEach(function (path) {
      path.forEach(function (point) {
        points.push(point);
      });
    });
  });
  if (pdxfEl("pdxfShowDevices").checked)
    (pdxfData.preview.valves || []).forEach(function (v) {
      if ((specs.blocks[v.block] && specs.blocks[v.block].include) || reference)
        points.push(v);
    });
  return points;
}
function pdxfCalCadClick(event) {
  if (!pdxfCal.on || pdxfCal.phase !== "cad" || pdxfBusy) return;
  var mouse = pdxfCadMap.latLngToContainerPoint(event.latlng),
    best = null,
    distance = 24;
  pdxfCalCandidates().forEach(function (p) {
    var d = pdxfCadMap
      .latLngToContainerPoint([p.dxf_y, p.dxf_x])
      .distanceTo(mouse);
    if (d < distance) {
      distance = d;
      best = p;
    }
  });
  if (!best) {
    pdxfStatus(
      "pdxfCalStatus",
      "未找到附近的 CAD 顶点。请放大原图选择角点，或输入测量坐标。",
      true,
    );
    return;
  }
  pdxfCalPrepareTarget(best);
}
function pdxfCalPrepareTarget(best) {
  pdxfCal.pending = { dxfX: best.dxf_x, dxfY: best.dxf_y, role: pdxfCalRole() };
  pdxfCal.phase = "sat";
  pdxfStatus(
    "pdxfCalStatus",
    "已选择 CAD 坐标 " +
      best.dxf_x.toFixed(2) +
      ", " +
      best.dxf_y.toFixed(2) +
      "；叠图已临时隐藏，请点卫星底图中的对应位置。",
  );
  pdxfEl("pdxfShowOverlay").checked = false;
  pdxfToggleOverlay();
  if (pdxfEl("pdxfOriginalDialog").open) pdxfEl("pdxfOriginalDialog").close();
  pdxfCalDrawMarkers();
  pdxfCalStepMsg();
}
function pdxfCalSatClick(event) {
  if (!pdxfCal.on || pdxfBusy) return;
  if (pdxfCal.phase === "cad") {
    if (!pdxfEl("pdxfShowOverlay").checked) {
      pdxfStatus("pdxfCalStatus", "请先显示 CAD 叠图，再选择 CAD 点。", true);
      return;
    }
    var mouse = pdxfMap.latLngToContainerPoint(event.latlng),
      best = null,
      distance = 24;
    pdxfCalCandidates().forEach(function (p) {
      var ll = pdxfGeographic(p);
      if (!ll) return;
      var d = pdxfMap.latLngToContainerPoint(ll).distanceTo(mouse);
      if (d < distance) {
        distance = d;
        best = p;
      }
    });
    if (best) pdxfCalPrepareTarget(best);
    else
      pdxfStatus(
        "pdxfCalStatus",
        "附近没有 CAD 顶点或设备点，请放大叠图后选择。",
        true,
      );
    return;
  }
  if (!pdxfCal.on || pdxfCal.phase !== "sat" || !pdxfCal.pending || pdxfBusy)
    return;
  var point = Object.assign({}, pdxfCal.pending, {
    satLat: event.latlng.lat,
    satLng: event.latlng.lng,
  });
  pdxfCalAdd(point);
}
function pdxfCalAdd(point) {
  if (pdxfBusy) return;
  if (pdxfCal.pairs.length >= 300) {
    pdxfStatus("pdxfCalStatus", "当前最多支持 300 个坐标对", true);
    return;
  }
  pdxfCal.pairs.push(point);
  pdxfEl("pdxfShowOverlay").checked = true;
  pdxfCal.pending = null;
  pdxfCal.phase = "cad";
  pdxfAlignmentDirty = true;
  pdxfEl("pdxfReviewConfirmed").checked = false;
  var controls = pdxfCal.pairs.filter(function (p) {
    return p.role === "control";
  });
  if (
    controls.length >= 3 &&
    !pdxfCal.pairs.some(function (p) {
      return p.role === "check";
    })
  )
    document.querySelector(
      'input[name="pdxfPickRole"][value="check"]',
    ).checked = true;
  pdxfStatus(
    "pdxfCalStatus",
    point.role === "check"
      ? "检查点已添加，它不会参与比例、旋转和位置的拟合。"
      : "对齐点已添加。请在不同区域选点，避免集中在一条直线上。",
  );
  pdxfCalFitShow();
  pdxfCalDrawMarkers();
  pdxfCalStepMsg();
  pdxfRefreshMap();
  pdxfUpdateWorkflow();
}
function pdxfCalAddCoordinates() {
  if (pdxfBusy) return;
  var values = ["pdxfPointX", "pdxfPointY", "pdxfPointLat", "pdxfPointLng"].map(
    function (id) {
      return parseFloat(pdxfEl(id).value);
    },
  );
  if (
    !values.every(Number.isFinite) ||
    Math.abs(values[2]) > 90 ||
    Math.abs(values[3]) > 180
  ) {
    pdxfStatus("pdxfCalStatus", "请填写有效的 CAD X/Y 与 WGS84 经纬度。", true);
    return;
  }
  pdxfCalAdd({
    dxfX: values[0],
    dxfY: values[1],
    satLat: values[2],
    satLng: values[3],
    role: pdxfCalRole(),
  });
}
function pdxfCalDropPair(index) {
  if (pdxfBusy) return;
  pdxfCal.pairs.splice(index, 1);
  pdxfAlignmentDirty = true;
  pdxfEl("pdxfReviewConfirmed").checked = false;
  pdxfCalFitShow();
  pdxfCalDrawMarkers();
  pdxfRefreshMap();
  pdxfUpdateWorkflow();
}
function pdxfCalClearDraft() {
  if (pdxfBusy) return;
  pdxfCal.pairs = [];
  pdxfCal.pending = null;
  pdxfDraftFit = null;
  pdxfEl("pdxfShowOverlay").checked = true;
  pdxfAlignmentDirty = true;
  document.querySelector(
    'input[name="pdxfPickRole"][value="control"]',
  ).checked = true;
  pdxfCal.phase = "cad";
  pdxfCalFitShow();
  pdxfCalDrawMarkers();
  pdxfCalStepMsg();
  pdxfRefreshMap();
  pdxfUpdateWorkflow();
}
function pdxfCalEvaluate() {
  var controls = pdxfCal.pairs.filter(function (p) {
      return p.role === "control";
    }),
    checks = pdxfCal.pairs.filter(function (p) {
      return p.role === "check";
    }),
    limit = pdxfCalLimit();
  var out = {
    ready: false,
    controls: controls,
    checks: checks,
    fit: null,
    errors: [],
  };
  if (controls.length < 3) {
    out.error = "还需 " + (3 - controls.length) + " 个对齐点。";
    return out;
  }
  var mx =
      controls.reduce(function (s, p) {
        return s + p.dxfX;
      }, 0) / controls.length,
    my =
      controls.reduce(function (s, p) {
        return s + p.dxfY;
      }, 0) / controls.length;
  var xx = 0,
    yy = 0,
    xy = 0;
  controls.forEach(function (p) {
    xx += (p.dxfX - mx) ** 2;
    yy += (p.dxfY - my) ** 2;
    xy += (p.dxfX - mx) * (p.dxfY - my);
  });
  if (xx + yy < 1e-12 || (xx * yy - xy * xy) / (xx + yy) ** 2 < 1e-4) {
    out.error = "对齐点接近一条直线，请选择不同方向的点。";
    return out;
  }
  var fit = pdxfCalFitPairs(controls);
  if (!fit || !Number.isFinite(fit.scale) || fit.scale <= 1e-12) {
    out.error = "无法计算有效比例，请核对对应点。";
    return out;
  }
  out.fit = fit;
  out.errors = checks.map(function (p) {
    return pdxfCalResidualOf(fit, p);
  });
  if (fit.rms_m > limit || Math.max.apply(null, fit.residuals_m) > limit) {
    out.error = "对齐点误差超过 " + limit + " m，请重选误差较大的点。";
    return out;
  }
  out.controlQualityPassed = true;
  if (!checks.length) {
    out.error = "请添加至少 1 个独立检查点，用不同的 CAD 点核验位置。";
    return out;
  }
  var separation = Math.max(
    Math.sqrt((xx + yy) / controls.length) * 1e-6,
    1e-9,
  );
  if (
    controls.some(function (p, i) {
      return controls.slice(0, i).some(function (c) {
        return Math.hypot(p.dxfX - c.dxfX, p.dxfY - c.dxfY) <= separation;
      });
    })
  ) {
    out.controlQualityPassed = false;
    out.error = "对齐点不能重复，请选择不同的 CAD 点。";
    return out;
  }
  if (
    checks.some(function (p) {
      return controls.some(function (c) {
        return Math.hypot(p.dxfX - c.dxfX, p.dxfY - c.dxfY) <= separation;
      });
    })
  ) {
    out.error = "检查点不能复用对齐点的 CAD 坐标。";
    return out;
  }
  if (
    checks.some(function (p, i) {
      return checks.slice(0, i).some(function (c) {
        return Math.hypot(p.dxfX - c.dxfX, p.dxfY - c.dxfY) <= separation;
      });
    })
  ) {
    out.error = "检查点不能重复，请选择不同的 CAD 点。";
    return out;
  }
  if (
    out.errors.some(function (error) {
      return !Number.isFinite(error) || error > limit;
    })
  ) {
    out.error =
      "独立检查点误差超过 " + limit + " m，请核对叠图与底图的对应位置。";
    return out;
  }
  out.ready = true;
  return out;
}
function pdxfCalFitShow() {
  var result = pdxfCalEvaluate();
  pdxfDraftFit = result.controlQualityPassed ? result.fit : null;
  pdxfEl("pdxfCalFit").innerHTML =
    (result.fit
      ? "<div>拟合误差 <b>" +
        result.fit.rms_m.toFixed(2) +
        " m</b> · 比例 " +
        (result.fit.scale * 111320).toPrecision(4) +
        " m / CAD 单位</div>"
      : "") +
    (result.errors.length
      ? "<div>独立检查最大误差 <b>" +
        Math.max.apply(null, result.errors).toFixed(2) +
        " m</b></div>"
      : "") +
    '<div class="' +
    (result.ready ? "success" : "error") +
    '">' +
    pdxfEsc(result.ready ? "误差检查通过，可以保存对齐。" : result.error) +
    "</div>";
  pdxfEl("pdxfCalSaveBtn").disabled =
    !result.ready || pdxfBusy || !pdxfAlignmentDirty;
  pdxfEl("pdxfCalApplyBtn").hidden = !pdxfBatchMode || !pdxfReady();
  pdxfCalRenderPairs(result);
}
function pdxfCalRenderPairs(result) {
  result = result || pdxfCalEvaluate();
  var ci = 0,
    vi = 0;
  pdxfEl("pdxfCalTable").hidden = !pdxfCal.pairs.length;
  pdxfEl("pdxfCalPairBody").innerHTML = pdxfCal.pairs
    .map(function (p, i) {
      var error =
        p.role === "control"
          ? result.fit
            ? result.fit.residuals_m[ci++]
            : null
          : result.errors[vi++];
      return (
        "<tr><td><b>" +
        (i + 1) +
        '</b><span class="pdxf-sub">' +
        (p.role === "check" ? "独立检查" : "对齐") +
        "</span></td><td>" +
        p.dxfX.toFixed(2) +
        ", " +
        p.dxfY.toFixed(2) +
        '<span class="pdxf-sub">' +
        p.satLat.toFixed(6) +
        ", " +
        p.satLng.toFixed(6) +
        "</span></td><td" +
        (error > pdxfCalLimit() ? ' style="color:#ae3630;"' : "") +
        ">" +
        (error != null ? error.toFixed(2) + " m" : "—") +
        '</td><td><button class="pdxf-btn pdxf-btn-secondary" aria-label="删除坐标对 ' +
        (i + 1) +
        '" onclick="pdxfCalDropPair(' +
        i +
        ')">删除</button></td></tr>'
      );
    })
    .join("");
}
function pdxfCalDrawMarkers() {
  if (!pdxfCadMap) return;
  if (pdxfCal.cadMarkers) pdxfCadMap.removeLayer(pdxfCal.cadMarkers);
  if (pdxfCal.markers) pdxfMap.removeLayer(pdxfCal.markers);
  pdxfCal.cadMarkers = L.layerGroup().addTo(pdxfCadMap);
  pdxfCal.markers = L.layerGroup().addTo(pdxfMap);
  function marker(point, i, pending) {
    var icon = L.divIcon({
      className: "",
      html:
        '<span class="pdxf-anchor ' +
        (point.role === "check" ? "check" : "") +
        '">' +
        (pending ? "•" : i + 1) +
        "</span>",
      iconSize: [20, 20],
      iconAnchor: [10, 10],
    });
    L.marker([point.dxfY, point.dxfX], {
      icon: icon,
      interactive: false,
    }).addTo(pdxfCal.cadMarkers);
    var source = pdxfGeographic({ dxf_x: point.dxfX, dxf_y: point.dxfY });
    if (
      source &&
      (pending || pdxfCalResidualOf(pdxfOverlayFit(), point) > 0.5)
    ) {
      L.marker(source, {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html:
            '<span class="pdxf-anchor source">CAD ' +
            (pending ? "•" : i + 1) +
            "</span>",
          iconSize: [48, 22],
          iconAnchor: [24, 11],
        }),
      }).addTo(pdxfCal.markers);
      if (!pending)
        L.polyline([source, [point.satLat, point.satLng]], {
          color: "#d49432",
          weight: 1.5,
          dashArray: "4 4",
          interactive: false,
        }).addTo(pdxfCal.markers);
    }
    if (!pending)
      L.marker([point.satLat, point.satLng], {
        icon: icon,
        interactive: false,
      }).addTo(pdxfCal.markers);
  }
  pdxfCal.pairs.forEach(function (p, i) {
    marker(p, i, false);
  });
  if (pdxfCal.pending) marker(pdxfCal.pending, 0, true);
}
function pdxfCalSave() {
  var result = pdxfCalEvaluate();
  if (!result.ready || pdxfBusy) return;
  pdxfCalStop();
  pdxfBusy = true;
  pdxfCalFitShow();
  pdxfUpdateWorkflow();
  pdxfEl("pdxfCalSaveBtn").textContent = "正在验证…";
  pdxfStatus("pdxfCalStatus", "重新计算拟合与独立检查点误差…");
  function raw(p) {
    return { dxf_x: p.dxfX, dxf_y: p.dxfY, lat: p.satLat, lng: p.satLng };
  }
  var fd = new FormData();
  fd.append("method", "sim");
  fd.append("pairs", JSON.stringify(result.controls.map(raw)));
  fd.append("check_points", JSON.stringify(result.checks.map(raw)));
  if (pdxfBatchMode) fd.append("batch_id", pdxfEl("pdxfCalBatch").value);
  else fd.append("token", pdxfToken);
  fd.append("note", "控制点对齐与独立检查 " + new Date().toLocaleString());
  pdxfPost(window.__DXF__.urls.calSave, fd)
    .then(function (d) {
      if (pdxfBatchMode) {
        pdxfCalInfo = d.calibration;
        pdxfData.calibration = d.calibration;
        pdxfData.alignment = d.calibration.alignment;
        pdxfAlignmentDirty = false;
        return;
      }
      var refresh = new FormData();
      refresh.append("token", pdxfToken);
      refresh.append("calibration_id", d.calibration.id);
      return pdxfPost(window.__DXF__.urls.analyze, refresh).then(
        function (data) {
          pdxfCalInfo = data.calibration;
          pdxfData = data;
          pdxfAlignmentDirty = false;
        },
      );
    })
    .then(function () {
      pdxfCalRenderCurrent();
      pdxfCalFitShow();
      pdxfRefreshMap();
      pdxfFitDrawing();
      pdxfStatus(
        "pdxfCalStatus",
        pdxfBatchMode
          ? "已验证并保存，请应用到所选批次。"
          : "已验证并保存。请核对叠图后继续导入。",
      );
    })
    .catch(function (err) {
      pdxfAlignmentDirty = true;
      pdxfStatus("pdxfCalStatus", err.message || "验证失败，请重试", true);
    })
    .finally(function () {
      pdxfBusy = false;
      pdxfEl("pdxfCalSaveBtn").textContent = "验证并保存对齐";
      pdxfCalFitShow();
      pdxfUpdateWorkflow();
    });
}
function pdxfConfirmReposition(message) {
  return new Promise(function (resolve) {
    var dialog = pdxfEl("pdxfApplyDialog");
    pdxfEl("pdxfApplyDialogBatch").textContent =
      "所选批次：" + pdxfEl("pdxfCalBatch").selectedOptions[0].textContent;
    pdxfEl("pdxfApplyDialogMessage").textContent = message;
    function finish(confirmed) {
      dialog.close();
      resolve(confirmed);
    }
    pdxfEl("pdxfApplyConfirm").onclick = function () {
      finish(true);
    };
    pdxfEl("pdxfApplyCancel").onclick = function () {
      finish(false);
    };
    dialog.oncancel = function (event) {
      event.preventDefault();
      finish(false);
    };
    dialog.showModal();
  });
}
async function pdxfCalApplySaved(force) {
  if (!pdxfBatchMode || !pdxfReady() || pdxfBusy) return;
  if (
    !force &&
    !(await pdxfConfirmReposition(
      "将按已验证的对齐结果重新定位所选批次。人工修正会保留，移动前会备份。继续？",
    ))
  )
    return;
  var fd = new FormData();
  fd.append("confirm", "1");
  fd.append("calibration_id", pdxfCalInfo.id);
  fd.append(
    "batch_ids",
    JSON.stringify([Number(pdxfEl("pdxfCalBatch").value)]),
  );
  if (force) fd.append("force", "1");
  pdxfBusy = true;
  pdxfUpdateWorkflow();
  var forceMessage = null;
  pdxfEl("pdxfCalApplyBtn").disabled = true;
  pdxfStatus("pdxfCalStatus", "正在备份并重新定位所选批次…");
  fetch(window.__DXF__.urls.calApply, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": pdxfCsrf() },
    body: fd,
  })
    .then(function (r) {
      return r.json();
    })
    .then(function (d) {
      if (!d.success && d.need_force) {
        forceMessage = d.error;
        return;
      }
      if (!d.success) throw new Error(d.error || "重新定位失败");
      pdxfStatus(
        "pdxfCalStatus",
        "已重新定位 " +
          d.pipelines +
          " 条管线、" +
          d.valves +
          " 个设备。" +
          d.unchanged +
          " 条相同标定的管线保持原位。",
      );
      pdxfRefreshRefPipelines(false);
      pdxfEdit = null;
    })
    .catch(function (err) {
      pdxfStatus("pdxfCalStatus", err.message, true);
    })
    .finally(async function () {
      pdxfBusy = false;
      pdxfEl("pdxfCalApplyBtn").disabled = false;
      pdxfUpdateWorkflow();
      if (forceMessage) pdxfStatus("pdxfCalStatus", forceMessage, true);
      if (
        forceMessage &&
        (await pdxfConfirmReposition(
          forceMessage + "\n确认控制点与检查点正确后，继续移动所选批次？",
        ))
      )
        pdxfCalApplySaved(true);
    });
}
