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

    // ── User color-scale cap (persisted) ─────────────────────────────────
    // One outlier zone can pin `max` so high that every other zone paints
    // green (v/max ≈ 0). A user-set cap clamps the high end to red so the
    // mid-range spreads across yellow/green. Empty/0/negative = auto.
    var USERMAX_KEY = 'irrigHeatUserMax';
    function effectiveMax(dataMax) {
        return (userMaxOverride && userMaxOverride > 0) ? userMaxOverride : (dataMax || 0);
    }
    function loadUserMax() {
        var v = parseInt(localStorage.getItem(USERMAX_KEY) || '', 10);
        userMaxOverride = (v > 0) ? v : null;
    }
    function initUserMaxControl() {
        var input = document.getElementById('irrigHeatUserMax');
        if (!input || input.dataset.bound) return;
        input.dataset.bound = '1';
        loadUserMax();
        if (userMaxOverride) input.value = userMaxOverride;
        input.addEventListener('input', function () {
            var v = parseInt(input.value, 10);
            v = isNaN(v) ? 0 : v;
            userMaxOverride = (v > 0) ? v : null;
            if (userMaxOverride) localStorage.setItem(USERMAX_KEY, String(v));
            else localStorage.removeItem(USERMAX_KEY);
            renderHeatZones();
        });
    }

    // ── Map init ──────────────────────────────────────────────────────────
    function initMap() {
        if (initialized) return;
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
        var dataMax = heatData.max || 0;
        var max = effectiveMax(dataMax);

        for (var i = 0; i < zones.length; i++) {
            var z = zones[i];
            var val = z.runtime_minutes || 0;
            var color = heatColor(val, max);
            var opacity = val > 0 ? 0.75 : 0.06;
            var style = {
                color: 'transparent',   // no outline
                weight: 0,
                fillColor: color,
                fillOpacity: opacity,
            };
            var label = (z.code || '') + ' ' + (z.name || '');
            var detail = '运行 ' + val + ' 分钟';
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
                poly.addTo(zoneLayer);
                polys.push(poly);
            }
            if (polys.length) polygonByZoneId[z.id] = polys;
        }

        // Legend max label + gradient bar.
        var maxLabel = document.getElementById('irrigHeatMaxLabel');
        if (maxLabel) {
            maxLabel.textContent = (userMaxOverride && userMaxOverride > 0)
                ? '色阶上限: ' + userMaxOverride + ' 分钟 (最大值 ' + dataMax + ')'
                : '最大: ' + dataMax + ' 分钟';
        }
        var bar = document.getElementById('irrigHeatLegendBar');
        if (bar) {
            bar.style.background = 'linear-gradient(to right, rgb(40,180,90), rgb(250,210,40), rgb(200,30,30))';
        }
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
        // Rank by runtime descending so the heaviest-irrigated zones surface.
        matches.sort(function (a, b) {
            return (b.runtime_minutes || 0) - (a.runtime_minutes || 0);
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
            for (var ri = 0; ri < matches.length; ri++) {
                var m = matches[ri];
                var mins = m.runtime_minutes || 0;
                // data-id drives the click handler; escaping mirrors map.js.
                var safeCode = _esc(m.code || '');
                var safeName = _esc(m.name || '');
                html += '<div class="irrig-result-row" data-zone-id="' + m.id + '">' +
                    '<div class="irrig-result-label">' +
                    '<span class="irrig-result-code">' + safeCode + '</span>' +
                    safeName +
                    '</div>' +
                    '<span class="irrig-result-mins">' + mins + ' 分</span>' +
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
            // Open the mobile-friendly boundary drawing page.
            html += '<div class="irrig-unmapped-row">' +
                '<div class="irrig-unmapped-label">' +
                '<span class="irrig-unmapped-code">' + _esc(it.code) + '</span>' +
                _esc(it.name || '') +
                '</div>' +
                '<span class="irrig-unmapped-mins">' + (it.runtime_minutes || 0) + ' 分</span>' +
                '<a class="irrig-unmapped-draw" href="/settings/zone/quick-draw/mobile" '
                + 'target="_blank" rel="noopener" title="绘制 ' + _esc(it.code) + ' 边界">绘制</a>' +
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

    // ── Public API ────────────────────────────────────────────────────────
    window.switchIrrigView = switchIrrigView;
    window.loadIrrigHeatmap = loadIrrigHeatmap;
    window.searchIrrigZone = searchZone;
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
