/* irrig-heatmap.js — Leaflet heatmap view for the /irrigation/ page.
 *
 * Mirrors stats-heatmap.js (the 数据报表 heatmap) but is scoped to a single
 * metric: per-zone irrigation runtime minutes, sourced from
 * /api/irrigation/zone-heatmap/. The color scale is green → yellow → red
 * (wide hue separation so value differences are obvious at a glance), matching
 * the 数据报表 (stats) heatmap and the pivot-table cells' green family on the
 * adjacent 表格视图 tab.
 *
 * Boundary format helpers (toLL / extractRings) are copied verbatim from
 * stats-heatmap.js — they handle all three shapes the dashboard stores.
 */
(function () {
    'use strict';

    var map = null;
    var zoneLayer = null;
    var wmLayer = null;
    var heatData = null;
    var initialized = false;
    var polygonByZoneId = {};   // zone.id -> L.polygon (for search highlight)
    var highlightLayer = null;  // L.layerGroup holding the yellow outline of matches
    var userMaxOverride = null;  // user color-scale cap (null = auto, use data max)
    // Manager flag drives whether the right-click → 排除 popup is bound to
    // each polygon. Read once from #irrigHeatMap[data-is-manager] (set by the
    // template via the user_role context processor). The backend also returns
    // heatData.is_manager as a redundant check.
    var isManager = false;

    // ── Boundary format helpers (verbatim from stats-heatmap.js) ───────────
    function toLL(p) {
        if (p == null) return null;
        if (Array.isArray(p)) {
            var la = parseFloat(p[0]), ln = parseFloat(p[1]);
            return (isNaN(la) || isNaN(ln)) ? null : [la, ln];
        }
        var la2 = parseFloat(p.lat), ln2 = parseFloat(p.lng);
        return (isNaN(la2) || isNaN(ln2)) ? null : [la2, ln2];
    }
    function extractRings(bp) {
        if (!bp || !bp.length) return [];
        var first = bp[0];
        if (!Array.isArray(first)) {
            var ring = first && typeof first === 'object' ? bp.map(toLL).filter(Boolean) : [];
            return ring.length >= 3 ? [ring] : [];
        }
        var inner = first[0];
        if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
            return bp.map(function (r) {
                var rr = (r || []).map(toLL).filter(Boolean);
                return rr.length >= 3 ? rr : null;
            }).filter(Boolean);
        }
        var rings = [];
        for (var g = 0; g < bp.length; g++) {
            var group = bp[g];
            if (group && group[0] && group[0].length) {
                var rr2 = group[0].map(toLL).filter(Boolean);
                if (rr2.length >= 3) rings.push(rr2);
            }
        }
        return rings;
    }

    // ── Color gradient: green → yellow → red ─────────────────────────────
    // Wide hue separation (green ↔ yellow ↔ red) makes value differences
    // obvious. The high-value red end stands out clearly against the satellite
    // basemap; low-value greens may blend slightly but matter least.
    function heatColor(v, max) {
        if (!v || !max) return 'rgba(40,150,70,0.12)';
        var t = Math.min(v / max, 1);
        if (t < 0.5) {
            // Green (#28B45A) → yellow (#FAD228) at the midpoint.
            var k = t / 0.5;
            var r = Math.round(40 + (250 - 40) * k);
            var g = Math.round(180 + (210 - 180) * k);
            var b = Math.round(90 + (40 - 90) * k);
            return 'rgb(' + r + ',' + g + ',' + b + ')';
        }
        // Yellow (#FAD228) → red (#C81E1E) at max.
        var k2 = (t - 0.5) / 0.5;
        var r2 = Math.round(250 + (200 - 250) * k2);
        var g2 = Math.round(210 + (30 - 210) * k2);
        var b2 = Math.round(40 + (30 - 40) * k2);
        return 'rgb(' + r2 + ',' + g2 + ',' + b2 + ')';
    }

    // ── Metric value picker ──────────────────────────────────────────────
    // Returns the numeric value of a zone under the active metric, used by
    // both the heatmap color decision and the search-result ranking. Zones
    // without irrigation_intensity report 0 in volume mode (so they sort to
    // the bottom of search results rather than NaN-ing the comparator).
    function metricValue(z) {
        if (currentMetric === 'volume') return z.irrigation_depth_mm || 0;
        return z.runtime_minutes || 0;
    }

    // ── User color-scale cap (persisted, per-metric) ────────────────────
    // One outlier zone can pin `max` so high that every other zone paints
    // green (v/max ≈ 0). A user-set cap clamps the high end to red so the
    // mid-range spreads across yellow/green. Empty/0/negative = auto.
    //
    // Two separate localStorage keys so a time-mode cap (minutes) and a
    // volume-mode cap (mm) don't collide — they have different magnitudes.
    var currentMetric = 'time';   // 'time' | 'volume'
    var USERMAX_KEYS = {
        time:   'irrigHeatUserMax',
        volume: 'irrigHeatUserMaxVolume',
    };
    function effectiveMax(dataMax) {
        return (userMaxOverride && userMaxOverride > 0) ? userMaxOverride : (dataMax || 0);
    }
    function loadUserMax() {
        var raw = localStorage.getItem(USERMAX_KEYS[currentMetric] || USERMAX_KEYS.time) || '';
        // volume caps may be fractional (mm), time caps are integer minutes.
        var v = currentMetric === 'volume' ? parseFloat(raw) : parseInt(raw, 10);
        userMaxOverride = (!isNaN(v) && v > 0) ? v : null;
    }
    function initUserMaxControl() {
        var input = document.getElementById('irrigHeatUserMax');
        if (!input || input.dataset.bound) return;
        input.dataset.bound = '1';
        loadUserMax();
        if (userMaxOverride) input.value = userMaxOverride;
        input.addEventListener('input', function () {
            var v = currentMetric === 'volume' ? parseFloat(input.value) : parseInt(input.value, 10);
            v = isNaN(v) ? 0 : v;
            userMaxOverride = (v > 0) ? v : null;
            var key = USERMAX_KEYS[currentMetric] || USERMAX_KEYS.time;
            if (userMaxOverride) localStorage.setItem(key, String(v));
            else localStorage.removeItem(key);
            renderHeatZones();
        });
    }

    // ── Map init ──────────────────────────────────────────────────────────
    function initMap() {
        if (initialized) return;
        // Read the manager flag from the template-injected data attribute once.
        // Stashing it module-level lets renderHeatZones decide whether to bind
        // the exclude popup without re-querying the DOM on every redraw.
        var mapEl = document.getElementById('irrigHeatMap');
        if (mapEl) isManager = mapEl.dataset.isManager === '1';
        var cLat = 31.145663, cLng = 121.655407;
        var latOff = 0.027, lngOff = 0.032;
        var bounds = L.latLngBounds([cLat - latOff, cLng - lngOff], [cLat + latOff, cLng + lngOff]);

        var satellite = L.tileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            { attribution: 'Esri', maxNativeZoom: 19, maxZoom: 22 });
        var fallback = L.tileLayer(
            'https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}',
            { minZoom: 19, maxZoom: 22, opacity: 0.7 });
        var hybrid = L.layerGroup([satellite, fallback]);

        map = L.map('irrigHeatMap', {
            center: [cLat, cLng],
            zoom: 15,
            minZoom: 15,
            maxZoom: 22,
            maxBounds: bounds,
            maxBoundsViscosity: 1.0,
            layers: [hybrid],
            preferCanvas: true,
            zoomControl: true,
        });
        window._irrigHeatMap = map;

        zoneLayer = L.layerGroup().addTo(map);
        wmLayer = L.layerGroup().addTo(map);

        map.on('zoomend', function () { renderWatermarks(); });
        initialized = true;
    }

    // ── Render zones with heat coloring ───────────────────────────────────
    function renderHeatZones() {
        if (!zoneLayer || !heatData || !heatData.zones) return;
        zoneLayer.clearLayers();
        polygonByZoneId = {};
        if (highlightLayer) { highlightLayer.clearLayers(); }

        var zones = heatData.zones;
        var isVolume = currentMetric === 'volume';
        // Each metric has its own data-max (minutes vs mm) so the color scale
        // spans the right range. max_volume only counts zones WITH intensity,
        // so gray (no-intensity) zones never get to set the red end.
        var dataMax = isVolume ? (heatData.max_volume || 0) : (heatData.max || 0);
        var max = effectiveMax(dataMax);
        var unitLabel = isVolume ? 'mm' : '分钟';

        for (var i = 0; i < zones.length; i++) {
            var z = zones[i];
            // Pick the value + whether this zone has data for the active metric.
            // Volume mode treats zones without irrigation_intensity as "no data"
            // (gray) — they can't be ranked on the depth scale at all.
            var val, hasData, detail;
            if (isVolume) {
                var intensity = z.irrigation_intensity;
                hasData = (intensity != null);
                val = z.irrigation_depth_mm || 0;
                if (hasData) {
                    detail = '深度 ' + val + ' mm' +
                             '（运行 ' + (z.runtime_minutes || 0) + ' 分钟 × ' + intensity + ' mm/h）';
                } else {
                    detail = '未配置灌溉强度，无法计算水量' +
                             '（运行 ' + (z.runtime_minutes || 0) + ' 分钟）';
                }
            } else {
                val = z.runtime_minutes || 0;
                hasData = true;
                detail = '运行 ' + val + ' 分钟';
            }
            var color, opacity;
            if (!hasData) {
                // Gray for zones the active metric can't score. Distinct from
                // the green-low-value tint so reviewers see "missing config",
                // not "low usage".
                color = 'rgb(140,140,140)';
                opacity = 0.25;
            } else {
                color = heatColor(val, max);
                opacity = val > 0 ? 0.75 : 0.06;
            }
            var style = {
                color: 'transparent',   // no outline
                weight: 0,
                fillColor: color,
                fillOpacity: opacity,
            };
            var label = (z.code || '') + ' ' + (z.name || '');
            var rings = extractRings(z.boundary_points);
            if (rings.length > 1) detail += ' · ' + rings.length + ' 个区域';
            // A zone may have multiple rings — group them so search can
            // outline / fly to all of them as one unit.
            var polys = [];
            for (var r = 0; r < rings.length; r++) {
                var ring = rings[r];
                if (ring.length < 3) continue;
                var poly = L.polygon(ring, style);
                poly.bindTooltip(label + '\n' + detail, { sticky: true });
                // Map polygons are all valid (drawn, in-use) zones — excluding
                // is intentionally NOT available here. Managers exclude zones
                // from the 「未绘制边界区域」 panel instead, where the zones
                // are not in active use.
                poly.addTo(zoneLayer);
                polys.push(poly);
            }
            if (polys.length) polygonByZoneId[z.id] = polys;
        }

        // Legend max label + gradient bar (unit follows the active metric).
        var maxLabel = document.getElementById('irrigHeatMaxLabel');
        if (maxLabel) {
            maxLabel.textContent = (userMaxOverride && userMaxOverride > 0)
                ? '色阶上限: ' + userMaxOverride + ' ' + unitLabel + ' (最大值 ' + dataMax + ')'
                : '最大: ' + dataMax + ' ' + unitLabel;
        }
        var bar = document.getElementById('irrigHeatLegendBar');
        if (bar) {
            bar.style.background = 'linear-gradient(to right, rgb(40,180,90), rgb(250,210,40), rgb(200,30,30))';
        }
        // Sync the legend title / unit suffix / note to the active metric so
        // the whole panel reads consistently (title, max, cap, explanation).
        var title = document.getElementById('irrigLegendTitle');
        if (title) title.textContent = isVolume ? '区域灌溉深度 (mm)' : '区域灌溉运行分钟';
        var unitSpan = document.getElementById('irrigHeatUnitLabel');
        if (unitSpan) unitSpan.textContent = unitLabel;
        var note = document.getElementById('irrigLegendNote');
        if (note) note.textContent = isVolume
            ? '深度 = 运行分钟 ÷ 60 × 灌溉强度(mm/h) · 灰色 = 未配置强度'
            : '颜色 = 所选时间窗口内该区域的运行分钟数';
        // The user-max input step should allow fractions in volume mode (mm
        // can be 0.5) but stay integer in time mode.
        var maxInput = document.getElementById('irrigHeatUserMax');
        if (maxInput) maxInput.step = isVolume ? '0.1' : '1';

        renderWatermarks();

        // Re-apply the current search box content after a data refresh so a
        // user-typed query survives filter changes.
        var input = document.getElementById('irrigZoneSearch');
        if (input && input.value) searchZone(input.value);
    }

    // ── Zone search + highlight ────────────────────────────────────────────
    // Matches zone code OR name (case-insensitive substring). All matches get
    // a bright yellow outline drawn above the heat polygons, the map flies to
    // the bounding box of all matches, and a ranked result list (by runtime
    // descending) renders below the input — click a row to fly to that zone.
    function searchZone(rawQuery) {
        if (!map) return;
        if (!highlightLayer) {
            highlightLayer = L.layerGroup().addTo(map);
        }
        highlightLayer.clearLayers();

        var input = document.getElementById('irrigZoneSearch');
        var statusEl = document.getElementById('irrigZoneSearchStatus');
        var resultsEl = document.getElementById('irrigZoneResults');
        var q = (rawQuery != null ? rawQuery : (input ? input.value : '')).trim().toLowerCase();

        if (resultsEl) {
            resultsEl.innerHTML = '';
            resultsEl.classList.remove('has-results');
        }

        if (!q) {
            if (statusEl) statusEl.textContent = '';
            return;
        }

        var matches = [];
        var zones = (heatData && heatData.zones) || [];
        for (var i = 0; i < zones.length; i++) {
            var z = zones[i];
            var code = (z.code || '').toLowerCase();
            var name = (z.name || '').toLowerCase();
            if (code.indexOf(q) >= 0 || name.indexOf(q) >= 0) {
                matches.push(z);
            }
        }
        // Rank by the active metric's value descending so the heaviest-
        // irrigated zones surface (time mode: minutes; volume mode: depth mm;
        // zones without intensity sort last under volume).
        matches.sort(function (a, b) {
            return metricValue(b) - metricValue(a);
        });

        var highlightStyle = {
            color: '#ffeb3b',
            weight: 3,
            opacity: 1,
            fillColor: '#ffeb3b',
            fillOpacity: 0.15,
            dashArray: '4,3',
        };
        var allBounds = L.latLngBounds([]);
        for (var mi = 0; mi < matches.length; mi++) {
            var polys = polygonByZoneId[matches[mi].id];
            if (!polys) continue;
            for (var pi = 0; pi < polys.length; pi++) {
                // Re-trace each ring as a standalone outline so the highlight
                // stays crisp regardless of the underlying polygon's style.
                var ll = polys[pi].getLatLngs();
                var outline = L.polygon(unwindRings(ll), highlightStyle);
                outline.addTo(highlightLayer);
                allBounds.extend(outline.getBounds());
            }
        }

        if (statusEl) {
            statusEl.textContent = matches.length
                ? '匹配 ' + matches.length + ' 个区域'
                : '无匹配';
        }

        // Render the ranked result list.
        if (resultsEl && matches.length) {
            var html = '';
            var unitSuffix = currentMetric === 'volume' ? ' mm' : ' 分';
            for (var ri = 0; ri < matches.length; ri++) {
                var m = matches[ri];
                // Volume mode: zones without intensity show "—" since they have
                // no depth value to rank on (they still appear because they
                // matched the name query).
                var valStr;
                if (currentMetric === 'volume') {
                    valStr = (m.irrigation_intensity != null)
                        ? (metricValue(m) + unitSuffix)
                        : '—';
                } else {
                    valStr = metricValue(m) + unitSuffix;
                }
                // data-id drives the click handler; escaping mirrors map.js.
                var safeCode = _esc(m.code || '');
                var safeName = _esc(m.name || '');
                html += '<div class="irrig-result-row" data-zone-id="' + m.id + '">' +
                    '<div class="irrig-result-label">' +
                    '<span class="irrig-result-code">' + safeCode + '</span>' +
                    safeName +
                    '</div>' +
                    '<span class="irrig-result-mins">' + valStr + '</span>' +
                    '</div>';
            }
            resultsEl.innerHTML = html;
            resultsEl.classList.add('has-results');
            // Wire click → fly to that zone (and outline only it briefly).
            resultsEl.querySelectorAll('.irrig-result-row').forEach(function (row) {
                row.addEventListener('click', function () {
                    var zid = parseInt(this.dataset.zoneId, 10);
                    flyToZoneById(zid);
                });
            });
        }

        if (matches.length && allBounds.isValid()) {
            map.flyToBounds(allBounds.pad(0.3), { duration: 0.6, maxZoom: 19 });
        }
    }

    function flyToZoneById(zoneId) {
        if (!map || !heatData) return;
        var zone = null;
        for (var i = 0; i < heatData.zones.length; i++) {
            if (heatData.zones[i].id === zoneId) { zone = heatData.zones[i]; break; }
        }
        if (!zone) return;
        var polys = polygonByZoneId[zone.id] || [];
        var bounds = L.latLngBounds([]);
        for (var p = 0; p < polys.length; p++) bounds.extend(polys[p].getBounds());
        if (bounds.isValid()) {
            map.flyToBounds(bounds.pad(0.4), { duration: 0.6, maxZoom: 20 });
        }
    }

    // Collapse/expand the search panel. Default is collapsed (only the 🔍
    // toggle button is visible); the panel slides open on click and focuses
    // the input for immediate typing.
    function toggleIrrigSearch() {
        var panel = document.getElementById('irrigSearchPanel');
        if (!panel) return;
        var open = panel.style.display !== 'none';
        panel.style.display = open ? 'none' : 'flex';
        if (!open) {
            var input = document.getElementById('irrigZoneSearch');
            if (input) setTimeout(function () { input.focus(); }, 30);
            // Re-apply any existing query so reopening doesn't lose state.
            if (input && input.value) searchZone(input.value);
        }
    }

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // Flatten Leaflet's nested getLatLngs() (polygon → rings → holes) into a
    // flat array of [lat,lng] arrays usable by L.polygon.
    function unwindRings(ll) {
        var out = [];
        for (var i = 0; i < ll.length; i++) {
            var ring = ll[i];
            if (ring.length && Array.isArray(ring[0]) && Array.isArray(ring[0][0])) {
                for (var j = 0; j < ring.length; j++) out.push(unwindFlat(ring[j]));
            } else if (ring.length && ring[0] && typeof ring[0].lat === 'number') {
                out.push(unwindFlat(ring));
            } else {
                out.push(unwindFlat(ring));
            }
        }
        return out;
    }
    function unwindFlat(arr) {
        var pts = [];
        for (var k = 0; k < arr.length; k++) {
            var p = arr[k];
            if (Array.isArray(p)) pts.push([p[0], p[1]]);
            else if (p && typeof p.lat === 'number') pts.push([p.lat, p.lng]);
        }
        return pts;
    }


    // ── Watermarks (Land-name labels, size by zoom) ───────────────────────
    function centerToLL(c) {
        if (!c) return null;
        if (Array.isArray(c)) return [c[0], c[1]];
        if (c.lat != null && c.lng != null) return [c.lat, c.lng];
        return null;
    }
    function computeLandCentroids() {
        if (!heatData) return {};
        var landPts = {};
        for (var i = 0; i < heatData.zones.length; i++) {
            var z = heatData.zones[i];
            if (!z.land_name || !z.center) continue;
            var ll = centerToLL(z.center);
            if (!ll) continue;
            if (!landPts[z.land_name]) landPts[z.land_name] = [];
            landPts[z.land_name].push(ll);
        }
        var out = {};
        for (var name in landPts) {
            var pts = landPts[name];
            var sLat = 0, sLng = 0;
            for (var j = 0; j < pts.length; j++) { sLat += pts[j][0]; sLng += pts[j][1]; }
            out[name] = [sLat / pts.length, sLng / pts.length];
        }
        return out;
    }
    function renderWatermarks() {
        if (!wmLayer || !map) return;
        wmLayer.clearLayers();
        var zoom = map.getZoom();
        if (zoom < 15) return;

        var landWm = computeLandCentroids();
        var base = 25;
        var size = zoom <= 16 ? Math.round(base * 0.7) :
                   zoom === 17 ? Math.round(base * 1.2) :
                   Math.round(base * 1.2);

        for (var name in landWm) {
            var center = landWm[name];
            var icon = L.divIcon({
                className: 'irrig-heat-watermark',
                html: '<div style="transform:translate(-50%,-50%);white-space:nowrap;">' +
                      '<span style="font-size:' + size + 'px;color:rgba(255,255,255,0.55);' +
                      'font-weight:700;text-shadow:0 0 8px rgba(0,0,0,0.4);pointer-events:none;">' +
                      name + '</span></div>',
                iconSize: [0, 0],
            });
            L.marker(center, { icon: icon, interactive: false }).addTo(wmLayer);
        }
    }

    // ── Data fetch ────────────────────────────────────────────────────────
    // Reads the page's current <input type="datetime-local"> values, compacts
    // them to YYYYMMDDHHMM (the backend pads internally), and queries the
    // heatmap endpoint. Stays in sync with the pivot-table filter bar.
    function currentWindowParams() {
        var fromEl = document.getElementById('dateFrom');
        var toEl = document.getElementById('dateTo');
        var params = new URLSearchParams();
        if (fromEl && fromEl.value) params.set('from', fromEl.value.replace(/[^0-9]/g, ''));
        if (toEl && toEl.value) params.set('to', toEl.value.replace(/[^0-9]/g, ''));
        return params.toString();
    }

    function loadIrrigHeatmap() {
        var qs = currentWindowParams();
        fetch('/api/irrigation/zone-heatmap/?' + qs)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                heatData = d;
                renderHeatZones();
                renderUnmappedZones();
                renderExcludedZones();
            })
            .catch(function (err) {
                console.error('[irrig-heatmap] load failed', err);
            });
    }

    // ── Unmapped zones panel ──────────────────────────────────────────────
    // Zones with a runtime mapping but no boundary polygon can't be drawn on
    // the map. Surface them as a ranked list (by runtime desc) with a link to
    // the dashboard so reviewers know exactly which zones need polygons drawn.
    function renderUnmappedZones() {
        var countEl = document.getElementById('irrigUnmappedCount');
        var listEl = document.getElementById('irrigUnmappedList');
        if (!countEl || !listEl) return;
        var items = (heatData && heatData.unmapped) || [];
        countEl.textContent = items.length;
        countEl.classList.toggle('zero', items.length === 0);
        if (!items.length) {
            listEl.innerHTML = '<div class="irrig-unmapped-note" style="margin:8px 0;">所有映射区域均已绘制边界 ✓</div>';
            return;
        }
        var html = '';
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            // Value column follows the active metric: minutes (time) or mm
            // depth (volume). Volume mode shows "—" when intensity is unset so
            // reviewers see the missing config, not a misleading 0.
            var valStr;
            if (currentMetric === 'volume') {
                valStr = (it.irrigation_intensity != null)
                    ? ((it.irrigation_depth_mm || 0) + ' mm')
                    : '—';
            } else {
                valStr = (it.runtime_minutes || 0) + ' 分';
            }
            // Manager-only: an "排除" button so these undrawn, not-in-use zones
            // can be hidden from the heatmap without ever appearing on the map.
            // (Drawn zones on the map are all valid and are never excludable.)
            var label = (it.code || '') + ' ' + (it.name || '');
            var excludeBtn = isManager
                ? '<button class="irrig-unmapped-exclude" type="button" '
                  + 'data-zone-id="' + it.id + '" data-zone-label="' + _esc(label) + '" '
                  + 'title="从热力图排除">排除</button>'
                : '';
            // Open the mobile-friendly boundary drawing page.
            html += '<div class="irrig-unmapped-row">' +
                '<div class="irrig-unmapped-label">' +
                '<span class="irrig-unmapped-code">' + _esc(it.code) + '</span>' +
                _esc(it.name || '') +
                '</div>' +
                '<span class="irrig-unmapped-mins">' + valStr + '</span>' +
                '<a class="irrig-unmapped-draw" href="/settings/zone/quick-draw/mobile" '
                + 'target="_blank" rel="noopener" title="绘制 ' + _esc(it.code) + ' 边界">绘制</a>' +
                excludeBtn +
                '</div>';
        }
        listEl.innerHTML = html;
    }

    function toggleIrrigUnmapped() {
        var panel = document.getElementById('irrigUnmappedPanel');
        var arrow = document.getElementById('irrigUnmappedArrow');
        var header = panel ? panel.querySelector('.irrig-unmapped-header') : null;
        if (!panel) return;
        var open = panel.classList.toggle('open');
        if (arrow) arrow.textContent = open ? '▼' : '▶';
        if (header) header.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    // ── Excluded zones panel (manager-only) ──────────────────────────────
    // Mirrors renderUnmappedZones but for zones the manager deliberately hid
    // via the 「排除」 button in the unmapped panel. Each row carries a 「恢复」
    // button that POSTs to the restore endpoint and reloads the heatmap.
    function renderExcludedZones() {
        var panel = document.getElementById('irrigExcludedPanel');
        if (!panel) return;   // non-manager: template doesn't render the panel
        var countEl = document.getElementById('irrigExcludedCount');
        var listEl = document.getElementById('irrigExcludedList');
        if (!countEl || !listEl) return;
        var items = (heatData && heatData.excluded) || [];
        countEl.textContent = items.length;
        countEl.classList.toggle('zero', items.length === 0);
        if (!items.length) {
            listEl.innerHTML = '<div class="irrig-excluded-note" style="margin:8px 0;">暂无排除的区域</div>';
            return;
        }
        var html = '';
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            html += '<div class="irrig-excluded-row">' +
                '<div class="irrig-excluded-label">' +
                '<span class="irrig-excluded-code">' + _esc(it.code) + '</span>' +
                _esc(it.name || '') +
                '</div>' +
                '<button class="irrig-excluded-restore" type="button" data-zone-id="' + it.id + '">恢复</button>' +
                '</div>';
        }
        listEl.innerHTML = html;
    }

    function toggleIrrigExcluded() {
        var panel = document.getElementById('irrigExcludedPanel');
        var arrow = document.getElementById('irrigExcludedArrow');
        var header = panel ? panel.querySelector('.irrig-excluded-header') : null;
        if (!panel) return;
        var open = panel.classList.toggle('open');
        if (arrow) arrow.textContent = open ? '▼' : '▶';
        if (header) header.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    // POST helper for the exclude/restore endpoints. Reads the CSRF token the
    // same way the rest of the page does (cookie-driven).
    function _irrigCsrfToken() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }
    function excludeZone(zoneId, label) {
        if (!confirm('确认将「' + label + '」从热力图排除？\n（排除后该区域不再显示，可在「已排除区域」面板恢复）')) return;
        fetch('/api/irrigation/zone/' + zoneId + '/exclude/', {
            method: 'POST',
            headers: { 'X-CSRFToken': _irrigCsrfToken() },
        }).then(function (r) { return r.json(); }).then(function (d) {
            _irrigToast(d.message || '已排除', !d.success);
            if (d.success) {
                loadIrrigHeatmap();   // refresh: zone disappears, panel updates
            }
        }).catch(function () { _irrigToast('网络错误', true); });
    }
    function restoreZone(zoneId) {
        fetch('/api/irrigation/zone/' + zoneId + '/restore/', {
            method: 'POST',
            headers: { 'X-CSRFToken': _irrigCsrfToken() },
        }).then(function (r) { return r.json(); }).then(function (d) {
            _irrigToast(d.message || '已恢复', !d.success);
            if (d.success) {
                loadIrrigHeatmap();
            }
        }).catch(function () { _irrigToast('网络错误', true); });
    }

    // Minimal toast — the irrigation page has no shared toast helper, so this
    // writes a transient status line. Kept tiny because excludes are rare.
    function _irrigToast(msg, isErr) {
        var t = document.createElement('div');
        t.textContent = msg;
        t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
            'background:' + (isErr ? '#b3261e' : '#333') + ';color:#fff;padding:8px 18px;' +
            'border-radius:20px;font-size:.86rem;z-index:9999;opacity:0;transition:opacity .2s;pointer-events:none;';
        document.body.appendChild(t);
        requestAnimationFrame(function () { t.style.opacity = '1'; });
        setTimeout(function () { t.style.opacity = '0'; setTimeout(function () { t.remove(); }, 250); }, 2500);
    }

    // ── View switching (chart ↔ heatmap) ──────────────────────────────────
    // The container has two CSS modes:
    //   .chart-mode   — normal centered page (sidebar collapses into a top
    //                   stack, pivot table visible, map hidden).
    //   .heatmap-mode — fullscreen flex row under the nav bar: sidebar on the
    //                   left (collapsible), map fills the rest.
    // The map is initialized lazily on first switch to heatmap; invalidateSize
    // runs after the layout transition so Leaflet measures the new size.
    function switchIrrigView(mode) {
        var root = document.getElementById('irrigFullscreen');
        if (!root) return;
        var isHeat = mode === 'heatmap';
        root.classList.toggle('chart-mode', !isHeat);
        root.classList.toggle('heatmap-mode', isHeat);

        // Summary cards are pivot-table stats — only meaningful in chart mode.
        var summary = document.getElementById('summaryCards');
        if (summary) summary.style.display = isHeat ? 'none' : '';

        // Active pill styling.
        document.querySelectorAll('.irrig-view-pill').forEach(function (p) {
            p.classList.toggle('active', p.dataset.view === mode);
        });

        if (isHeat) {
            initMap();
            // Layout transition + Leaflet measuring both need a tick after the
            // container becomes visible. invalidateSize after the transition.
            setTimeout(function () {
                if (map) map.invalidateSize();
            }, 320);
            loadIrrigHeatmap();
        }
    }

    // ── Sidebar collapse (heatmap mode only) ──────────────────────────────
    // Toggles the .collapsed class on the sidebar and .visible on the floating
    // reopen handle, then invalidates the map so Leaflet re-fills the space.
    function toggleIrrigSidebar() {
        var sidebar = document.getElementById('irrigSidebar');
        var expand = document.getElementById('irrigSidebarExpand');
        if (!sidebar) return;
        sidebar.classList.toggle('collapsed');
        var collapsed = sidebar.classList.contains('collapsed');
        if (expand) expand.classList.toggle('visible', collapsed);
        setTimeout(function () {
            if (map) map.invalidateSize();
        }, 320);
    }

    // ── Metric switching (运行时间 ↔ 灌水量) ─────────────────────────────
    // Toggles which value drives the heatmap color + legend. Data is already
    // in heatData (backend returns both runtime_minutes and irrigation_depth_mm
    // for every zone), so switching is a pure re-render — no refetch needed.
    // The user-set color cap is per-metric (minutes vs mm have very different
    // magnitudes), so we swap localStorage keys and sync the input on switch.
    function switchIrrigMetric(metric) {
        if (metric === currentMetric) return;
        if (metric !== 'time' && metric !== 'volume') return;
        currentMetric = metric;
        document.querySelectorAll('.irrig-metric-pill').forEach(function (p) {
            p.classList.toggle('active', p.dataset.metric === metric);
        });
        // Load this metric's saved cap (may be null) and reflect it in the input.
        loadUserMax();
        var input = document.getElementById('irrigHeatUserMax');
        if (input) input.value = userMaxOverride || '';
        renderHeatZones();
        renderUnmappedZones();
        renderExcludedZones();
        // Re-run the current query so the result ranking follows the new metric.
        var s = document.getElementById('irrigZoneSearch');
        if (s && s.value) searchZone(s.value);
    }

    // ── Public API ────────────────────────────────────────────────────────
    window.switchIrrigView = switchIrrigView;
    window.switchIrrigMetric = switchIrrigMetric;
    window.loadIrrigHeatmap = loadIrrigHeatmap;
    window.searchIrrigZone = searchZone;
    window.toggleIrrigExcluded = toggleIrrigExcluded;
    window.excludeZone = excludeZone;
    window.restoreZone = restoreZone;
    window.toggleIrrigSearch = toggleIrrigSearch;
    window.toggleIrrigSidebar = toggleIrrigSidebar;
    window.toggleIrrigUnmapped = toggleIrrigUnmapped;
    window._irrigHeatmapInitialized = function () { return initialized; };

    // ── Boot ──────────────────────────────────────────────────────────────
    // If the page opens directly in heatmap mode (the default), initialize
    // the map and load data on DOMContentLoaded. (In chart mode the map
    // initializes lazily when the user switches over.)
    document.addEventListener('DOMContentLoaded', function () {
        initUserMaxControl();
        // Delegated clicks for the dynamically-injected exclude/restore
        // buttons. The exclude button lives in the 未绘制边界区域 panel rows
        // (manager-only); the restore button lives in the 已排除区域 panel.
        // Both panels are re-rendered on every heatmap refresh, so a single
        // delegated listener outlives them.
        document.addEventListener('click', function (e) {
            var x = e.target.closest ? e.target.closest('.irrig-unmapped-exclude') : null;
            if (x) {
                var zid = x.getAttribute('data-zone-id');
                var zlabel = x.getAttribute('data-zone-label') || '';
                if (zid) excludeZone(zid, zlabel);
                return;
            }
            var r = e.target.closest ? e.target.closest('.irrig-excluded-restore') : null;
            if (r) {
                var rid = r.getAttribute('data-zone-id');
                if (rid) restoreZone(rid);
                return;
            }
        });
        var root = document.getElementById('irrigFullscreen');
        if (root && root.classList.contains('heatmap-mode')) {
            initMap();
            // Allow the layout to settle before Leaflet measures its pane.
            setTimeout(function () {
                if (map) map.invalidateSize();
                loadIrrigHeatmap();
            }, 60);
        }
    });
})();
