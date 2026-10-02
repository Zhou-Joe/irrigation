const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function workspace() {
  const elements = new Map();
  const context = vm.createContext({
    window: { __DXF__: { cal: null, placementPoints: [] } },
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, { checked: true, style: {} });
        return elements.get(id);
      },
      querySelectorAll() {
        return [];
      },
    },
  });
  for (const name of [
    "dxf-core.js",
    "dxf-cal-math.js",
    "dxf-placement.js",
    "dxf-cal.js",
  ]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "..", name), "utf8"),
      context,
    );
  }
  return context;
}
function close(actual, expected, tolerance = 1e-10) {
  assert.ok(
    Math.abs(actual - expected) < tolerance,
    `${actual} != ${expected}`,
  );
}
function fixture(c) {
  const raw = [
    [0, 0],
    [100, 0],
    [0, -100],
    [50, -50],
  ];
  const a = 2e-6,
    b = -7e-6,
    origin = 31;
  const k = Math.cos(((origin - 0.0005 / 3) * Math.PI) / 180);
  const fit = {
    a,
    b,
    c: origin,
    d: 121.65 * k,
    iso_k: k,
    scale: Math.hypot(a, b),
  };
  const pairs = raw.map(([x, y], i) => {
    const [lat, lng] = c.pdxfProjectPoint(fit, { dxf_x: x, dxf_y: y });
    return {
      dxfX: x,
      dxfY: y,
      satLat: lat,
      satLng: lng,
      role: i < 3 ? "control" : "check",
    };
  });
  return { fit, pairs };
}

test("coarse move, rotation and uniform scale preserve shape and original coordinates", () => {
  const c = workspace(),
    { fit } = fixture(c);
  const raw = [
    { dxf_x: 10, dxf_y: -20 },
    { dxf_x: 80, dxf_y: -30 },
    { dxf_x: 30, dxf_y: -90 },
  ];
  const before = JSON.stringify(raw),
    fitBefore = JSON.stringify(fit),
    center = raw[0];
  const moved = c.pdxfMoveFit(fit, center, [31.15, 121.66]);
  const changed = c.pdxfAdjustFit(moved, center, 35, 1.7);
  const anchor = c.pdxfProjectPoint(changed, center);
  close(anchor[0], 31.15);
  close(anchor[1], 121.66);
  for (let i = 0; i < raw.length; i++)
    for (let j = i + 1; j < raw.length; j++) {
      const p = c.pdxfProjectPoint(changed, raw[i]),
        q = c.pdxfProjectPoint(changed, raw[j]);
      const distance = Math.hypot(p[0] - q[0], (p[1] - q[1]) * fit.iso_k);
      const original = Math.hypot(
        raw[i].dxf_x - raw[j].dxf_x,
        raw[i].dxf_y - raw[j].dxf_y,
      );
      close(distance / original, fit.scale * 1.7);
    }
  assert.equal(JSON.stringify(raw), before);
  assert.equal(JSON.stringify(fit), fitBefore);
});

test("one and two controls update the overlay before validation without authorizing import", () => {
  const c = workspace(),
    { fit, pairs } = fixture(c);
  c.pdxfData = { alignment: { ready: false } };
  c.pdxfPlacementFit = c.pdxfMoveFit(
    fit,
    { dxf_x: 0, dxf_y: 0 },
    [31.16, 121.67],
  );
  for (let count = 0; count <= 2; count++) {
    c.pdxfCal.pairs = pairs.slice(0, count);
    assert.ok(c.pdxfOverlayFit());
    assert.equal(c.pdxfReady(), false);
    assert.equal(c.pdxfCalEvaluate().ready, false);
    for (const p of c.pdxfCal.pairs) {
      const projected = c.pdxfGeographic({
        dxf_x: p.dxfX,
        dxf_y: p.dxfY,
        lat: -80,
        lng: -100,
      });
      close(projected[0], p.satLat);
      close(projected[1], p.satLng);
    }
    assert.equal(c.pdxfPlacementAllowed(), count === 0);
  }
});

test("an independent check validates the fitted overlay; an incorrect check cannot change its fit", () => {
  const c = workspace(),
    { pairs } = fixture(c);
  c.pdxfCal.pairs = pairs.slice(0, 3);
  const controlsOnly = c.pdxfCalEvaluate();
  assert.equal(controlsOnly.ready, false);
  assert.equal(controlsOnly.controlQualityPassed, true);
  c.pdxfCal.pairs.push(pairs[3]);
  const valid = c.pdxfCalEvaluate();
  assert.equal(valid.ready, true);
  c.pdxfCal.pairs[3] = { ...pairs[3], satLat: pairs[3].satLat + 0.0001 };
  const rejected = c.pdxfCalEvaluate();
  assert.equal(rejected.ready, false);
  assert.ok(rejected.errors[0] > 11);
  assert.deepEqual(rejected.fit, valid.fit);
  c.pdxfDraftFit = rejected.fit;
  assert.ok(c.pdxfOverlayFit());
});

test("editing a verified drawing immediately uses the draft overlay instead of stale server positions", () => {
  const c = workspace(),
    { fit, pairs } = fixture(c);
  c.pdxfData = { alignment: { ready: true } };
  const point = {
    dxf_x: pairs[0].dxfX,
    dxf_y: pairs[0].dxfY,
    lat: 31.2,
    lng: 121.7,
  };
  assert.equal(
    JSON.stringify(c.pdxfGeographic(point)),
    JSON.stringify([31.2, 121.7]),
  );
  c.pdxfAlignmentDirty = true;
  c.pdxfPlacementFit = fit;
  assert.equal(c.pdxfReady(), false);
  const draft = c.pdxfGeographic(point);
  close(draft[0], pairs[0].satLat);
  close(draft[1], pairs[0].satLng);
});

function bounds(points) {
  const south = Math.min(...points.map((p) => p[0])),
    north = Math.max(...points.map((p) => p[0]));
  const west = Math.min(...points.map((p) => p[1])),
    east = Math.max(...points.map((p) => p[1]));
  return {
    getNorth: () => north,
    getSouth: () => south,
    getEast: () => east,
    getWest: () => west,
    getCenter: () => ({ lat: (north + south) / 2, lng: (east + west) / 2 }),
    pad(amount) {
      return bounds([
        [south - (north - south) * amount, west - (east - west) * amount],
        [north + (north - south) * amount, east + (east - west) * amount],
      ]);
    },
    contains(p) {
      return p.lat >= south && p.lat <= north && p.lng >= west && p.lng <= east;
    },
  };
}
test("unknown source coordinates get a visible shape-preserving initial overlay in the project viewport", () => {
  const c = workspace(),
    view = bounds([
      [31.14, 121.65],
      [31.15, 121.66],
    ]);
  const points = [
    { dxf_x: 5e6, dxf_y: -3e6 },
    { dxf_x: 5e6 + 200, dxf_y: -3e6 + 100 },
  ];
  const before = JSON.stringify(points);
  c.pdxfMap = { getBounds: () => view };
  c.L = { latLngBounds: bounds };
  c.pdxfData = {
    alignment: { ready: false },
    preview: { layers: [{ paths: [points] }] },
  };
  c.pdxfPlacementSeed();
  for (const p of points) {
    const [lat, lng] = c.pdxfGeographic(p);
    assert.ok(view.contains({ lat, lng }));
  }
  const center = c.pdxfProjectPoint(
    c.pdxfPlacementFit,
    c.pdxfPlacementCenterPoint,
  );
  close(center[0], view.getCenter().lat);
  close(center[1], view.getCenter().lng);
  assert.equal(c.pdxfReady(), false);
  assert.equal(JSON.stringify(points), before);
});

test("out-of-range or nonfinite preview projections are not rendered as valid map coordinates", () => {
  const c = workspace(),
    { fit } = fixture(c);
  assert.equal(c.pdxfProjectPoint(null, { dxf_x: 0, dxf_y: 0 }), null);
  assert.equal(c.pdxfProjectPoint(fit, { dxf_x: NaN, dxf_y: 0 }), null);
  assert.equal(
    c.pdxfProjectPoint({ ...fit, c: 100 }, { dxf_x: 0, dxf_y: 0 }),
    null,
  );
});
