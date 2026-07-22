/* stats-heatmap.js — Leaflet map for the 数据报表 (stats) heatmap tab.
 *
 * Draws zone boundaries colored by a selectable metric (report count / hours
 * / difficult-or-pending), with Land-name watermarks that adapt to zoom level.
 * Adapted from map.js (dashboard) but stripped to only the polygon + watermark
 * logic needed here — no pipelines, landmarks, zone-labels, or layer panel.
 */
(function () {
    'use strict';

    var map = null;
    var zoneLayer = null;           // L.layerGroup holding the heat polygons
    var wmLayer = null;             // watermark markers
    var heatData = null;            // last fetched {zones, max}
    var currentMetric = 'reports';  // 'reports' | 'hours' | 'team_hours' | 'third_hours' | 'entries'
    var filterDifficult = false;    // when true, only count is_difficult reports
    var filterPending = false;      // when true, only count is_pending_repair reports
    var currentGranularity = 'zone'; // 'zone' | 'name' | 'land' — map + table grouping
    var selectedWorkers = null;     // null = all workers; otherwise array of worker IDs
    var userMaxOverride = null;     // user color-scale cap (null = auto, use data max)

    // ── Map init (center/bounds/tiles mirror the dashboard map) ────────────
    function initMap() {
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

        map = L.map('statsHeatMap', {
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
        window._statsHeatMap = map;

        zoneLayer = L.layerGroup().addTo(map);
        wmLayer = L.layerGroup().addTo(map);

        // Watermarks re-render on zoom (size/visibility tiers).
        map.on('zoomend', function () { renderWatermarks(); });
    }

    // ── Boundary format helpers ────────────────────────────────────────────
    // The dashboard stores boundaries in 3 possible shapes:
    //   1. Single ring:       [{lat,lng}, ...]
    //   2. Flat multi-ring:   [[{lat,lng},...], [{lat,lng},...]]
    //   3. Nested multi-group:[[[[lat,lng],...]], ...]  (outer + holes)
    // The distinguishing factor is the type of bp[0]:
    //   • dict  → single ring (case 1)
    //   • array of dicts  → flat multi-ring (case 2, the most common shape)
    //   • array of arrays  → nested multi-group (case 3)
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
            // Case 1: single ring of point dicts/arrays.
            var ring = first && typeof first === 'object' ? bp.map(toLL).filter(Boolean) : [];
            return ring.length >= 3 ? [ring] : [];
        }
        // first is an array — is it a ring (of dicts) or a group (of rings)?
        var inner = first[0];
        if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
            // Case 2: flat multi-ring — each element is a ring of point dicts.
            return bp.map(function (r) {
                var rr = (r || []).map(toLL).filter(Boolean);
                return rr.length >= 3 ? rr : null;
            }).filter(Boolean);
        }
        // Case 3: nested multi-group — take the first (outer) ring of each group.
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

    // ── Color gradient: green → yellow → red (all metrics use this) ───────
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
    // parseFloat: hours metrics are fractional.
    var USERMAX_KEY = 'statsHeatUserMax';
    function effectiveMax(dataMax) {
        return (userMaxOverride && userMaxOverride > 0) ? userMaxOverride : (dataMax || 0);
    }
    function loadUserMax() {
        var v = parseFloat(localStorage.getItem(USERMAX_KEY) || '');
        userMaxOverride = (!isNaN(v) && v > 0) ? v : null;
    }
    function initUserMaxControl() {
        var input = document.getElementById('statsHeatUserMax');
        if (!input || input.dataset.bound) return;
        input.dataset.bound = '1';
        loadUserMax();
        if (userMaxOverride) input.value = userMaxOverride;
        input.addEventListener('input', function () {
            var v = parseFloat(input.value);
            userMaxOverride = (!isNaN(v) && v > 0) ? v : null;
            if (userMaxOverride) localStorage.setItem(USERMAX_KEY, String(v));
            else localStorage.removeItem(USERMAX_KEY);
            renderHeatZones();
        });
    }

    // ── Filter helpers ─────────────────────────────────────────────────────
    // When a filter is active, read from the zone's f_difficult / f_pending /
    // f_risk sub-dict instead of the top-level values. Both filters on = risk
    // (疑难 OR 待修).
    function activeScope(z) {
        if (filterDifficult && filterPending) return z.f_risk;
        if (filterDifficult) return z.f_difficult;
        if (filterPending) return z.f_pending;
        return z;
    }

    // ── Grouping helper: build render groups from the right data level ─────
    // 'zone'  → each zone is its own group (uses heatData.zones).
    // 'name'  → one group per name (uses pre-aggregated heatData.names).
    // 'land'  → one group per land (uses pre-aggregated heatData.lands).
    // For name/land, we still collect the boundary rings from the child zones so
    // the map draws all polygons in that group with the same color.
    function groupZones(zones) {
        if (currentGranularity === 'zone') {
            return zones.map(function (z) {
                return {
                    key: z.id,
                    label: z.code + ' ' + (z.name || ''),
                    rings: extractRings(z.boundary_points),
                    scope: activeScope(z),
                    count: 1,
                };
            });
        }
        if (currentGranularity === 'land') {
            var lands = (heatData.lands || []);
            // Pre-build a land_name → rings lookup from zones.
            var landRings = {};
            for (var i = 0; i < zones.length; i++) {
                var ln = zones[i].land_name || '未分类';
                if (!landRings[ln]) landRings[ln] = [];
                var zRings = extractRings(zones[i].boundary_points);
                for (var r = 0; r < zRings.length; r++) landRings[ln].push(zRings[r]);
            }
            var out = [];
            for (var li = 0; li < lands.length; li++) {
                var l = lands[li];
                out.push({
                    key: l.key,
                    label: l.land_name,
                    rings: landRings[l.land_name] || [],
                    scope: activeScope(l),
                    count: 0,
                });
            }
            return out;
        }
        // 'name' granularity.
        var names = (heatData.names || []);
        var nameRings = {};
        for (var ni = 0; ni < zones.length; ni++) {
            var zn = zones[ni];
            var nk = (zn.land_name || '未分类') + '||' + (zn.name || zn.code);
            if (!nameRings[nk]) nameRings[nk] = [];
            var nr = extractRings(zn.boundary_points);
            for (var ri = 0; ri < nr.length; ri++) nameRings[nk].push(nr[ri]);
        }
        var out2 = [];
        for (var nmi = 0; nmi < names.length; nmi++) {
            var nm = names[nmi];
            out2.push({
                key: nm.key,
                label: nm.land_name + ' · ' + nm.name,
                rings: nameRings[nm.key] || [],
                scope: activeScope(nm),
                count: 0,
            });
        }
        return out2;
    }

    // activeScope works for zone dicts (top-level + f_difficult/f_pending/f_risk)
    // and name/land dicts (same shape).
    function _blankScope() {
        return { reports: 0, team_hours: 0, third_hours: 0, hours: 0 };
    }

    // ── Render zones with heat coloring ────────────────────────────────────
    function renderHeatZones() {
        if (!zoneLayer || !heatData) return;
        zoneLayer.clearLayers();

        var zones = heatData.zones;
        var groups = groupZones(zones);

        // Recompute max over the grouped data so the color scale adapts.
        var dataMax = 0;
        for (var mi = 0; mi < groups.length; mi++) {
            var v = (groups[mi].scope[currentMetric] || 0);
            if (v > dataMax) dataMax = v;
        }
        var max = effectiveMax(dataMax);

        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];
            var val = g.scope[currentMetric] || 0;
            var color = heatColor(val, max);
            var opacity = val > 0 ? 0.75 : 0.06;
            // No outline — matches the irrigation heatmap's clean polygon style
            // (boundary lines cluttered the map and fought the green→red fill).
            var style = {
                color: 'transparent',
                weight: 0,
                fillColor: color,
                fillOpacity: opacity,
            };
            var detail = '工单 ' + g.scope.reports +
                ' · 工时 ' + round1(g.scope.hours) + 'h (灌溉组 ' + round1(g.scope.team_hours) + 'h · 第三方 ' + round1(g.scope.third_hours) + 'h)';
            if (g.rings.length > 1) detail += ' · ' + g.rings.length + ' 个区域';
            for (var r = 0; r < g.rings.length; r++) {
                var ring = g.rings[r];
                if (ring.length < 3) continue;
                var poly = L.polygon(ring, style);
                poly.bindTooltip(g.label + '\n' + detail, { sticky: true });
                poly.addTo(zoneLayer);
            }
        }

        // Update legend max label.
        var maxLabel = document.getElementById('statsHeatMaxLabel');
        if (maxLabel) {
            var isHoursMetric = currentMetric in { 'hours': 1, 'team_hours': 1, 'third_hours': 1 };
            var suffix = isHoursMetric ? 'h' : '';
            maxLabel.textContent = (userMaxOverride && userMaxOverride > 0)
                ? '上限 ' + round1(userMaxOverride) + suffix + ' (最大 ' + round1(dataMax) + suffix + ')'
                : '最大: ' + round1(dataMax) + suffix;
        }
        // Update legend bar gradient (yellow → orange → dark red, same as zones).
        var bar = document.getElementById('statsHeatLegendBar');
        if (bar) {
            bar.style.background = 'linear-gradient(to right, rgb(40,180,90), rgb(250,210,40), rgb(200,30,30))';
        }

        renderHeatTable(zones, max);
    }

    function round1(v) { return Math.round((v || 0) * 10) / 10; }

    // ── Ranked table (left sidebar) — hierarchy: Land → Name → Zone ────────
    // Collapsible tree, all collapsed by default. Each level shows the sum of
    // its children's metric value. Leaf rows (zones) fly the map on click.
    function renderHeatTable(zones, max) {
        var body = document.getElementById('statsHeatTableBody');
        if (!body) return;

        var metricLabel = '';
        if (currentMetric === 'reports') metricLabel = '工单数';
        else if (currentMetric === 'hours') metricLabel = '总工时';
        else if (currentMetric === 'team_hours') metricLabel = '灌溉组';
        else if (currentMetric === 'third_hours') metricLabel = '第三方';
        var colEl = document.getElementById('statsHeatColMetric');
        if (colEl) colEl.textContent = metricLabel;

        var isHours = currentMetric in { 'hours': 1, 'team_hours': 1, 'third_hours': 1 };

        // Use pre-aggregated land/name data (deduplicated server-side) instead
        // of summing zone values (which would double-count multi-zone reports).
        var lands = (heatData.lands || []).map(function (l) {
            return { label: l.land_name, val: activeScope(l)[currentMetric] || 0 };
        }).filter(function (r) { return r.val > 0; })
          .sort(function (a, b) { return b.val - a.val; });

        // Build a name lookup: land -> [{label, val}] (pre-aggregated, deduped).
        var namesByLand = {};
        (heatData.names || []).forEach(function (n) {
            var v = activeScope(n)[currentMetric] || 0;
            if (v <= 0) return;
            if (!namesByLand[n.land_name]) namesByLand[n.land_name] = [];
            namesByLand[n.land_name].push({ label: n.name, val: v });
        });
        for (var lk in namesByLand) {
            namesByLand[lk].sort(function (a, b) { return b.val - a.val; });
        }

        // Zone rows grouped by land||name (these are per-zone, no dedup needed).
        var zonesByName = {};
        for (var i = 0; i < zones.length; i++) {
            var z = zones[i];
            var sc = activeScope(z);
            var v = sc[currentMetric] || 0;
            if (v <= 0) continue;
            var znKey = (z.land_name || '未分类') + '||' + (z.name || z.code);
            if (!zonesByName[znKey]) zonesByName[znKey] = [];
            zonesByName[znKey].push({ label: z.code + ' ' + (z.name || ''), val: v, zoneId: z.id });
        }
        for (var zk in zonesByName) {
            zonesByName[zk].sort(function (a, b) { return b.val - a.val; });
        }

        // Visibility by granularity.
        var showName = currentGranularity === 'name' || currentGranularity === 'zone';
        var showZone = currentGranularity === 'zone';

        var html = '';
        for (var li = 0; li < lands.length; li++) {
            var landRow = lands[li];
            var landName = landRow.label;
            var landId = 'heatL' + li;
            var landExpanded = showName;
            html += renderTreeRow(landId, null, landName, landRow.val, max, isHours, 0, true, !landExpanded);

            var landNames = namesByLand[landName] || [];
            var nameHtml = '';
            for (var ni = 0; ni < landNames.length; ni++) {
                var nmRow = landNames[ni];
                var nameKey = landName + '||' + nmRow.label;
                var nameId = landId + 'N' + ni;
                var nameExpanded = showZone;
                nameHtml += renderTreeRow(nameId, landId, nmRow.label, nmRow.val, max, isHours, 1, true, !nameExpanded, !showName);

                var nameZones = zonesByName[nameKey] || [];
                for (var zi = 0; zi < nameZones.length; zi++) {
                    nameHtml += renderTreeRow(nameId + 'Z' + zi, nameId,
                        nameZones[zi].label, nameZones[zi].val, max, isHours, 2, false, false, !showZone, nameZones[zi].zoneId);
                }
            }
            html += nameHtml;
        }
        if (!lands.length) html = '<tr><td colspan="4" style="text-align:center;color:#aaa;padding:16px;">该指标下无数据</td></tr>';
        body.innerHTML = html;

        // Wire toggle: clicking a branch row expands/collapses its children.
        body.querySelectorAll('tr.heat-toggle').forEach(function (tr) {
            tr.addEventListener('click', function (e) {
                e.stopPropagation();
                var pid = this.dataset.id;
                var arrow = this.querySelector('.heat-arrow');
                var expanded = this.classList.toggle('heat-expanded');
                if (arrow) arrow.textContent = expanded ? '▼' : '▶';
                // Toggle direct children.
                body.querySelectorAll('tr[data-parent="' + pid + '"]').forEach(function (child) {
                    child.style.display = expanded ? '' : 'none';
                    // When collapsing, also hide all descendants.
                    if (!expanded) {
                        collapseDescendants(body, child.dataset.id);
                        child.classList.remove('heat-expanded');
                        var ca = child.querySelector('.heat-arrow');
                        if (ca) ca.textContent = '▶';
                    }
                });
            });
        });
        // Click leaf row → fly to zone.
        body.querySelectorAll('tr[data-zone]').forEach(function (tr) {
            tr.addEventListener('click', function (e) {
                e.stopPropagation();
                var zid = parseInt(this.dataset.zone, 10);
                var zone = (heatData.zones || []).find(function (z) { return z.id === zid; });
                if (zone && zone.center && map) {
                    var ll = centerToLL(zone.center);
                    if (ll) map.flyTo(ll, 18, { duration: 0.8 });
                }
            });
        });
    }

    function collapseDescendants(body, parentId) {
        body.querySelectorAll('tr[data-parent="' + parentId + '"]').forEach(function (child) {
            child.style.display = 'none';
            if (child.classList.contains('heat-expanded')) {
                child.classList.remove('heat-expanded');
                var ca = child.querySelector('.heat-arrow');
                if (ca) ca.textContent = '▶';
            }
            collapseDescendants(body, child.dataset.id);
        });
    }

    function renderTreeRow(id, parentId, label, val, max, isHours, level, isBranch, collapsed, hidden, zoneId) {
        var pct = max > 0 ? Math.max(3, Math.round(val / max * 100)) : 0;
        var barColor = heatColor(val, max);
        var valDisplay = isHours ? round1(val) + 'h' : val;
        var indent = level * 16;
        var arrowChar = isBranch ? (collapsed ? '▶' : '▼') : '';
        var arrow = isBranch ? '<span class="heat-arrow">' + arrowChar + '</span> ' : '<span class="heat-arrow-spacer"></span> ';
        var classes = isBranch ? 'heat-toggle heat-branch' : 'heat-leaf';
        if (isBranch && !collapsed) classes += ' heat-expanded';
        var attrs = 'data-id="' + id + '"';
        if (parentId) attrs += ' data-parent="' + parentId + '"';
        if (zoneId != null) attrs += ' data-zone="' + zoneId + '"';
        // Row hidden when its parent level isn't the active granularity.
        var display = hidden ? ' style="display:none;"' : '';
        return '<tr class="' + classes + '"' + attrs + display + '>' +
            '<td class="heat-label" style="padding-left:' + (8 + indent) + 'px;">' + arrow + _esc(label) + '</td>' +
            '<td class="num heat-val">' + valDisplay + '</td>' +
            '<td class="heat-bar-cell"><div class="heat-bar" style="width:' + pct + '%;background:' + barColor + ';"></div></td>' +
            '</tr>';
    }

    function _esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ── Watermarks (Land names that scale with zoom) ───────────────────────
    // The API returns center as {lat, lng} (dict from get_zone_center).
    function centerToLL(c) {
        if (!c) return null;
        if (Array.isArray(c)) return [c[0], c[1]];
        if (c.lat != null && c.lng != null) return [c.lat, c.lng];
        return null;
    }
    function computeLandCentroids() {
        if (!heatData) return {};
        var landPts = {};  // landName -> [[lat,lng],...]
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
        // Size tiers (mirrors dashboard): 15-16 small, 17 medium, >=18 large.
        var base = 25;
        var size = zoom <= 16 ? Math.round(base * 0.7) :
                   zoom === 17 ? Math.round(base * 1.2) :
                   Math.round(base * 1.2);

        for (var name in landWm) {
            var center = landWm[name];
            var icon = L.divIcon({
                className: 'stats-heat-watermark',
                html: '<div style="transform:translate(-50%,-50%);white-space:nowrap;">' +
                      '<span style="font-size:' + size + 'px;color:rgba(255,255,255,0.55);' +
                      'font-weight:700;text-shadow:0 0 8px rgba(0,0,0,0.4);pointer-events:none;">' +
                      name + '</span></div>',
                iconSize: [0, 0],
            });
            L.marker(center, { icon: icon, interactive: false }).addTo(wmLayer);
        }
    }

    // ── Data fetch ─────────────────────────────────────────────────────────
    // Reads the page's current date range from the URL query string so the
    // heatmap stays in sync with whatever ?from=/&to=/&week= the user picked.
    function currentRangeParams() {
        var url = new URL(window.location.href);
        var params = new URLSearchParams();
        ['from', 'to', 'week'].forEach(function (key) {
            var val = url.searchParams.get(key);
            if (val) params.set(key, val);
        });
        return params.toString();
    }

    function loadZoneHeatmap() {
        var qs = currentRangeParams();
        if (selectedWorkers && selectedWorkers.length) {
            qs += (qs ? '&' : '') + 'workers=' + selectedWorkers.join(',');
        }
        fetch('/api/stats/zone-heatmap/?' + qs)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                heatData = d;
                populateWorkerDropdown(d.workers || []);
                renderHeatZones();
                renderWatermarks();
            })
            .catch(function (err) {
                console.error('[stats-heatmap] load failed', err);
            });
    }

    // ── Metric switching ───────────────────────────────────────────────────
    // currentMetric can be any of: reports, hours, team_hours, third_hours,
    // entries, difficult. The hours family (hours/team_hours/third_hours) shares
    // a single dropdown pill whose label updates to reflect the sub-selection.
    var hoursLabels = {
        'hours': '总工时',
        'team_hours': '灌溉组工时',
        'third_hours': '第三方工时',
    };

    function switchMetric(metric) {
        currentMetric = metric;
        // Active pill: the hours pill covers hours/team_hours/third_hours.
        var isHours = metric in hoursLabels;
        document.querySelectorAll('.sh-pill').forEach(function (p) {
            if (p.id === 'statsHoursPill') {
                p.classList.toggle('active', isHours);
            } else {
                p.classList.toggle('active', p.dataset.metric === metric && !isHours);
            }
        });
        // Update hours pill label + dropdown active item.
        if (isHours) {
            var pill = document.getElementById('statsHoursPill');
            if (pill) pill.textContent = hoursLabels[metric] + ' ▾';
            document.querySelectorAll('.sh-dropdown-item').forEach(function (it) {
                it.classList.toggle('active', it.dataset.sub === metric);
            });
        }
        closeHoursDropdown();
        renderHeatZones();
    }

    function toggleHoursDropdown(e) {
        if (e) e.stopPropagation();
        var menu = document.getElementById('statsHoursMenu');
        if (menu) menu.classList.toggle('open');
    }
    function closeHoursDropdown() {
        var menu = document.getElementById('statsHoursMenu');
        if (menu) menu.classList.remove('open');
    }
    function selectHoursMetric(e, sub) {
        if (e) e.stopPropagation();
        switchMetric(sub);
    }
    // Close the dropdown when clicking elsewhere.
    document.addEventListener('click', function () { closeHoursDropdown(); });

    // ── Filter toggling (疑难 / 待修) ──────────────────────────────────────
    function toggleHeatFilter() {
        filterDifficult = document.getElementById('filterDifficult').checked;
        filterPending = document.getElementById('filterPending').checked;
        // Visual feedback: highlight active filter labels.
        var dl = document.querySelector('label.stats-heat-filter:nth-of-type(1)');
        // The two filter labels — find by their checkbox id.
        document.querySelectorAll('.sh-filter').forEach(function (lbl) {
            var cb = lbl.querySelector('input[type=checkbox]');
            if (cb) lbl.classList.toggle('on', cb.checked);
        });
        renderHeatZones();
    }

    // ── Granularity switching ──────────────────────────────────────────────
    function switchGranularity(gran) {
        currentGranularity = gran;
        document.querySelectorAll('.sh-gran-pill').forEach(function (p) {
            p.classList.toggle('active', p.dataset.gran === gran);
        });
        renderHeatZones();
    }

    // ── Worker multi-select dropdown ───────────────────────────────────────
    function populateWorkerDropdown(workers) {
        var list = document.getElementById('statsWorkerList');
        if (!list) return;
        // Default: all selected (null means "no filter").
        var sel = selectedWorkers;
        var html = '';
        for (var i = 0; i < workers.length; i++) {
            var w = workers[i];
            var checked = (!sel || sel.indexOf(String(w.id)) >= 0);
            html += '<label class="stats-heat-worker-item">' +
                '<input type="checkbox" value="' + w.id + '" ' + (checked ? 'checked' : '') +
                ' onchange="onWorkerChange()"> ' + _esc(w.name) +
                '</label>';
        }
        if (!workers.length) html = '<div style="padding:8px 14px;color:#aaa;font-size:0.82rem;">无数据</div>';
        list.innerHTML = html;
        updateWorkerPillLabel(workers);
    }

    function updateWorkerPillLabel(workers) {
        var pill = document.getElementById('statsWorkerPill');
        if (!pill) return;
        var all = workers || (heatData ? heatData.workers : []) || [];
        if (!selectedWorkers || selectedWorkers.length === all.length) {
            pill.textContent = '创建人: 全部 ▾';
        } else if (selectedWorkers.length === 0) {
            pill.textContent = '创建人: 无 ▾';
        } else if (selectedWorkers.length <= 2) {
            var names = selectedWorkers.map(function (id) {
                var w = all.find(function (x) { return String(x.id) === String(id); });
                return w ? w.name : id;
            });
            pill.textContent = '创建人: ' + names.join(', ') + ' ▾';
        } else {
            pill.textContent = '创建人: ' + selectedWorkers.length + ' 人 ▾';
        }
    }

    function onWorkerChange() {
        var checkboxes = document.querySelectorAll('#statsWorkerList input[type=checkbox]');
        var checked = [];
        checkboxes.forEach(function (cb) { if (cb.checked) checked.push(cb.value); });
        var all = (heatData ? heatData.workers : []) || [];
        // If all are checked, treat as "no filter" (null) for a cleaner URL.
        selectedWorkers = (checked.length === all.length) ? null : checked;
        updateWorkerPillLabel();
        // Re-fetch with the worker filter applied server-side.
        loadZoneHeatmap();
    }

    function toggleWorkerDropdown(e) {
        if (e) e.stopPropagation();
        var menu = document.getElementById('statsWorkerMenu');
        if (menu) menu.classList.toggle('open');
        // Close other dropdowns.
        closeHoursDropdown();
    }
    function closeWorkerDropdown() {
        var menu = document.getElementById('statsWorkerMenu');
        if (menu) menu.classList.remove('open');
    }
    function selectAllWorkers(e) {
        if (e) e.stopPropagation();
        document.querySelectorAll('#statsWorkerList input[type=checkbox]').forEach(function (cb) { cb.checked = true; });
        onWorkerChange();
    }
    function clearAllWorkers(e) {
        if (e) e.stopPropagation();
        document.querySelectorAll('#statsWorkerList input[type=checkbox]').forEach(function (cb) { cb.checked = false; });
        onWorkerChange();
    }

    // ── Boot ───────────────────────────────────────────────────────────────
    window.switchStatsHeatMetric = switchMetric;
    window.toggleHoursDropdown = toggleHoursDropdown;
    window.selectHoursMetric = selectHoursMetric;
    window.toggleHeatFilter = toggleHeatFilter;
    window.switchHeatGranularity = switchGranularity;
    window.toggleWorkerDropdown = toggleWorkerDropdown;
    window.selectAllWorkers = selectAllWorkers;
    window.clearAllWorkers = clearAllWorkers;
    window.onWorkerChange = onWorkerChange;

    // Close dropdowns when clicking outside.
    document.addEventListener('click', function () { closeHoursDropdown(); closeWorkerDropdown(); });

    document.addEventListener('DOMContentLoaded', function () {
        initMap();
        initUserMaxControl();
        loadZoneHeatmap();
    });
})();
