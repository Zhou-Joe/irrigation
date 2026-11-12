/* New imports default to the current preview; existing batches stay strict. */
var pdxfPlacementMode = true;
function pdxfImportMode() {
  return pdxfPlacementMode && !pdxfBatchMode ? "direct" : "aligned";
}
function pdxfFitWithScale(fit) {
  return fit ? Object.assign({}, fit, {
    scale: Math.hypot(fit.a, fit.b),
    rotation_deg: Math.atan2(-fit.b, fit.a) * 180 / Math.PI,
  }) : null;
}
function pdxfUsePlacement() {
  return !!(pdxfPlacementMode && pdxfData && !pdxfBatchMode);
}
function pdxfPlacementValid() {
  var f = pdxfPlacementFit;
  return !!f && [f.a, f.b, f.c, f.d, f.iso_k].every(Number.isFinite) &&
    f.iso_k > 0 && f.iso_k <= 1 && Math.hypot(f.a, f.b) > 1e-12 &&
    Math.hypot(f.a, f.b) < 1;
}
function pdxfPositionModeChanged(manual) {
  if (pdxfBusy || pdxfImported || pdxfBatchMode) return;
  if (manual && !pdxfPlacementMode) {
    pdxfPlacementFit = pdxfFitWithScale(pdxfOverlayFit());
  }
  pdxfCalStop();
  pdxfPlacementMode = manual;
  pdxfEl("pdxfPositionDirect").checked = manual;
  pdxfEl("pdxfPositionCalibrated").checked = !manual;
  pdxfEl("pdxfPreciseControls").hidden = manual;
  pdxfEl("pdxfCalCurrent").hidden = manual;
  pdxfInvalidatePreview();
  pdxfRefreshMap();
  pdxfUpdateWorkflow();
  if (pdxfToken) pdxfRebuildPreview();
}
var pdxfPlacementFit = null,
  pdxfPlacementCenterPoint = null;
var pdxfPlacementMoving = false,
  pdxfPlacementHandle = null;

function pdxfPlacementReset() {
  pdxfPlacementMode = !pdxfBatchMode;
  pdxfEl("pdxfPositionDirect").checked = pdxfPlacementMode;
  pdxfEl("pdxfPositionCalibrated").checked = !pdxfPlacementMode;
  pdxfEl("pdxfPreciseControls").hidden = pdxfPlacementMode;
  pdxfEl("pdxfCalCurrent").hidden = pdxfPlacementMode;
  pdxfEl("pdxfPositionMode").hidden = pdxfBatchMode;
  pdxfPlacementFit = null;
  pdxfPlacementCenterPoint = null;
  pdxfPlacementMoving = false;
  if (pdxfPlacementHandle) pdxfMap.removeLayer(pdxfPlacementHandle);
  pdxfPlacementHandle = null;
}
function pdxfPlacementSeed() {
  pdxfPlacementReset();
  var minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  pdxfData.preview.layers.forEach(function (layer) {
    layer.paths.forEach(function (path) {
      path.forEach(function (p) {
        minX = Math.min(minX, p.dxf_x);
        maxX = Math.max(maxX, p.dxf_x);
        minY = Math.min(minY, p.dxf_y);
        maxY = Math.max(maxY, p.dxf_y);
      });
    });
  });
  if (!Number.isFinite(minX + minY + maxX + maxY)) return;
  pdxfPlacementCenterPoint = {
    dxf_x: (minX + maxX) / 2,
    dxf_y: (minY + maxY) / 2,
  };
  var info = pdxfCalInfo || {};
  var points =
    info.method === "similarity" && info.quality && info.quality.valid
      ? info.points
      : window.__DXF__.placementPoints;
  var fit = info.source === "placement" && info.fit ? pdxfFitWithScale(info.fit) : pdxfCalFitPairs(
    (points || []).map(function (p) {
      return { dxfX: p.dxf_x, dxfY: p.dxf_y, satLat: p.lat, satLng: p.lng };
    }),
  );
  var corners = [
    { dxf_x: minX, dxf_y: minY },
    { dxf_x: maxX, dxf_y: maxY },
    { dxf_x: minX, dxf_y: maxY },
    { dxf_x: maxX, dxf_y: minY },
  ];
  var projected = corners.map(function (p) {
    return pdxfProjectPoint(fit, p);
  });
  var view = pdxfMap.getBounds(),
    usable = fit && fit.scale > 1e-12 && projected.every(Boolean);
  if (usable && !(pdxfBatchMode && info.source === "placement")) {
    var extent = L.latLngBounds(projected);
    var ratio = Math.max(
      (extent.getNorth() - extent.getSouth()) /
        (view.getNorth() - view.getSouth()),
      (extent.getEast() - extent.getWest()) / (view.getEast() - view.getWest()),
    );
    usable =
      view.pad(1).contains(extent.getCenter()) && ratio > 0.01 && ratio < 4;
  }
  if (!usable) {
    // Unknown drawing coordinates: fit its extent uniformly into the project view.
    // No CRS/units inference or accepted geographic placement is claimed here.
    var center = view.getCenter(),
      k = Math.cos((center.lat * Math.PI) / 180);
    var span = Math.max(maxX - minX, maxY - minY, 1e-9);
    var scale =
      0.55 *
      Math.min(
        (view.getNorth() - view.getSouth()) / (maxY - minY || span),
        ((view.getEast() - view.getWest()) * k) / (maxX - minX || span),
      );
    fit = pdxfMoveFit(
      { a: 0, b: -scale, c: 0, d: 0, iso_k: k, scale: scale },
      pdxfPlacementCenterPoint,
      [center.lat, center.lng],
    );
  }
  pdxfPlacementFit = fit;
  pdxfEl("pdxfShowOverlay").checked = true;
  pdxfPlacementControls();
}
function pdxfOverlayFit() {
  if (pdxfUsePlacement()) return pdxfPlacementFit;
  if (pdxfDraftFit) return pdxfDraftFit;
  var controls = pdxfCal.pairs.filter(function (p) {
    return p.role === "control";
  });
  // Incremental previews help identify the next point. They never satisfy readiness.
  if (controls.length >= 2) {
    var fit = pdxfCalFitPairs(controls.slice(0, 2));
    if (fit && fit.scale > 1e-12 && Number.isFinite(fit.scale)) return fit;
  }
  if (controls.length && pdxfPlacementFit) {
    var point = controls[0];
    return pdxfMoveFit(
      pdxfPlacementFit,
      { dxf_x: point.dxfX, dxf_y: point.dxfY },
      [point.satLat, point.satLng],
    );
  }
  return pdxfPlacementFit;
}
function pdxfPlacementAllowed() {
  return (
    !!pdxfPlacementFit && !pdxfBusy && !pdxfImported && pdxfStep !== 4 &&
    (pdxfUsePlacement() || (!pdxfVerified() && !pdxfCal.pairs.length))
  );
}
function pdxfPlacementControls() {
  var allowed = pdxfPlacementAllowed();
  if (!allowed) pdxfPlacementMoving = false;
  pdxfEl("pdxfMoveBtn").disabled = !allowed;
  document.querySelectorAll("[data-placement]").forEach(function (el) {
    el.disabled = !allowed;
  });
  pdxfEl("pdxfMoveBtn").textContent = pdxfPlacementMoving
    ? "完成移动"
    : "移动 CAD";
  pdxfEl("pdxfPlacementHint").textContent = pdxfUsePlacement()
    ? "将按地图上当前的位置、角度和比例导入，无需选择对齐点。请核对位置后继续。"
    : pdxfCal.pairs.length
    ? "已开始选点，粗调已锁定。重新选点可再次粗调。"
    : "可继续选点校准，也可选择按当前摆放位置导入。";
  if (!pdxfPlacementMoving && pdxfPlacementHandle) {
    pdxfMap.removeLayer(pdxfPlacementHandle);
    pdxfPlacementHandle = null;
  }
}
function pdxfPlacementToggle() {
  if (!pdxfPlacementAllowed()) return;
  pdxfCalStop();
  pdxfPlacementMoving = !pdxfPlacementMoving;
  pdxfPlacementControls();
  if (!pdxfPlacementMoving) return;
  var position = pdxfProjectPoint(pdxfPlacementFit, pdxfPlacementCenterPoint);
  pdxfPlacementHandle = L.marker(position, {
    draggable: true,
    autoPan: true,
    icon: L.divIcon({
      className: "",
      html: '<span class="pdxf-move-handle">✥ 拖动移动 CAD</span>',
      iconSize: [132, 34],
      iconAnchor: [66, 17],
    }),
  }).addTo(pdxfMap);
  pdxfPlacementHandle.on("drag", function (event) {
    if (pdxfBusy || !pdxfPlacementAllowed()) return;
    var target = event.target.getLatLng();
    pdxfPlacementFit = pdxfMoveFit(pdxfPlacementFit, pdxfPlacementCenterPoint, [
      target.lat,
      target.lng,
    ]);
    pdxfInvalidatePreview();
    pdxfRefreshMap();
  });
}
function pdxfPlacementCenter() {
  if (!pdxfPlacementAllowed()) return;
  var center = pdxfMap.getCenter();
  pdxfPlacementFit = pdxfMoveFit(pdxfPlacementFit, pdxfPlacementCenterPoint, [
    center.lat,
    center.lng,
  ]);
  pdxfRefreshPlacement();
}
function pdxfPlacementAdjust(degrees, factor) {
  if (!pdxfPlacementAllowed()) return;
  var fit = pdxfAdjustFit(
    pdxfPlacementFit,
    pdxfPlacementCenterPoint,
    degrees,
    factor,
  );
  if (!fit) return;
  pdxfPlacementFit = fit;
  pdxfRefreshPlacement();
}
function pdxfRefreshPlacement() {
  pdxfInvalidatePreview();
  if (pdxfPlacementHandle)
    pdxfPlacementHandle.setLatLng(
      pdxfProjectPoint(pdxfPlacementFit, pdxfPlacementCenterPoint),
    );
  pdxfRefreshMap();
  pdxfCalDrawMarkers();
}
function pdxfToggleOverlay() {
  pdxfPreviewPane.style.display = pdxfEl("pdxfShowOverlay").checked
    ? ""
    : "none";
}
function pdxfOpenOriginal() {
  pdxfEl("pdxfOriginalDialog").showModal();
  pdxfCadMap.invalidateSize();
  pdxfFitOriginal();
}
function pdxfFitOriginal() {
  if (!pdxfData) return;
  var points = [];
  pdxfData.preview.layers.forEach(function (layer) {
    layer.paths.forEach(function (path) {
      path.forEach(function (p) {
        points.push([p.dxf_y, p.dxf_x]);
      });
    });
  });
  if (points.length) pdxfCadMap.fitBounds(L.latLngBounds(points).pad(0.1));
}
