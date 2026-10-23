/**
 * Leaflet Map Initialization and Zone Rendering
 * Handles interactive map with irrigation zones
 */

(function() {
    'use strict';
    const runtime = window.IrrigationMapRuntime;
    let labelsVisible = true;
    let watermarkCache = null;
    let zonesLoading = false;
    let pipelinesLoading = false;
    let lastZoneRefresh = 0;

    // Inject pulse animation for remark indicators
    const style = document.createElement('style');
    style.textContent = '@keyframes remark-pulse{0%{box-shadow:0 0 0 0 rgba(232,89,12,0.5)}70%{box-shadow:0 0 0 8px rgba(232,89,12,0)}100%{box-shadow:0 0 0 0 rgba(232,89,12,0)}}';
    document.head.appendChild(style);

    // Map instance
    let map;
    let userMarker = null;
    let userAccuracyCircle = null;

    // Satellite tile layer (Esri World Imagery - works globally)
    const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: '<a href="https://www.esri.com" target="_blank" style="font-size:9px;color:#888">Esri</a>',
        maxNativeZoom: 19,
        maxZoom: 22
    });

    // 高倍补底曾用 GeoQ（GCJ-02 火星坐标，与 WGS-84 卫星图错开 ~400m，且多数
    // 网络连不上 map.geoq.cn）——已移除。19 级以上由 satelliteLayer 的
    // maxNativeZoom 拉伸补足，画面略糊但坐标可信。

    // Zone layers group
    let zonesLayerGroup;

    // Pipeline layers group
    let pipelinesLayerGroup;
    let cadReferenceLayerGroup;
    let cadNotesLayerGroup;
    let cadUnmatchedLayerGroup;
    // Rendered valve markers + their tooltip content, so a zoomend handler can
    // flip labels to permanent (auto-show) at max zoom, hover-only otherwise.
    let valveMarkersForLabels = [];

    // Zone label layers group (separate from boundaries for independent toggle)
    let labelsLayerGroup;

    // Leader lines layer group (separate from labels for independent toggle)
    let leaderLinesLayerGroup;
    // Per-ring sublabel markers for multi-boundary zones (shown when 连线 is OFF)
    let ringLabelsLayerGroup;

    // Landmark overlay layers group (off by default, toggled via layer control)
    let landmarksLayerGroup;

    // Zone code label markers
    let zoneLabels = [];

    // Landmark label markers
    let landmarkLabels = [];

    // Design system status-based polygon colors
    // Map style config (from MapStyleSettings, injected by view)
    const _mapCfg = window.MAP_STYLE_CONFIG || {};
    const _bCfg = _mapCfg.boundary || {};
    const _lCfg = _mapCfg.label || {};
    const _rCfg = _mapCfg.leaderLine || {};

    // Ring anchor — centroid if inside polygon, nearest boundary point if not
    function _nearestBoundaryPoint(pts, tLat, tLng) {
        let best = Infinity, pt = null;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            const a = pts[j], b = pts[i];
            const aLat = Array.isArray(a) ? a[0] : a.lat, aLng = Array.isArray(a) ? a[1] : a.lng;
            const bLat = Array.isArray(b) ? b[0] : b.lat, bLng = Array.isArray(b) ? b[1] : b.lng;
            const dx = bLng - aLng, dy = bLat - aLat, l2 = dx * dx + dy * dy;
            let t = l2 > 0 ? ((tLng - aLng) * dx + (tLat - aLat) * dy) / l2 : 0;
            t = Math.max(0, Math.min(1, t));
            const pLat = aLat + t * dy, pLng = aLng + t * dx;
            const d = (pLat - tLat) ** 2 + (pLng - tLng) ** 2;
            if (d < best) { best = d; pt = [pLat, pLng]; }
        }
        return pt;
    }
    function _pointInRing(lat, lng, pts) {
        let inside = false;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            const a = pts[j], b = pts[i];
            const aLat = Array.isArray(a) ? a[0] : a.lat, aLng = Array.isArray(a) ? a[1] : a.lng;
            const bLat = Array.isArray(b) ? b[0] : b.lat, bLng = Array.isArray(b) ? b[1] : b.lng;
            if ((aLat > lat) !== (bLat > lat) && lng < (bLng - aLng) * (lat - aLat) / (bLat - aLat) + aLng) inside = !inside;
        }
        return inside;
    }
    function _ringAnchor(ringPts, labelLat, labelLng) {
        if (ringPts.length < 3) {
            let s1 = 0, s2 = 0;
            ringPts.forEach(p => { s1 += Array.isArray(p) ? p[0] : p.lat; s2 += Array.isArray(p) ? p[1] : p.lng; });
            return [s1 / ringPts.length, s2 / ringPts.length];
        }
        let s1 = 0, s2 = 0;
        ringPts.forEach(p => { s1 += Array.isArray(p) ? p[0] : p.lat; s2 += Array.isArray(p) ? p[1] : p.lng; });
        const cLat = s1 / ringPts.length, cLng = s2 / ringPts.length;
        if (_pointInRing(cLat, cLng, ringPts)) return [cLat, cLng];
        return _nearestBoundaryPoint(ringPts, labelLat, labelLng);
    }

    function _dash(s) {
        if (s === 'dashed') return '8 5';
        if (s === 'dotted') return '2 4';
        return null;
    }

    // Chaikin corner-cutting smoothing
    function _chaikin(pts, iterations) {
        if (iterations <= 0) return pts;
        var r = pts;
        for (var it = 0; it < iterations; it++) {
            var next = [];
            for (var i = 0; i < r.length; i++) {
                var p0 = r[i], p1 = r[(i + 1) % r.length];
                next.push({ lat: 0.75 * p0.lat + 0.25 * p1.lat, lng: 0.75 * p0.lng + 0.25 * p1.lng });
                next.push({ lat: 0.25 * p0.lat + 0.75 * p1.lat, lng: 0.25 * p0.lng + 0.75 * p1.lng });
            }
            r = next;
        }
        return r;
    }

    function _smoothLL(latlngs, iterations) {
        if (iterations <= 0) return latlngs;
        var pts = latlngs.map(function(p) { return { lat: Array.isArray(p) ? p[0] : p.lat, lng: Array.isArray(p) ? p[1] : p.lng }; });
        var s = _chaikin(pts, iterations);
        return s.map(function(p) { return [p.lat, p.lng]; });
    }

    const _smoothIter = _bCfg.smooth || 0;

    function _zoneSmooth(zone) {
        const value = Number(zone.smooth_override != null ? zone.smooth_override : _smoothIter);
        return Number.isFinite(value) ? Math.max(0, Math.min(3, Math.floor(value))) : 0;
    }

    // Default zone style (fallback when no status)
    const defaultStyle = {
        color: '#2D6A4F',
        weight: _bCfg.weight ?? 2,
        opacity: _bCfg.opacity ?? 0.8,
        fillColor: '#2D6A4F',
        fillOpacity: _bCfg.fillOpacity != null ? _bCfg.fillOpacity : 0.12,
        dashArray: _dash(_bCfg.dashStyle),
        interactive: true   // required under preferCanvas so click/hover fire
    };

    // Highlighted/selected zone style (user-clicked) — red
    const highlightStyle = {
        color: '#C0392B',
        weight: 3,
        opacity: 1,
        fillColor: '#C0392B',
        fillOpacity: 0.3
    };
    // "Needs attention" style — orange. Used when a zone has unconfirmed remarks or an
    // unresolved 待修 work report (needs_attention flag from the payload).
    const attentionStyle = {
        color: '#CC7722',
        weight: _bCfg.weight ?? 2,
        opacity: _bCfg.opacity ?? 0.7,
        fillColor: '#CC7722',
        fillOpacity: _bCfg.fillOpacity != null ? _bCfg.fillOpacity : 0.15,
        dashArray: _dash(_bCfg.dashStyle),
        interactive: true
    };

    // Status-based polygon styling (from design system)
    const _bW = _bCfg.weight ?? 2;
    const _bO = _bCfg.opacity ?? 0.7;
    const _bFO = _bCfg.fillOpacity != null ? _bCfg.fillOpacity : 0.15;
    const _bD = _dash(_bCfg.dashStyle);

    const statusStyles = {
        completed: {
            color: '#40916C', weight: _bW, opacity: _bO,
            fillColor: '#40916C', fillOpacity: _bFO, dashArray: _bD
        },
        in_progress: {
            color: '#CC7722', weight: _bW, opacity: _bO,
            fillColor: '#CC7722', fillOpacity: _bFO, dashArray: _bD
        },
        unarranged: {
            color: '#888888', weight: _bW, opacity: _bO,
            fillColor: '#888888', fillOpacity: _bFO, dashArray: _bD
        },
        canceled: {
            color: '#9B2226', weight: _bW, opacity: _bO,
            fillColor: '#9B2226', fillOpacity: _bFO, dashArray: _bD
        },
        delayed: {
            color: '#7B5544', weight: _bW, opacity: _bO,
            fillColor: '#7B5544', fillOpacity: _bFO, dashArray: _bD
        },
        // Legacy status names for backwards compatibility
        done: {
            color: '#40916C', weight: _bW, opacity: _bO,
            fillColor: '#40916C', fillOpacity: _bFO, dashArray: _bD
        },
        working: {
            color: '#CC7722', weight: _bW, opacity: _bO,
            fillColor: '#CC7722', fillOpacity: _bFO, dashArray: _bD
        },
        scheduled: {
            color: '#52B788', weight: _bW, opacity: _bO,
            fillColor: '#52B788', fillOpacity: _bFO, dashArray: _bD
        }
    };

    /**
     * Get style for a zone based on its status
     * @param {string} status - Zone status
     * @returns {Object} Leaflet style object
     */
    function getStyleForStatus(status) {
        return statusStyles[status] || defaultStyle;
    }

    /**
     * Initialize the map
     */
    function initMap() {
        // Center point adjusted ~1.07km north-east, bounds (3km radius)
        const centerLat = 31.145663;
        const centerLng = 121.655407;
        const latOffset = 0.027; // ~3km in latitude
        const lngOffset = 0.032; // ~3km in longitude at lat 31°

        const southWest = L.latLng(centerLat - latOffset, centerLng - lngOffset);
        const northEast = L.latLng(centerLat + latOffset, centerLng + lngOffset);
        const bounds = L.latLngBounds(southWest, northEast);
        const viewKey = 'irrigation-map-view:' + (document.querySelector('.pwa-bottom-nav')?.dataset.userId || '');
        let savedView = null;
        try { savedView = runtime.readView(window.sessionStorage, viewKey); } catch (_) {}
        if (savedView && !bounds.contains(savedView.center)) savedView = null;

        // Create map centered on location with satellite layer.
        // preferCanvas: render 1100+ zone polygons on a single <canvas> instead of one
        // SVG element each. This cuts ~1100 DOM nodes on mobile and makes pan/zoom far
        // smoother (canvas redraw is GPU-friendly; SVG re-layout per element is not).
        map = L.map('map', {
            center: savedView?.center || [centerLat, centerLng],
            zoom: savedView?.zoom || 15,
            maxZoom: 22,
            minZoom: 15,
            maxBounds: bounds,
            maxBoundsViscosity: 1.0,
            layers: [satelliteLayer],
            zoomControl: false,
            preferCanvas: true,
            // Touch: the map must own pan + pinch-zoom (mobile users pinch the map
            // to zoom, never the page — page zoom is locked via the viewport meta).
            dragging: true,
            touchZoom: true,
        });

        L.control.zoom({zoomInText: window.uiIcon('plus'), zoomOutText: window.uiIcon('minus')}).addTo(map);

        // Expose map instance for external use (sidebar resize)
        window._map = map;
        map.on('moveend', function () {
            const center = map.getCenter();
            try { window.sessionStorage.setItem(viewKey, JSON.stringify({center:[center.lat, center.lng], zoom:map.getZoom()})); } catch (_) {}
        });

        // Initialize leader lines layer group (rendered below zones so boundaries occlude lines)
        leaderLinesLayerGroup = L.layerGroup().addTo(map);

        // Ring sublabels: small per-boundary labels shown when 连线 is OFF (instead of
        // a single label at the zone centroid with leader lines). Rendered above zones.
        ringLabelsLayerGroup = L.layerGroup().addTo(map);
        // Global toggle: when true show leader lines; when false show the
        // per-ring sublabels. Default OFF (sublabels) — 连线 must be opted in.
        window._leaderLinesVisible = false;

        // Initialize zones layer group (rendered on top of leader lines)
        zonesLayerGroup = L.layerGroup().addTo(map);
        window._dashboardZonesLayer = zonesLayerGroup;

        // Initialize pipelines layer group
        pipelinesLayerGroup = L.layerGroup().addTo(map);
        cadReferenceLayerGroup = L.layerGroup();
        cadNotesLayerGroup = L.layerGroup();
        cadUnmatchedLayerGroup = L.layerGroup().addTo(map);

        // Initialize labels layer group (separate for independent layer control)
        labelsLayerGroup = L.layerGroup().addTo(map);

        // Watermark layer for 通称 at xx-xx zoom level
        window.__wmLayer = L.layerGroup().addTo(map);

        // Initialize landmarks layer group (not added by default - user toggles via layer control)
        landmarksLayerGroup = L.layerGroup();

        // Load and render zones
        loadZones();

        // Load and render pipelines
        loadPipelines();

        // During the zoom animation Leaflet CSS-transforms every label DOM node
        // (~1100) each frame — the main source of zoom lag. Hide them instantly at
        // zoomstart via a CSS class (see .map-zooming in style.css) so they leave the
        // render tree entirely during the animation.
        map.on('zoomstart', function () {
            map.getContainer().classList.add('map-zooming');
        });
        // Re-layout labels on zoomend (debounced). updateLabelSizes re-applies the
        // correct per-element display, then clears the zooming class so labels
        // reappear with the right layout (see _updateLabelSizesAndClearZoom wrapper).
        map.on('zoomend', updateLabelSizesDebounced);
        map.on('zoomend', applyValveLabelMode);   // valve labels: auto at max zoom, hover below
        map.on('zoomend', updatePipeOverlayTiers); // pipe overlays: valve dots from z17
        // 最大层级平移后重排阀门常显 label（碰撞结果是视口相关的）；均防抖。
        let _valveRelayoutT = null;
        map.on('moveend', function () {
            if (map.getZoom() < map.getMaxZoom()) return;
            clearTimeout(_valveRelayoutT);
            _valveRelayoutT = setTimeout(layoutValveLabels, 250);
        });
        // Re-cull labels to the viewport after panning so only on-screen labels render.
        map.on('moveend', _cullLabelsToViewportDebounced);

        // Close popup when clicking on empty map space
        map.on('click', function(e) {
            if (window._v2ModalMapMode) return;
            // If a polygon was just clicked, don't hide the popup
            if (_polygonJustClicked) return;
            // Only close if click was directly on the map, not on a polygon
            if (e.originalEvent && e.originalEvent.target && e.originalEvent.target.closest('.leaflet-overlay-pane')) return;
            hideZonePopup();
        });
    }

    /**
     * Load zones from the API endpoint (preferred) or the embedded JSON fallback.
     *
     * The zone payload is ~5MB, so it is no longer inlined in the dashboard HTML.
     * Instead it is fetched async from /api/zones-payload/ where it can be gzipped
     * (~0.3MB on the wire) and cached by the browser (1 min). A loading overlay is
     * shown over the map until the zones render.
     */
    function applyZones(zones) {
        if (!Array.isArray(zones)) throw new Error('Invalid zone payload');
        window.zonesData = zones;
        window._zoneById = {};
        zones.forEach(function (z) { window._zoneById[z.id] = z; });
        // Remark grouping uses the same geometry as the map, without making
        // the HTML request decode every zone's boundaries a second time.
        const remarked = zones.filter(z => z.has_remarks);
        const centers = remarked.map(z => runtime.point(z.center)).filter(Boolean);
        _pendingRemarkZoneIds = new Set(remarked.map(z => z.id));
        _pendingRemarksData = centers.length ? {
            count:remarked.length, zone_ids:remarked.map(z => z.id),
            center:{lat:centers.reduce((sum,c) => sum+c[0],0)/centers.length,
                lng:centers.reduce((sum,c) => sum+c[1],0)/centers.length}
        } : null;
        return renderZones(zones).then(() => {
            lastZoneRefresh = Date.now();
            var ov = document.getElementById('zone-loading-overlay');
            if (ov) ov.style.display = 'none';
            document.getElementById('map').dataset.zonesState = 'ready';
            document.dispatchEvent(new CustomEvent('irrigation:zones-ready'));
        });
    }

    function loadZones() {
        if (zonesLoading) return;
        zonesLoading = true;
        var overlay = document.getElementById('zone-loading-overlay');
        if (overlay) overlay.style.display = '';
        const message = document.getElementById('zoneLoadingMessage');
        const spinner = document.getElementById('zoneLoadingSpinner');
        const retry = document.getElementById('zoneLoadingRetry');
        if (message) message.textContent = '加载区域数据…';
        if (spinner) spinner.hidden = false;
        if (retry) { retry.hidden = true; retry.onclick = loadZones; }
        document.getElementById('map').dataset.zonesState = 'loading';

        // Legacy fallback: if the page still inlines the zones JSON, use it directly.
        var zonesDataElement = document.getElementById('zones-data');
        const request = zonesDataElement && zonesDataElement.textContent.trim()
            ? Promise.resolve().then(() => JSON.parse(zonesDataElement.textContent))
            : runtime.fetchJSON('/api/zones-payload/', {timeout:120000});
        request.then(applyZones)
            .catch(function (err) {
                console.error('Failed to load zones:', err);
                if (spinner) spinner.hidden = true;
                if (message) message.textContent = '区域加载失败，请检查网络后重试。';
                if (retry) retry.hidden = false;
                document.getElementById('map').dataset.zonesState = 'error';
            }).finally(() => { zonesLoading = false; });
    }

    /**
     * Detect if boundary_points is multi-polygon format [[{lat,lng},...], [{lat,lng},...]]
     * vs legacy single-polygon format [{lat,lng},...]
     */
    function isMultiPolygonFormat(boundaryPoints) {
        if (!boundaryPoints || boundaryPoints.length === 0) return false;
        const first = boundaryPoints[0];
        // Multi-polygon: first element is an array (of points)
        return Array.isArray(first) && first.length > 0 && (
            Array.isArray(first[0]) || (first[0] && (first[0].lat !== undefined || first[0].lng !== undefined))
        );
    }

    /**
     * Convert a single ring of points to LatLng array
     */
    function pointsToLatLngs(points) {
        return points.map(point => {
            if (Array.isArray(point)) {
                return [point[0], point[1]];
            } else if (point.lat !== undefined && point.lng !== undefined) {
                return [point.lat, point.lng];
            }
            return null;
        }).filter(p => p !== null);
    }

    /**
     * Add a zone code label at the centroid of a polygon (or custom position)
     */
    function addZoneLabel(zone) {
        const code = zone.code;
        const latLngs = zone._allLatLngs;
        const labelLat = zone.label_lat;
        const labelLng = zone.label_lng;
        const labelScale = zone.label_scale || 1.0;
        const labelAngle = zone.label_angle || 0;

        let center;
        if (labelLat != null && labelLng != null) {
            center = [labelLat, labelLng];
        } else {
            let latSum = 0, lngSum = 0, count = 0;
            latLngs.forEach(p => {
                const lat = Array.isArray(p) ? p[0] : p.lat;
                const lng = Array.isArray(p) ? p[1] : p.lng;
                if (lat !== undefined && lng !== undefined) {
                    latSum += lat;
                    lngSum += lng;
                    count++;
                }
            });
            if (count === 0) return;
            center = [latSum / count, lngSum / count];
        }

        const size = getLabelFontSize(map.getZoom()) * labelScale;
        const rotation = labelAngle ? `transform:rotate(${labelAngle}deg);` : '';
        // Build label style from config
        const _lFont = _lCfg.fontFamily || 'Noto Sans SC';
        const _lWeight = _lCfg.fontWeight || 400;
        const _lColor = _lCfg.fontColor || '#1C1C1C';
        const _lBgColor = _lCfg.bgColor || '#000000';
        const _lBgOpacity = _lCfg.bgOpacity || 0;
        const _lBgRadius = _lCfg.bgRadius || 0;
        const _lShadow = _lCfg.textShadow;
        let labelStyle = `font-size:${size}px;font-family:'${_lFont}',sans-serif;font-weight:${_lWeight};color:${_lColor};`;
        if (rotation) labelStyle += rotation;
        if (_lBgOpacity > 0) {
            const r = parseInt(_lBgColor.slice(1,3),16), g = parseInt(_lBgColor.slice(3,5),16), b = parseInt(_lBgColor.slice(5,7),16);
            labelStyle += `background:rgba(${r},${g},${b},${_lBgOpacity});padding:2px 8px;border-radius:${_lBgRadius}px;display:inline-block;`;
        }
        if (_lShadow) labelStyle += 'text-shadow:0 1px 3px rgba(0,0,0,0.6),0 0 8px rgba(0,0,0,0.3);';
        const label = L.marker(center, {
            interactive: false,
            icon: L.divIcon({
                className: 'zone-label',
                html: `<div style="transform:translate(-50%,-50%);white-space:nowrap;"><span style="${labelStyle}">${escapeHtml(getCodeForZoom(code, map.getZoom()))}</span></div>`,
                iconSize: null,
                iconAnchor: [0, 0]
            })
        });
        label._zone = zone;
        label._originalCenter = center;
        // Attach only labels needed at this zoom/viewport. At overview zoom
        // thousands of hidden markers otherwise enter the DOM before hiding.
        zoneLabels.push(label);

        // Multi-boundary zones: build BOTH the leader lines (shown when 连线 is ON) and
        // small per-ring sublabels (shown when 连线 is OFF). Initial visibility follows
        // the global toggle so the 连线 layer switch is instant (no re-render needed).
        if (zone._mapRings && zone._mapRings.length > 1) {
            label._leaderLines = [];
            label._ringLabels = [];
            const showLines = window._leaderLinesVisible;
            const ringLabelSize = Math.round((_lCfg.fontSize || 25) * 0.7);
            zone._mapRings.forEach((ringPts, ringIndex) => {
                if (ringPts.length < 3) return;
                const smoothPts = zone._renderRings[ringIndex];
                const ringCenter = _ringAnchor(smoothPts, center[0], center[1]);
                // Leader line from the zone centroid to this ring's anchor
                const line = L.polyline([center, ringCenter], {
                    color: zone.needs_attention ? '#CC7722' : '#2D6A4F',
                    weight: _rCfg.weight || 2.5,
                    opacity: _rCfg.opacity != null ? _rCfg.opacity : 0.55,
                    dashArray: _dash(_rCfg.dashStyle),
                    interactive: false
                });
                if (!showLines) line.setStyle({ opacity: 0 });
                label._leaderLines.push(line);
                // Small sublabel centered on the ring (shown only when 连线 is OFF).
                // Visibility is controlled solely by syncMultiBoundaryDisplay() via
                // display:none/'' — never embed opacity here, or it would fight that logic.
                const sub = L.marker(ringCenter, {
                    interactive: false,
                    icon: L.divIcon({
                        className: 'zone-ring-label',
                        html: `<div style="transform:translate(-50%,-50%);white-space:nowrap;">
                            <span style="font-size:${ringLabelSize}px;color:#1B4332;font-weight:600;background:rgba(255,255,255,0.7);padding:0 3px;border-radius:3px;">${escapeHtml(zone.code)}</span>
                        </div>`,
                        iconSize: null, iconAnchor: [0, 0]
                    })
                });
                label._ringLabels.push(sub);
            });
        }

        return label;
    }

    /**
     * Minimum zoom level to show zone labels
     */
    const LABEL_MIN_ZOOM = 15;

    /**
     * Return the code display string based on zoom level.
     * xx-xx-xx → zoomed out: "xx", mid: "xx-xx", zoomed in: "xx-xx-xx"
     */
    function getCodeForZoom(code, zoom) {
        const parts = code.split('-');
        if (parts.length <= 1 || zoom >= 18) return code;
        if (zoom >= 17) return parts.slice(0, 2).join('-');
        return parts[0];
    }

    /**
     * Calculate label font size based on zoom level
     */
    function getLabelFontSize(zoom) {
        const base = _lCfg.fontSize || 25;
        // Truncated code modes: use much larger base to stay readable
        if (zoom <= 16) return base * 5;       // xx mode: 5x base
        if (zoom === 17) return base * 3;       // xx-xx mode: 3x base
        return Math.max(5, Math.round(base * Math.pow(0.7, 19 - zoom)));
    }

    /**
     * Compute watermark groupings from the current zone labels.
     *
     * Returns { landWm, nameWm, landNameSet }:
     *   landWm   — landName -> centroid [lat,lng] (every land that has named zones)
     *   nameWm   — name -> { center:[lat,lng], land:landName } (dedup rules applied)
     *   landNameSet — not needed externally (kept inline below)
     *
     * Name watermark dedup rules (per requirements):
     *   - Skip a name watermark if the land it belongs to has ONLY that one distinct name.
     *   - Skip a name watermark if the name equals the land name.
     * Both rules mean "no point expanding a name level when it adds no information".
     */
    function computeWatermarks() {
        if (watermarkCache) return watermarkCache;
        // landName -> { centerSum:[lat,lng], count, names:Set }
        const landAgg = {};
        // name -> { centerSum:[lat,lng], count, land:landName }
        const nameAgg = {};
        zoneLabels.forEach(label => {
            const zone = label._zone;
            if (!zone) return;
            const c = label._originalCenter;
            if (!c) return;
            const landName = zone.land_name || null;
            const name = zone.name || null;
            if (landName) {
                if (!landAgg[landName]) landAgg[landName] = { sLat: 0, sLng: 0, count: 0, names: new Set() };
                landAgg[landName].sLat += c[0]; landAgg[landName].sLng += c[1]; landAgg[landName].count++;
                if (name) landAgg[landName].names.add(name);
            }
            if (name) {
                if (!nameAgg[name]) nameAgg[name] = { sLat: 0, sLng: 0, count: 0, land: landName };
                nameAgg[name].sLat += c[0]; nameAgg[name].sLng += c[1]; nameAgg[name].count++;
            }
        });
        // Resolve land centroids
        const landWm = {};
        Object.entries(landAgg).forEach(([landName, a]) => {
            landWm[landName] = [a.sLat / a.count, a.sLng / a.count];
        });
        // Resolve name centroids with dedup rules
        const nameWm = {};
        Object.entries(nameAgg).forEach(([name, a]) => {
            const landName = a.land;
            const landInfo = landName ? landAgg[landName] : null;
            // Skip if land has only one distinct name (nothing to disambiguate),
            // or if the name is identical to the land name (redundant).
            if (landInfo && landInfo.names.size <= 1) return;
            if (landName && name === landName) return;
            nameWm[name] = { center: [a.sLat / a.count, a.sLng / a.count], land: landName };
        });
        return watermarkCache = { landWm: landWm, nameWm: nameWm };
    }

    /**
     * Render a set of watermark markers into window.__wmLayer.
     * entries: array of { text, center, size }
     */
    function renderWatermarks(entries) {
        if (!window.__wmLayer) return;
        window.__wmLayer.clearLayers();
        entries.forEach(e => {
            if (!e.center) return;
            const wm = L.marker(e.center, {
                interactive: false,
                icon: L.divIcon({
                    className: 'zone-watermark',
                    html: `<div style="transform:translate(-50%,-50%);white-space:nowrap;">
                        <span style="font-size:${e.size}px;color:rgba(255,255,255,0.55);font-weight:700;text-shadow:0 0 8px rgba(0,0,0,0.3);pointer-events:none;">${escapeHtml(e.text)}</span>
                    </div>`,
                    iconSize: null, iconAnchor: [0, 0]
                })
            });
            window.__wmLayer.addLayer(wm);
        });
    }

    /**
     * Synchronize leader-line vs per-ring-sublabel visibility for multi-boundary zones.
     *
     * Rules:
     *   - Zone labels hidden (zoomed way out): hide BOTH leader lines and ring sublabels.
     *   - 连线 ON  (window._leaderLinesVisible): show leader lines, hide ring sublabels.
     *   - 连线 OFF: hide leader lines; show ring sublabels ONLY at the deepest zoom
     *     (zoom>=19). Earlier levels keep the map uncluttered.
     * Called after every label re-layout so the 连线 layer toggle stays consistent.
     */
    function setMarkerVisible(marker, group, visible) {
        if (visible && !group.hasLayer(marker)) group.addLayer(marker);
        else if (!visible && group.hasLayer(marker)) group.removeLayer(marker);
        const el = marker.getElement();
        if (el && visible) el.style.opacity = marker._filterMatch === false ? '0.1' : '1';
    }

    function syncMultiBoundaryDisplay(showLabels, zoom) {
        const wantLines = showLabels && window._leaderLinesVisible;
        const wantRing = showLabels && !window._leaderLinesVisible && zoom >= 19;
        const bounds = map.getBounds().pad(0.15);
        const lineOpacity = _rCfg.opacity != null ? _rCfg.opacity : 0.55;
        zoneLabels.forEach(label => {
            (label._leaderLines || []).forEach(line => {
                const visible = wantLines && bounds.intersects(line.getBounds());
                if (visible) {
                    line.setStyle({opacity: label._filterMatch === false ? 0.05 : lineOpacity});
                    if (!leaderLinesLayerGroup.hasLayer(line)) leaderLinesLayerGroup.addLayer(line);
                } else if (leaderLinesLayerGroup.hasLayer(line)) leaderLinesLayerGroup.removeLayer(line);
            });
            (label._ringLabels || []).forEach(sub => {
                sub._filterMatch = label._filterMatch;
                setMarkerVisible(sub, ringLabelsLayerGroup, wantRing && bounds.contains(sub.getLatLng()));
            });
        });
    }

    // Debounce a function by `wait` ms (trailing edge). updateLabelSizes rebuilds labels +
    // watermarks (a full pass over ~2500 zone labels), so firing it on every zoomend —
    // including rapid pinch-zoom / wheel bursts on mobile — janks the UI. Coalescing to a
    // single call after zooming settles keeps the interaction smooth.
    function _debounce(fn, wait) {
        let t = null;
        return function () {
            clearTimeout(t);
            t = setTimeout(() => { fn.apply(null, arguments); }, wait);
        };
    }
    // Wrapper: run the heavy re-layout, THEN drop the .map-zooming flag set at zoomstart.
    // Clearing the class after the layout pass (not before) avoids a flash where the CSS
    // override lifts before per-element display has been re-applied.
    function _updateLabelSizesAndClearZoom() {
        try { updateLabelSizes(); }
        finally { map.getContainer().classList.remove('map-zooming'); }
    }
    const updateLabelSizesDebounced = _debounce(_updateLabelSizesAndClearZoom, 120);

    /**
     * Hide zone labels whose center is outside the current viewport (plus a small margin).
     *
     * ~1100 label markers always live in the DOM; at full zoom most are off-screen, but
     * Leaflet still transforms every one of them on pan/zoom — the main source of mobile
     * jank. Culling to the visible viewport keeps only the few hundred on-screen labels
     * laid out, so panning stays smooth. Only meaningful at zoom>=18 (individual labels);
     * at lower zoom levels labels are already grouped/hidden.
     */
    function _cullLabelsToViewport() {
        const zoom = map.getZoom();
        if (!labelsVisible || zoom < 18) return;
        const bounds = map.getBounds().pad(0.15);
        zoneLabels.forEach(label => {
            const center = label._originalCenter;
            setMarkerVisible(label, labelsLayerGroup, !!center && bounds.contains(L.latLng(center[0], center[1])));
            const span = label.getElement()?.querySelector('span');
            if (span) {
                span.style.fontSize = (getLabelFontSize(zoom) * (label._zone?.label_scale || 1)) + 'px';
                span.textContent = label._zone?.code || '';
            }
        });
        syncMultiBoundaryDisplay(true, zoom);
    }
    const _cullLabelsToViewportDebounced = _debounce(_cullLabelsToViewport, 80);

    function updateLabelSizes() {
        const zoom = map.getZoom();
        const showLabels = labelsVisible && zoom >= LABEL_MIN_ZOOM;
        const baseSize = getLabelFontSize(zoom);
        const representatives = new Map();
        if (showLabels && zoom === 17) {
            const groups = new Map();
            zoneLabels.forEach(label => {
                const key = getCodeForZoom(label._zone.code, zoom);
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(label);
            });
            groups.forEach((labels, key) => {
                const centers = labels.map(l => l._originalCenter).filter(Boolean);
                const center = centers.length ? [
                    centers.reduce((sum,c) => sum+c[0],0)/centers.length,
                    centers.reduce((sum,c) => sum+c[1],0)/centers.length
                ] : labels[0]._originalCenter;
                representatives.set(labels[0], {center, code:key});
            });
        }
        zoneLabels.forEach(label => {
            const grouped = representatives.get(label);
            const center = grouped ? grouped.center : label._originalCenter;
            if (center) label.setLatLng(center);
            const visible = showLabels && zoom === 17 && !!grouped;
            // Full-zoom visibility is applied by viewport culling below.
            if (zoom < 18 || !showLabels) setMarkerVisible(label, labelsLayerGroup, visible);
            const span = label.getElement()?.querySelector('span');
            if (span && grouped) {
                span.style.fontSize = (baseSize * (label._zone.label_scale || 1)) + 'px';
                span.textContent = grouped.code;
            }
        });
        const entries = [];
        if (showLabels) {
            const wm = computeWatermarks();
            const size = zoom < 17 ? Math.round(baseSize * 0.7)
                : Math.max(Math.round(baseSize * 1.2), Math.round(getLabelFontSize(17) * 1.2));
            Object.entries(wm.landWm).forEach(([text, center]) => entries.push({text, center, size}));
            if (zoom > 18) Object.entries(wm.nameWm).forEach(([text, info]) => {
                entries.push({text, center:info.center, size:Math.round(size * 0.49)});
            });
        }
        renderWatermarks(entries);
        if (showLabels && zoom >= 18) _cullLabelsToViewport();
        else syncMultiBoundaryDisplay(showLabels, zoom);
        landmarkLabels.forEach(label => {
            const el = label.getElement();
            if (el) {
                el.style.display = showLabels ? '' : 'none';
                const span = el.querySelector('span');
                if (span && showLabels) span.style.fontSize = (baseSize * 0.85) + 'px';
            }
        });
    }

    // ── Pending water requests: one marker per request, with zone boundaries highlighted ──
    // Populated from the inline #pending-water-requests JSON (one entry per request).
    var _pendingWaterRequests = [];
    var _pendingWaterZoneIds = new Set();
    var _pendingWaterLayer = null;
    (function loadPendingWaterRequests() {
        var el = document.getElementById('pending-water-requests');
        if (!el || !el.textContent.trim()) return;
        try {
            _pendingWaterRequests = JSON.parse(el.textContent) || [];
            _pendingWaterRequests.forEach(function (r) {
                (r.zone_ids || []).forEach(function (zid) { _pendingWaterZoneIds.add(zid); });
            });
        } catch (e) { _pendingWaterRequests = []; }
    })();
    // Orange outline used for zones covered by a pending water request.
    var pendingWaterStyle = {
        color: '#E8590C', weight: 3, opacity: 0.95,
        fillColor: '#E8590C', fillOpacity: 0.10, dashArray: null
    };

    /**
     * Resolve a safe [lat,lng] for a GROUP marker (remarks / water request).
     *
     * The server averages the centroids of every included zone; when those zones are
     * far apart the average lands in empty space (no zone under it). This falls back:
     * if the center isn't inside any included zone's bounds, snap to the bounding-box
     * center of the NEAREST included zone — guaranteeing the marker always sits on a
     * real zone rather than floating in the map void.
     */
    function _placeGroupMarker(center, zoneIds) {
        if (!center) return null;
        var target = L.latLng(center.lat, center.lng);
        var included = new Set(zoneIds || []);
        // Collect the rendered layers for the included zones.
        var layers = [];
        zonesLayerGroup.eachLayer(function (l) {
            if (l.zoneData && included.has(l.zoneData.id) && l.getBounds) layers.push(l);
        });
        if (!layers.length) return [center.lat, center.lng];
        // 1. Is the computed center inside any included zone's bounds?
        for (var i = 0; i < layers.length; i++) {
            if (layers[i].getBounds().contains(target)) return [center.lat, center.lng];
        }
        // 2. Fallback: nearest included zone's bounding-box center.
        var best = null, bestDist = Infinity;
        layers.forEach(function (l) {
            var c = l.getBounds().getCenter();
            var d = c.distanceTo(target);
            if (d < bestDist) { bestDist = d; best = c; }
        });
        return best ? [best.lat, best.lng] : [center.lat, center.lng];
    }

    // ── Pending remarks: one marker for all zones with unconfirmed remarks ──
    var _pendingRemarksData = null;
    var _pendingRemarkZoneIds = new Set();
    var _pendingRemarksLayer = null;
    (function loadPendingRemarks() {
        var el = document.getElementById('pending-remarks');
        if (!el || !el.textContent.trim() || el.textContent.trim() === 'null') return;
        try {
            _pendingRemarksData = JSON.parse(el.textContent);
            (_pendingRemarksData.zone_ids || []).forEach(function (zid) { _pendingRemarkZoneIds.add(zid); });
        } catch (e) { _pendingRemarksData = null; }
    })();

    function renderPendingRemarksMarker() {
        if (_pendingRemarksLayer) { map.removeLayer(_pendingRemarksLayer); _pendingRemarksLayer = null; }
        if (!_pendingRemarksData || !_pendingRemarksData.center) return;
        var d = _pendingRemarksData;
        var pos = _placeGroupMarker(d.center, d.zone_ids);
        var marker = L.marker(pos, {
            icon: L.divIcon({
                className: 'pending-remarks-marker',
                html: '<div style="background:#E8590C;color:#fff;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;box-shadow:0 2px 6px rgba(0,0,0,0.3);border:2px solid #fff;cursor:pointer;animation:remark-pulse 2s infinite;">!</div>',
                iconSize: [30, 30], iconAnchor: [15, 15]
            })
        });
        marker.bindTooltip('<div style="font-size:12px;"><strong>' + window.uiIcon('clipboard') + ' 待确认备注 · ' + d.count + ' 个区域</strong><br><span style="color:#888;font-size:11px;">点击查看详情</span></div>', { direction: 'top', offset: [0, -10] });
        marker.on('click', function () {
            window.location.href = '/remarks/';
        });
        _pendingRemarksLayer = L.layerGroup([marker]).addTo(map);
    }

    function renderPendingWaterRequestMarkers() {
        if (_pendingWaterLayer) { map.removeLayer(_pendingWaterLayer); _pendingWaterLayer = null; }
        if (!_pendingWaterRequests.length) return;
        _pendingWaterLayer = L.layerGroup();
        _pendingWaterRequests.forEach(function (r) {
            if (!r.center) return;
            var pos = _placeGroupMarker(r.center, r.zone_ids);
            var marker = L.marker(pos, {
                icon: L.divIcon({
                    className: 'pending-water-request-marker',
                    html: '<div style="background:#E8590C;color:#fff;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;box-shadow:0 2px 6px rgba(0,0,0,0.3);border:2px solid #fff;cursor:pointer;">' + r.count + '</div>',
                    iconSize: [30, 30], iconAnchor: [15, 15]
                })
            });
            marker.bindTooltip('<div style="font-size:12px;">' +
                '<strong>' + window.uiIcon('drop') + ' ' + (r.request_type || r.type_display || '浇水协调') + '</strong>' +
                ' · <span style="color:#888;">' + (r.user_type || '') + '</span>' +
                ' · ' + r.count + ' 个区域<br>' +
                '<span style="color:#555;">' + (r.start || '') + ' → ' + (r.end || '') + '</span><br>' +
                '<span style="color:#888;font-size:11px;">点击查看详情</span></div>',
                { direction: 'top', offset: [0, -10] });
            marker.on('click', function () { window.location.href = '/requests/'; });
            _pendingWaterLayer.addLayer(marker);
        });
        _pendingWaterLayer.addTo(map);
    }

    /**
     * Render zones on the map (supports multi-polygon format)
     */
    function renderZones(zones) {
        zonesLayerGroup.clearLayers();
        labelsLayerGroup.clearLayers();
        if (leaderLinesLayerGroup) leaderLinesLayerGroup.clearLayers();
        if (ringLabelsLayerGroup) ringLabelsLayerGroup.clearLayers();
        zoneLabels = [];
        watermarkCache = null;

        return runtime.renderBatches(zones, zone => {
            if (!zone.boundary_points || zone.boundary_points.length === 0) {
                return;
            }

            try {
                const rings = runtime.boundaryRings(zone.boundary_points);
                if (!rings.length) return;
                zone._mapRings = rings;
                zone._renderRings = rings.map(ring => _smoothLL(ring, _zoneSmooth(zone)));
                // Color rule: green default; orange if needs_attention (unconfirmed
                // remarks OR unresolved 待修); red only when user-selected (highlight).
                // A pending water request overrides to an orange outline (the marker
                // for the request group sits at the zone centroid).
                let zoneStyle = zone.needs_attention ? attentionStyle : defaultStyle;
                if (_pendingWaterZoneIds.has(zone.id)) zoneStyle = pendingWaterStyle;
                if (_pendingRemarkZoneIds.has(zone.id)) zoneStyle = pendingWaterStyle;

                const zoneData = {
                    id: zone.id,
                    code: zone.code,
                    name: zone.name,
                    status: zone.status,
                    statusDisplay: zone.statusDisplay,
                    plantCount: zone.plant_count || zone.plantCount || 0,
                    equipmentCount: zone.equipment_count || 0,
                    pendingWorkOrders: zone.pendingWorkOrders,
                    pendingRequests: zone.pending_requests || [],
                    recentFaultCount: zone.recent_fault_count || 0,
                    priority: zone.priority || 'medium',
                    priorityDisplay: zone.priority_display || '',
                    plantNames: zone.plant_names || [],
                    sprinklerType: zone.sprinkler_type || '',
                    irrigationIntensity: zone.irrigation_intensity,
                    areaDisplay: zone.area_display || '',
                    areaSqm: zone.area_sqm,
                    patchId: zone.patch_id,
                    patchCode: zone.patch_code || '',
                    patchName: zone.patch_name || '',
                    solenoidValveSize: zone.solenoid_valve_size,
                    landscapeCoefficient: zone.landscape_coefficient,
                    plantType: zone.plant_type || '',
                    irrigationForeman: zone.irrigation_foreman || '',
                    greeneryZone: zone.greenery_zone || '',
                    greeneryForeman: zone.greenery_foreman || '',
                    pestControlZone: zone.pest_control_zone || '',
                    pestControlForeman: zone.pest_control_foreman || '',
                    terrainFeature: zone.terrain_feature || '',
                    plantFeature: zone.plant_feature || '',
                    soilMoisture: zone.soil_moisture || '',
                    currentStatus: zone.current_status || '',
                    equipmentNotes: zone.equipment_maintenance_notes || '',
                    irrigationNotes: zone.irrigation_management_notes || '',
                    recentWorkorders: zone.recent_workorders || [],
                    smooth_override: zone.smooth_override,
                    hasRemarks: zone.has_remarks || false,
                    hasConfirmedRemarks: zone.has_confirmed_remarks || false,
                    center: zone.center || null,
                };

                zone._renderRings.forEach(latLngs => {
                    const polygon = L.polygon(latLngs, zoneStyle);
                    polygon.zoneData = zoneData;
                    polygon.originalStyle = zoneStyle;
                    polygon.on('mouseover', handleMouseOver);
                    polygon.on('mouseout', handleMouseOut);
                    polygon.on('click', handleClick);
                    polygon.bindTooltip(escapeHtml(`${zone.code} ${zone.name || ''}`), {sticky: true});
                    zonesLayerGroup.addLayer(polygon);
                });
                zone._allLatLngs = rings.flat();
                addZoneLabel(zone);

                // Pending water requests are shown as a single marker per request
                // (see renderPendingWaterRequestMarkers) instead of one per zone.
                // Pending remarks are collapsed into one marker too (see
                // renderPendingRemarksMarker); confirmed-only remarks stay markerless.


            } catch (err) {
                console.error('Error creating polygon for zone:', zone.name, err);
            }
        }, { progress(done, total) {
            const message = document.getElementById('zoneLoadingMessage');
            if (message) message.textContent = '绘制区域 ' + done + ' / ' + total + '…';
        }}).then(() => {
        // Apply initial label visibility based on current zoom.
        updateLabelSizes();
        if (window.applyMapFilters) window.applyMapFilters();
        if (currentPopupZoneData?.id) {
            highlightedZoneId = null;
            highlightZonePolygons(currentPopupZoneData.id);
        }
        // One marker per pending water request (with zone boundaries already
        // highlighted via pendingWaterStyle above).
        renderPendingWaterRequestMarkers();
        // One marker for all pending-remark zones (boundaries highlighted too).
        renderPendingRemarksMarker();
        });
    }

    /**
     * Add a marker to show pending requests on a zone
     * @param {Object} zone - Zone data with pending_requests
     */
    function addPendingRequestMarker(zone) {
        const pendingCount = zone.pending_requests.length;
        if (pendingCount === 0 || !zone.center) return;

        // Create a custom icon with the count
        const markerHtml = `
            <div style="
                background: #CC7722;
                color: white;
                border-radius: 50%;
                width: 28px;
                height: 28px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 14px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                border: 2px solid white;
                cursor: pointer;
            ">${pendingCount}</div>
        `;

        const marker = L.marker([zone.center.lat, zone.center.lng], {
            icon: L.divIcon({
                className: 'pending-request-marker',
                html: markerHtml,
                iconSize: [28, 28],
                iconAnchor: [14, 14]
            })
        });

        // Concise tooltip: just the count (the list of identical 💧浇水协调 lines was
        // visual clutter when many zones shared a request).
        marker.bindTooltip(`
            <div style="font-size: 12px;">
                <strong>${window.uiIcon('drop')} 待审批浇水需求 ${pendingCount} 个</strong><br>
                <span style="color: #888; font-size: 11px;">点击查看详情</span>
            </div>
        `, {
            permanent: false,
            direction: 'top',
            offset: [0, -10]
        });

        // Click to go to requests page
        marker.on('click', function() {
            window.location.href = '/requests/';
        });

        marker.addTo(map);
    }

    /**
     * Add a remark indicator marker on a zone
     * Shows an orange dot for pending remarks, blue for confirmed-only
     */
    function addRemarkMarker(zone) {
        const hasPending = zone.has_remarks;
        const color = hasPending ? '#E8590C' : '#3B82F6';
        const label = hasPending ? '待确认备注' : '已确认备注';

        // Position marker slightly offset from center to avoid overlap with pending request markers
        const offsetLat = (zone.center.lat || 0) + 0.00015;
        const offsetLng = (zone.center.lng || 0) + 0.00015;

        const markerHtml = `
            <div style="
                background: ${color};
                color: white;
                border-radius: 50%;
                width: 14px;
                height: 14px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3);
                border: 1.5px solid white;
                ${hasPending ? 'animation: remark-pulse 2s infinite;' : ''}
            "></div>
        `;

        const marker = L.marker([offsetLat, offsetLng], {
            icon: L.divIcon({
                className: 'remark-indicator-marker',
                html: markerHtml,
                iconSize: [14, 14],
                iconAnchor: [7, 7]
            })
        });

        marker.bindTooltip(`
            <div style="font-size: 12px;">
                <strong>${label}</strong><br>
                <span style="color: #888; font-size: 11px;">点击查看区域详情</span>
            </div>
        `, {
            permanent: false,
            direction: 'top',
            offset: [0, -5]
        });

        marker.on('click', function() {
            window.location.href = '/zone/' + zone.id + '/detail/';
        });

        marker.addTo(map);
    }

    // --- Zone Profile Card Configuration ---
    const ZONE_CARD_FIELDS = [
        { key: 'priority', label: '优先级', getValue: z => z.priorityDisplay },
        { key: 'sprinklerType', label: '灌水器类型', getValue: z => z.sprinklerType },
        { key: 'irrigationIntensity', label: '灌溉强度', getValue: z => z.irrigationIntensity != null ? z.irrigationIntensity : '' },
        { key: 'area', label: '面积', getValue: z => z.areaDisplay },
        { key: 'patchInfo', label: 'CCU-灌溉分区', getValue: z => [z.patchCode, z.patchName].filter(Boolean).join(' - ') },
        { key: 'solenoidValveSize', label: '电磁阀尺寸', getValue: z => z.solenoidValveSize != null ? z.solenoidValveSize : '' },
        { key: 'landscapeCoefficient', label: '景观系数', getValue: z => z.landscapeCoefficient != null ? z.landscapeCoefficient : '' },
        { key: 'plantType', label: '植物类型', getValue: z => z.plantType },
        { key: 'irrigationForeman', label: '灌溉领班', getValue: z => z.irrigationForeman },
        { key: 'greeneryZone', label: '绿化分区', getValue: z => z.greeneryZone },
        { key: 'greeneryForeman', label: '绿化领班', getValue: z => z.greeneryForeman },
        { key: 'pestControlZone', label: '植保分区', getValue: z => z.pestControlZone },
        { key: 'pestControlForeman', label: '植保领班', getValue: z => z.pestControlForeman },
        { key: 'terrainFeature', label: '地形特点', getValue: z => z.terrainFeature },
        { key: 'plantFeature', label: '植物特点', getValue: z => z.plantFeature },
        { key: 'soilMoisture', label: '土壤湿度', getValue: z => z.soilMoisture },
        { key: 'equipmentNotes', label: '设备维护记录', getValue: z => z.equipmentNotes, isList: true },
        { key: 'irrigationNotes', label: '灌溉管理记录', getValue: z => z.irrigationNotes, isList: true },
        { key: 'recentWorkorders', label: '工单记录', getValue: z => z.recentWorkorders, isWorkorder: true },
    ];

    const CARD_SETTINGS_KEY = 'zoneProfileCardFields';
    let cardSettingsMemory = null;

    function getCardFieldSettings() {
        if (cardSettingsMemory) return cardSettingsMemory;
        try {
            const saved = localStorage.getItem(CARD_SETTINGS_KEY);
            const parsed = saved ? JSON.parse(saved) : null;
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
        } catch (e) {}
        // Default: all fields hidden
        const defaults = {};
        ZONE_CARD_FIELDS.forEach(f => { defaults[f.key] = false; });
        return defaults;
    }

    function saveCardFieldSetting(key, visible) {
        const settings = getCardFieldSettings();
        settings[key] = visible;
        cardSettingsMemory = settings;
        try { localStorage.setItem(CARD_SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* Keep the UI usable when storage is unavailable. */ }
    }

    // Currently displayed zone data (for re-rendering after settings change)
    let currentPopupZoneData = null;
    let popupSettingsOpen = false;

    function buildPopupHtml(zone) {
        if (popupSettingsOpen) return buildSettingsHtml(zone);
        return buildCardHtml(zone);
    }

    function buildCardHtml(zone) {
        const settings = getCardFieldSettings();

        // Status badge — use current_status (from data), not computed status
        const currentStatus = zone.currentStatus || '';
        const statusBadgeMap = {
            '施工中': { label: '施工中', color: '#0984e3' },
            '停浇': { label: '停浇', color: '#e17055' },
            '运行中': { label: '运行中', color: '#00b894' },
            '维修中': { label: '维修中', color: '#CC7722' },
        };
        const statusInfo = currentStatus ? (statusBadgeMap[currentStatus] || { label: currentStatus, color: '#636e72' }) : null;

        // Customizable fields
        let fieldsHtml = '';
        ZONE_CARD_FIELDS.forEach(f => {
            if (!settings[f.key]) return;
            const val = f.getValue(zone);
            if (!val && val !== 0) return;
            if (f.isList) {
                // Render notes list as compact timeline
                let entries = [];
                try { entries = typeof val === 'string' ? JSON.parse(val) : val; } catch(e) { return; }
                if (!Array.isArray(entries) || entries.length === 0) return;
                const maxShow = 5;
                const listId = 'notes_' + f.key + '_' + zone.id;
                const allHtml = entries.map(e => {
                    const d = typeof e.date === 'string' ? e.date : '';
                    const displayDate = d && d !== '日期格式错误'
                        ? d.replace(/-0*/g, '/').replace(/^20/, '')
                        : '';
                    return `<div style="display:flex;gap:4px;font-size:0.82em;padding:1px 0;"><span style="color:var(--color-primary);flex-shrink:0;min-width:56px;">${escapeHtml(displayDate)}</span><span style="color:#555;word-break:break-all;">${escapeHtml(e.content || '')}</span></div>`;
                }).join('');
                const collapsedHtml = entries.slice(0, maxShow).map(e => {
                    const d = typeof e.date === 'string' ? e.date : '';
                    const displayDate = d && d !== '日期格式错误'
                        ? d.replace(/-0*/g, '/').replace(/^20/, '')
                        : '';
                    return `<div style="display:flex;gap:4px;font-size:0.82em;padding:1px 0;"><span style="color:var(--color-primary);flex-shrink:0;min-width:56px;">${escapeHtml(displayDate)}</span><span style="color:#555;word-break:break-all;">${escapeHtml(e.content || '')}</span></div>`;
                }).join('');
                const remaining = entries.length - maxShow;
                const moreBtn = remaining > 0
                    ? `<div class="notes-expand-btn" style="font-size:0.78em;color:var(--color-primary);padding-top:1px;cursor:pointer;text-decoration:underline;" onclick="window._toggleNotesExpand('${listId}', this)">还有 ${remaining} 条记录</div>`
                    : '';
                fieldsHtml += `<div class="popup-field" style="flex-direction:column;align-items:stretch;gap:2px;"><span class="popup-field-label">${f.label}</span><div id="${listId}_collapsed" style="margin-left:0;">${collapsedHtml}${moreBtn}</div><div id="${listId}_expanded" style="margin-left:0;display:none;">${allHtml}<div class="notes-expand-btn" style="font-size:0.78em;color:var(--color-primary);padding-top:1px;cursor:pointer;text-decoration:underline;" onclick="window._toggleNotesExpand('${listId}', this)">收起</div></div></div>`;
            } else if (f.isWorkorder) {
                // Render recent workorder list as clickable rows opening detail in a new tab.
                const entries = Array.isArray(val) ? val : [];
                if (entries.length === 0) return;
                const maxShow = 5;
                const listId = 'wo_' + f.key + '_' + zone.id;
                const rowHtml = (items) => items.map(w => {
                    const id = w.id || '';
                    const date = (w.date || '').replace(/-0*/g, '/').replace(/^20/, '');
                    const sections = (w.sections || []).join('/');
                    const path = w.first_entry_path || '';
                    const url = w.detail_url || ('/work-reports/' + id + '/');
                    return `<div style="display:flex;gap:6px;font-size:0.82em;padding:2px 0;align-items:baseline;">
                        <a href="${url}" target="_blank" rel="noopener" style="color:var(--color-primary);font-weight:600;flex-shrink:0;text-decoration:none;" title="在新标签打开工单 #${id}">#${id}</a>
                        <span style="color:#888;flex-shrink:0;min-width:46px;">${escapeHtml(date)}</span>
                        ${sections ? `<span style="color:#1565c0;background:#e3f2fd;padding:0 5px;border-radius:8px;font-size:0.92em;flex-shrink:0;">${escapeHtml(sections)}</span>` : ''}
                        <span style="color:#555;word-break:break-all;flex:1;min-width:0;">${escapeHtml(path)}</span>
                    </div>`;
                }).join('');
                const collapsedHtml = rowHtml(entries.slice(0, maxShow));
                const allHtml = rowHtml(entries);
                const remaining = entries.length - maxShow;
                const moreBtn = remaining > 0
                    ? `<div class="notes-expand-btn" style="font-size:0.78em;color:var(--color-primary);padding-top:1px;cursor:pointer;text-decoration:underline;" onclick="window._toggleNotesExpand('${listId}', this)">还有 ${remaining} 条工单</div>`
                    : '';
                fieldsHtml += `<div class="popup-field" style="flex-direction:column;align-items:stretch;gap:2px;"><span class="popup-field-label">${f.label}</span><div id="${listId}_collapsed" style="margin-left:0;">${collapsedHtml}${moreBtn}</div><div id="${listId}_expanded" style="margin-left:0;display:none;">${allHtml}<div class="notes-expand-btn" style="font-size:0.78em;color:var(--color-primary);padding-top:1px;cursor:pointer;text-decoration:underline;" onclick="window._toggleNotesExpand('${listId}', this)">收起</div></div></div>`;
            } else {
                fieldsHtml += `<div class="popup-field"><span class="popup-field-label">${f.label}</span><span class="popup-field-value">${escapeHtml(val)}</span></div>`;
            }
        });

        // Fault warning
        let faultHtml = '';
        if (zone.recentFaultCount > 0) {
            faultHtml = `<div class="popup-alert">${window.uiIcon('alert')} 近30天 ${zone.recentFaultCount} 次故障</div>`;
        }

        // Pending requests
        let pendingHtml = '';
        const pendingCount = (zone.pendingRequests || []).length;
        if (pendingCount > 0) {
            pendingHtml = `<div class="popup-alert popup-alert-warn">${window.uiIcon('drop')} ${pendingCount} 个待审批浇水需求</div>`;
        }

        const hasExtra = fieldsHtml || faultHtml || pendingHtml;

        return `
            <div class="popup-card">
                <div class="popup-header">
                    <div>
                        <div class="popup-title">${escapeHtml(zone.code)} - ${escapeHtml(zone.name)}</div>
                        ${statusInfo ? `<span class="popup-status-badge" style="background: ${statusInfo.color}18; color: ${statusInfo.color};">${escapeHtml(statusInfo.label)}</span>` : ''}
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;">
                        <button class="popup-settings-btn" onclick="togglePopupSettings()" title="自定义显示字段">${window.uiIcon('settings')}</button>
                        <button class="popup-close-btn" onclick="window.hideZonePopup()" title="关闭">${window.uiIcon('close')}</button>
                    </div>
                </div>
                ${hasExtra ? '<div class="popup-fields">' + fieldsHtml + faultHtml + pendingHtml + '</div>' : ''}
                <div class="popup-footer">
                    <div class="popup-quick-actions">
                        <button class="popup-action-btn popup-action-primary" data-zone-code="${escapeHtml(zone.code)}" onclick="if(typeof window.quickWorkorder==='function')window.quickWorkorder([this.dataset.zoneCode])">${window.uiIcon('clipboard')} 创建工单</button>
                        <button class="popup-action-btn popup-action-patch" data-zone-name="${escapeHtml(zone.name || '')}" data-zone-code="${escapeHtml(zone.code)}" onclick="window._quickPatchWorkorder(this)">${window.uiIcon('layers')} 片区工单</button>
                    </div>
                    <button class="popup-detail-btn" onclick="window.location.href='/zone/${zone.id}/detail/'">查看区域详情</button>
                </div>
            </div>
        `;
    }

    function buildSettingsHtml(zone) {
        const settings = getCardFieldSettings();
        const smoothVal = zone.smooth_override != null ? zone.smooth_override : _smoothIter;
        const isCustom = zone.smooth_override != null;
        return `
            <div class="popup-card">
                <div class="popup-header">
                    <div class="popup-title" style="font-size:0.92em;">自定义显示字段</div>
                    <button class="popup-settings-btn" onclick="togglePopupSettings()" title="返回">${window.uiIcon('close')}</button>
                </div>
                <div class="popup-settings-list">
                    ${ZONE_CARD_FIELDS.map(f => `
                        <label class="popup-settings-item">
                            <input type="checkbox" ${settings[f.key] ? 'checked' : ''} onchange="handleFieldToggle('${f.key}', this.checked)">
                            <span>${f.label}</span>
                        </label>
                    `).join('')}
                </div>
                <div style="padding:10px 14px;border-top:1px solid #eee;">
                    <div style="font-size:0.82em;font-weight:600;color:#555;margin-bottom:6px;">
                        圆滑度特调
                        <label style="float:right;font-weight:400;font-size:0.78em;cursor:pointer;">
                            <input type="checkbox" id="smoothCustomToggle" ${isCustom ? 'checked' : ''} onchange="handleSmoothCustomToggle(this.checked)"> 自定义
                        </label>
                    </div>
                    <input type="range" min="0" max="3" step="1" value="${smoothVal}" id="smoothOverrideSlider"
                        style="width:100%;accent-color:#2D6A4F;" ${isCustom ? '' : 'disabled'}
                        oninput="document.getElementById('smoothOverrideVal').textContent=this.value">
                    <div style="display:flex;justify-content:space-between;font-size:0.72em;color:#999;margin-top:2px;">
                        <span>直角</span>
                        <span id="smoothOverrideVal">${smoothVal}</span>
                        <span>圆滑</span>
                    </div>
                </div>
                <div class="popup-footer">
                    <button class="popup-detail-btn" onclick="saveSmoothOverride()">保存圆滑度</button>
                </div>
            </div>
        `;
    }

    function flyToZone(zoneData, layer) {
        if (!zoneData || !map) return;
        // Resolve the target center: prefer the zone's stored center, fall back
        // to the polygon bounds center when the data lacks one.
        let center = zoneData.center;
        if ((!center || typeof center.lat !== 'number') && layer && layer.getBounds) {
            try { center = layer.getBounds().getCenter(); } catch (e) { center = null; }
        }
        if (!center) return;
        const target = (center.lat !== undefined) ? [center.lat, center.lng] : [center.lat || center[0], center.lng || center[1]];
        const cz = map.getZoom();
        // Zoom up to 19; if already past 19, keep current zoom (just pan).
        const targetZoom = cz > 19 ? cz : 19;
        map.flyTo(target, targetZoom, { animate: true, duration: 0.8 });
    }

    function showZonePopup(zoneData) {
        const panel = document.getElementById('zonePopupPanel');
        if (!panel) return;
        currentPopupZoneData = zoneData;
        popupSettingsOpen = false;
        panel.innerHTML = buildPopupHtml(zoneData);
        panel.style.display = '';
        const fw = document.getElementById('mapFilterWidget');
        if (fw) fw.style.display = 'none';
    }

    function hideZonePopup() {
        const panel = document.getElementById('zonePopupPanel');
        if (!panel) return;
        panel.style.display = 'none';
        currentPopupZoneData = null;
        popupSettingsOpen = false;
        unhighlightZonePolygons();
        document.querySelectorAll('.zone-item.active').forEach(el => el.classList.remove('active'));
        const fw = document.getElementById('mapFilterWidget');
        if (fw) fw.style.display = '';
    }

    function togglePopupSettings() {
        popupSettingsOpen = !popupSettingsOpen;
        if (currentPopupZoneData) {
            const panel = document.getElementById('zonePopupPanel');
            if (!panel) return;
            panel.innerHTML = buildPopupHtml(currentPopupZoneData);
        }
    }

    function handleFieldToggle(key, checked) {
        saveCardFieldSetting(key, checked);
        // Re-render settings view with updated state
        if (currentPopupZoneData) {
            const panel = document.getElementById('zonePopupPanel');
            if (!panel) return;
            panel.innerHTML = buildPopupHtml(currentPopupZoneData);
        }
    }

    window.showZonePopup = showZonePopup;
    window.hideZonePopup = hideZonePopup;
    window.togglePopupSettings = togglePopupSettings;
    window._dashboardZonesLayer = zonesLayerGroup;
    window.handleFieldToggle = handleFieldToggle;

    // Quick workorder from profile card — collect all zones sharing the same 通用名称 (zone.name)
    window._quickPatchWorkorder = function (btn) {
        var zoneName = btn.getAttribute('data-zone-name');
        var zoneCode = btn.getAttribute('data-zone-code');
        if (!zoneCode) return;
        var codes = [zoneCode];
        // Group by common name (zone.name); if name is empty, fall back to just this zone
        if (zoneName && window.zonesData) {
            window.zonesData.forEach(function (zone) {
                if (zone.name === zoneName && zone.code && !codes.includes(zone.code)) {
                    codes.push(zone.code);
                }
            });
        }
        if (typeof window.quickWorkorder === 'function') window.quickWorkorder(codes);
    };

    window.handleSmoothCustomToggle = function(checked) {
        const slider = document.getElementById('smoothOverrideSlider');
        if (slider) slider.disabled = !checked;
        if (!checked && slider) slider.value = _smoothIter;
    };

    window._getCSRFToken = window._getCSRFToken || function() {
        const fromInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (fromInput) return fromInput.value;
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    };

    function _smoothToast(msg) {
        let t = document.getElementById('_smoothToast');
        if (!t) { t = document.createElement('div'); t.id = '_smoothToast'; t.style.cssText = 'position:fixed;bottom:60px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:8px 20px;border-radius:6px;font-size:14px;z-index:99999;opacity:0;transition:opacity .3s;'; document.body.appendChild(t); }
        t.textContent = msg; t.style.opacity = '1';
        clearTimeout(t._timer);
        t._timer = setTimeout(() => { t.style.opacity = '0'; }, 2000);
    }

    window.saveSmoothOverride = function() {
        if (!currentPopupZoneData) return;
        const toggle = document.getElementById('smoothCustomToggle');
        const slider = document.getElementById('smoothOverrideSlider');
        const isCustom = toggle && toggle.checked;
        const val = isCustom ? parseInt(slider && slider.value) : null;

        fetch(`/zone/${currentPopupZoneData.id}/smooth/`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': window._getCSRFToken()},
            body: JSON.stringify({smooth_override: val})
        }).then(r => r.json()).then(data => {
            if (data.success) {
                currentPopupZoneData.smooth_override = data.smooth_override;
                _refreshZonePolygons(currentPopupZoneData);
                _smoothToast('圆滑度已保存');
            } else {
                _smoothToast(data.error || '保存失败');
            }
        }).catch(() => {
            _smoothToast('网络错误');
        });
    };

    function _refreshZonePolygons(zoneData) {
        const zone = (window.zonesData || []).find(z => z.id === zoneData.id);
        if (!zone) return;
        zone.smooth_override = zoneData.smooth_override;
        const wasSelected = highlightedZoneId === zone.id;
        let data = zoneData;
        zonesLayerGroup.eachLayer(layer => {
            if (layer.zoneData?.id === zone.id) {
                data = {...layer.zoneData, smooth_override:zone.smooth_override};
                zonesLayerGroup.removeLayer(layer);
            }
        });
        let style = zone.needs_attention ? attentionStyle : defaultStyle;
        if (_pendingWaterZoneIds.has(zone.id) || _pendingRemarkZoneIds.has(zone.id)) style = pendingWaterStyle;
        zone._mapRings = runtime.boundaryRings(zone.boundary_points);
        zone._renderRings = zone._mapRings.map(ring => _smoothLL(ring, _zoneSmooth(zone)));
        zone._renderRings.forEach(ring => {
            const polygon = L.polygon(ring, style);
            polygon.zoneData = data;
            polygon.originalStyle = style;
            polygon.on('mouseover', handleMouseOver);
            polygon.on('mouseout', handleMouseOut);
            polygon.on('click', handleClick);
            polygon.bindTooltip(escapeHtml(`${zone.code} ${zone.name || ''}`), {sticky:true});
            zonesLayerGroup.addLayer(polygon);
        });
        const oldLabel = zoneLabels.find(label => label._zone.id === zone.id);
        if (oldLabel) {
            labelsLayerGroup.removeLayer(oldLabel);
            (oldLabel._leaderLines || []).forEach(line => leaderLinesLayerGroup.removeLayer(line));
            (oldLabel._ringLabels || []).forEach(label => ringLabelsLayerGroup.removeLayer(label));
            zoneLabels = zoneLabels.filter(label => label !== oldLabel);
        }
        zone._allLatLngs = zone._mapRings.flat();
        if (zone._allLatLngs.length) addZoneLabel(zone);
        watermarkCache = null;
        updateLabelSizes();
        if (window.applyMapFilters) window.applyMapFilters();
        if (wasSelected) { highlightedZoneId = null; highlightZonePolygons(zone.id); }
    }
    window._toggleNotesExpand = function(listId, btn) {
        const collapsed = document.getElementById(listId + '_collapsed');
        const expanded = document.getElementById(listId + '_expanded');
        if (collapsed && expanded) {
            collapsed.style.display = collapsed.style.display === 'none' ? '' : 'none';
            expanded.style.display = expanded.style.display === 'none' ? '' : 'none';
        }
    };

    // Currently highlighted zone ID (for multi-polygon highlighting)
    let highlightedZoneId = null;
    let highlightedLayer = null;

    // Flag to prevent map click handler from hiding popup right after polygon click
    let _polygonJustClicked = false;

    /**
     * Highlight all polygons belonging to a zone
     */
    function highlightZonePolygons(zoneId) {
        if (highlightedZoneId === zoneId) return;
        unhighlightZonePolygons();
        highlightedZoneId = zoneId;
        zonesLayerGroup.eachLayer(function(layer) {
            if (layer.zoneData && layer.zoneData.id === zoneId) {
                layer.setStyle(highlightStyle);
                layer.bringToFront();
            }
        });
    }

    /**
     * Remove highlight from all polygons of the currently highlighted zone
     */
    function unhighlightZonePolygons() {
        if (highlightedZoneId === null) return;
        const prevId = highlightedZoneId;
        highlightedZoneId = null;
        // Re-apply current filter state instead of blindly restoring originalStyle
        if (typeof window.applyMapFilters === 'function') {
            window.applyMapFilters();
        } else {
            zonesLayerGroup.eachLayer(function(layer) {
                if (layer.zoneData && layer.zoneData.id === prevId) {
                    layer.setStyle(layer.originalStyle || defaultStyle);
                }
            });
        }
    }

    /**
     * Handle mouse over event on zone
     * @param {Event} e - Leaflet event
     */
    let _lastTooltipLayer = null;
    function handleMouseOver(e) {
        if (window._v2ModalMapMode) return;
        // Close previous tooltip to ensure only one visible at a time
        if (_lastTooltipLayer && _lastTooltipLayer !== e.target) {
            _lastTooltipLayer.closeTooltip();
        }
        _lastTooltipLayer = e.target;
        const layer = e.target;
        const zoneId = layer.zoneData?.id;
        if (zoneId) highlightZonePolygons(zoneId);
    }

    /**
     * Handle mouse out event on zone
     * @param {Event} e - Leaflet event
     */
    function handleMouseOut(e) {
        if (window._v2ModalMapMode) return;
        e.target.closeTooltip();
        if (currentPopupZoneData?.id) highlightZonePolygons(currentPopupZoneData.id);
        else unhighlightZonePolygons();
    }

    /**
     * Handle click event on zone polygon
     * @param {Event} e - Leaflet event
     */
    function handleClick(e) {
        if (window._v2ModalMapMode) return;
        const layer = e.target;
        const zoneId = layer.zoneData?.id;

        if (zoneId) {
            // Prevent map click handler from hiding popup right after this
            _polygonJustClicked = true;
            setTimeout(function() { _polygonJustClicked = false; }, 0);

            highlightZonePolygons(zoneId);

            // Highlight the corresponding sidebar item
            highlightSidebarItem(zoneId);

            // Zoom to zone (zoom 19, or keep current if already deeper)
            flyToZone(layer.zoneData, layer);

            // Show fixed popup panel
            showZonePopup(layer.zoneData);
        }
    }

    /**
     * Load pipelines from the payload endpoint (was: inline JSON in the
     * dashboard HTML — re-downloaded on every visit and uncached by the
     * browser). Empty #pipelines-data element is the fetch trigger, same
     * pattern as zones. Falls back to inline content if the element carries
     * data (kept for any page still embedding it).
     */
    function loadPipelines() {
        if (pipelinesLoading) return;
        const el = document.getElementById('pipelines-data');
        if (!el) return;
        const notice = document.getElementById('pipelineLoadNotice');
        const retry = document.getElementById('pipelineLoadingRetry');
        if (notice) notice.hidden = true;
        if (retry) retry.onclick = loadPipelines;
        if (el.textContent && el.textContent.trim().length > 2) {
            try {
                renderPipelines(JSON.parse(el.textContent));
                applyValveLabelMode(true);
                updatePipeOverlayTiers();
            } catch (e) { console.error('pipelines inline parse failed', e); }
            return;
        }
        pipelinesLoading = true;
        runtime.fetchJSON('/api/pipelines-payload/')
            .then(d => {
                renderPipelines(d.pipelines || []);
                renderCadReference(d.cad_reference || []);
                applyValveLabelMode(true);   // fresh markers — force rebind
                updatePipeOverlayTiers();    // valve dots follow the current zoom
            })
            .catch(err => {
                console.error('pipelines payload fetch failed', err);
                if (notice) notice.hidden = false;
            }).finally(() => { pipelinesLoading = false; });
    }

    // Valve labels: permanent (auto-shown) at the max zoom level, hover-only
    // below it — matches the zoom-tiered display used for zone watermarks and
    // boundaries so valves don't clutter the map when zoomed out.
    // Pipeline overlays follow the map's zoom tiers:
    //   tier 1 (<17): park overview — valve dots hidden
    //   tier 2 (>=17): pipe level — valve dots appear
    //   tier 3 (max zoom): valve labels become permanent (applyValveLabelMode)
    // CSS class toggles only — no per-marker work on zoom.
    function updatePipeOverlayTiers() {
        if (!map) return;
        const z = map.getZoom();
        const c = map.getContainer();
        c.classList.toggle('hide-pipe-valves', z < 17);
    }

    let _valveLabelMode = null;   // 'hover' | 'permanent' — 跨 zoom 不变则不重建
    function applyValveLabelMode(force) {
        if (!map) return;
        const isMax = map.getZoom() >= map.getMaxZoom();
        const mode = isMax ? 'permanent' : 'hover';
        if (!force && mode === _valveLabelMode) {
            // 模式没变：只做廉价的碰撞重排（平移后视口变化）
            if (isMax) layoutValveLabels();
            return;
        }
        _valveLabelMode = mode;
        valveMarkersForLabels.forEach(vm => {
            if (!vm || vm._tipContent === undefined) return;
            if (vm.getTooltip()) vm.unbindTooltip();
            vm.bindTooltip(vm._tipContent, {
                sticky: true, className: 'ref-tooltip',
                // 最大层级只常显已浇水阀门；未浇水的保持悬停显示，避免满屏
                // 未浇水 label 盖住还没读到的状态点。
                permanent: isMax && vm._watered === true
            });
        });
        if (isMax) layoutValveLabels();
    }

    // 最大层级常显的阀门 label 防重叠：贪心放置——按顺序把每个 label 的
    // 包围盒（点上方、实测尺寸 + 边距）与已放置的比较，撞了就隐藏本次缩放。
    // 缩放离开最大层级后 applyValveLabelMode 重建 tooltip，隐藏自动复原。
    function layoutValveLabels() {
        const placed = [];
        valveMarkersForLabels.forEach(vm => {
            if (!vm) return;
            const tip = vm.getTooltip();
            if (!tip || !tip.options.permanent) return;
            const el = tip.getElement();
            if (!el) return;
            const pos = map.latLngToContainerPoint(vm.getLatLng());
            const w = el.offsetWidth, h = el.offsetHeight;
            const rect = { x: pos.x - w / 2 - 3, y: pos.y - h - 12, w: w + 6, h: h + 6 };
            const clash = placed.some(r =>
                rect.x < r.x + r.w && rect.x + rect.w > r.x &&
                rect.y < r.y + r.h && rect.y + rect.h > r.y);
            el.style.display = clash ? 'none' : '';
            if (!clash) placed.push(rect);
        });
    }

    /**
     * Render pipelines as polylines on the map, with diameter-scaled weight,
     * per-valve markers (colored by whether the valve's Maxicom station watered
     * on the latest irrigation day).
     */
    function renderPipelines(pipelines) {
        pipelinesLayerGroup.clearLayers();
        valveMarkersForLabels = [];   // rebuilt as valve markers are created below

        pipelines.forEach(pipeline => {
            if (!pipeline.line_points || pipeline.line_points.length < 2) {
                return;
            }

            const latLngs = pipeline.line_points.map(point => {
                if (Array.isArray(point)) {
                    return [point[0], point[1]];
                } else if (point.lat !== undefined && point.lng !== undefined) {
                    return [point.lat, point.lng];
                }
                return null;
            }).filter(p => p !== null);

            if (latLngs.length < 2) return;

            // Weight: map main_diameter (mm) to pixel weight; fall back to line_weight.
            let baseWeight = pipeline.line_weight || 3;
            if (pipeline.main_diameter) {
                baseWeight = Math.max(3, Math.min(10, 2 + pipeline.main_diameter / 15));
            }

            const lineStyle = {
                color: pipeline.line_color,
                weight: baseWeight,
                opacity: 0.9,
            };

            const polyline = L.polyline(latLngs, lineStyle);
            const valves = pipeline.valves || [];
            const wateredCount = valves.filter(v => v.watered_today).length;

            polyline.pipelineData = {
                id: pipeline.id,
                code: pipeline.code,
                name: pipeline.name,
                pipeline_type: pipeline.pipeline_type,
                pipeline_type_display: pipeline.pipeline_type_display,
                zone_names: pipeline.zone_names || [],
            };

            const zoneList = pipeline.zone_names && pipeline.zone_names.length > 0
                ? pipeline.zone_names.join(', ')
                : '无关联区域';

            const diaLabel = pipeline.main_diameter
                ? `主管径 ${pipeline.main_diameter} mm`
                : '主管径未填';
            const valveLabel = valves.length
                ? `阀门 ${valves.length} 个（最近灌溉日浇水 ${wateredCount}）`
                : '无阀门节点';
            const srcLabel = pipeline.source_label
                ? `<div>水源: ${escapeHtml(pipeline.source_label)}</div>`
                : '';

            const popupContent = `
                <div class="popup-content">
                    <h3>${escapeHtml(pipeline.name)}</h3>
                    <div>编号: ${escapeHtml(pipeline.code)}</div>
                    <div>
                        <span style="background: ${pipeline.line_color}20; color: ${pipeline.line_color}; padding: 2px 8px; border-radius: 8px; font-size: 0.9em;">
                            ${escapeHtml(pipeline.pipeline_type_display)}
                        </span>
                    </div>
                    <div style="margin-top: 6px;">${diaLabel}</div>
                    ${srcLabel}
                    <div style="margin-top: 4px;">${valveLabel}</div>
                    <div style="margin-top: 4px;">关联区域: ${escapeHtml(zoneList)}</div>
                </div>
            `;
            polyline.bindPopup(popupContent);

            polyline.on('mouseover', function(e) {
                this.setStyle({ weight: baseWeight + 2, opacity: 1 });
            });
            polyline.on('mouseout', function(e) {
                this.setStyle({ weight: baseWeight, opacity: 0.9 });
            });

            pipelinesLayerGroup.addLayer(polyline);

            // ── Valve markers (DOM divIcon squares — always render above canvas,
            //    clearly visible against zone fills. Green=filled=watered, gray
            //    outline=not watered.) ──
            valves.forEach(v => {
                const pt = Array.isArray(v.point) && v.point[0]
                    ? (v.point[0].lat !== undefined ? [v.point[0].lat, v.point[0].lng] : [v.point[0][0], v.point[0][1]])
                    : null;
                if (!pt) return;
                const dia = v.diameter || 20;
                const size = Math.max(13, Math.min(18, 9 + dia / 10));
                const watered = !!v.watered_today;
                // Watered: solid green diamond. Not watered: hollow gray (white fill, gray border).
                const fill = watered ? '#2D6A4F' : '#ffffff';
                const border = watered ? '#ffffff' : '#5a5a5a';
                const ring = watered ? '#52B788' : '#8a8a8a';
                const vm = L.marker(pt, {
                    icon: L.divIcon({
                        className: 'pipe-valve-marker',
                        html: `<div style="width:${size}px;height:${size}px;background:${fill};border:2.5px solid ${ring};border-radius:50%;box-shadow:0 0 0 1.5px ${border},0 1px 4px rgba(0,0,0,0.5);"></div>`,
                        iconSize: [size, size], iconAnchor: [size / 2, size / 2]
                    })
                });
                // Zone label: "名称 代号" (e.g. "BOH 1-1-1"); fall back to whichever exists.
                const zLabel = [v.zone_name, v.zone_code].filter(x => x).join(' ') || '查看区域';
                const zLink = v.zone_id ? `<a href="/zone/${v.zone_id}/detail/" style="color:#1B4332;">${escapeHtml(zLabel)} ↗</a>` : '无';
                const stLink = v.station_id ? `SAT 阀 #${v.station_id}` : '未关联 station';
                // 最近灌溉: date(to minute) · minutes · depth(mm), each only if present.
                const rtParts = [];
                if (v.runtime_date) rtParts.push(escapeHtml(v.runtime_date));
                if (v.runtime_minutes != null && v.runtime_minutes > 0) rtParts.push(v.runtime_minutes + ' 分钟');
                if (v.depth_mm != null) rtParts.push(v.depth_mm + ' mm');
                const runtime = rtParts.length ? rtParts.join(' · ') : '无记录';
                vm.bindPopup(`
                    <div class="popup-content">
                        <h3>${escapeHtml(v.name || '阀门 #' + (v.order + 1))}</h3>
                        <div>${escapeHtml(v.valve_type_display || v.valve_type || '阀门')}${v.diameter ? ' · ' + v.diameter + 'mm' : ''}</div>
                        <div style="margin-top:6px;">控制区域: ${zLink}</div>
                        <div>${stLink}</div>
                        <div>最近灌溉: <b>${runtime}</b></div>
                        ${v.notes ? `<div style="white-space:pre-wrap;">备注: ${escapeHtml(v.notes)}</div>` : ''}
                    </div>
                `);
                const tipContent = escapeHtml((v.zone_name || '') + (v.zone_code ? ' ' + v.zone_code : '') || ('阀门 #' + (v.order + 1))) + (watered ? ' · 已浇水' : ' · 未浇水');
                vm.bindTooltip(tipContent, { sticky: true, className: 'ref-tooltip' });
                vm._tipContent = tipContent;   // for zoom-driven permanent toggle
                vm._watered = watered;          // 未浇水阀门最大层级不常显 label（仍可悬停查看）
                valveMarkersForLabels.push(vm);
                pipelinesLayerGroup.addLayer(vm);
            });
        });
    }

    function renderCadReference(batches) {
        cadReferenceLayerGroup.clearLayers();
        cadNotesLayerGroup.clearLayers();
        cadUnmatchedLayerGroup.clearLayers();
        batches.forEach(batch => {
            (batch.layers || []).forEach(layer => {
                (layer.paths || []).forEach(path => {
                    L.polyline(path.map(p => [p.lat, p.lng]), {
                        color: '#d6a544', weight: 1.5, opacity: 0.7
                    }).bindTooltip(escapeHtml(batch.name + ' · ' + layer.layer))
                        .addTo(cadReferenceLayerGroup);
                });
            });
            (batch.labels || []).forEach(note => {
                L.marker([note.lat, note.lng], {
                    icon: L.divIcon({ className: 'cad-note',
                        html: `<span style="font-size:10px;background:rgba(255,255,255,.85);white-space:nowrap;">${escapeHtml(note.text)}</span>` })
                }).bindPopup(`<div style="white-space:pre-wrap;">${escapeHtml(note.text)}</div><small>${escapeHtml(batch.name + ' · ' + note.layer)}</small>`)
                    .addTo(cadNotesLayerGroup);
            });
            (batch.unmatched_valves || []).forEach(valve => {
                L.circleMarker([valve.lat, valve.lng], {
                    radius: 6, color: '#a65d00', fillColor: '#ffc65a', fillOpacity: 1
                }).bindPopup(`<b>待挂接设备 · ${escapeHtml(valve.block)}</b><div>${escapeHtml(valve.reason)}</div><small>${escapeHtml(batch.name + ' · ' + valve.source_id)}</small>`)
                    .addTo(cadUnmatchedLayerGroup);
            });
        });
    }

    // Minimal HTML-escape for user-entered strings placed into popups/tooltips.
    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[ch]));
    }

    /**
     * Highlight a zone in the sidebar
     * @param {number} zoneId - Zone ID to highlight
     */
    function highlightSidebarItem(zoneId) {
        // Remove active class from all items
        document.querySelectorAll('.zone-item').forEach(item => {
            item.classList.remove('active');
        });

        // Add active class to selected item
        const selectedItem = document.querySelector(`[data-zone-id="${zoneId}"]`);
        if (selectedItem) {
            selectedItem.classList.add('active');
            selectedItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    /**
     * Handle sidebar zone item click
     */
    function setupSidebarInteraction() {
        document.querySelectorAll('.zone-item').forEach(item => {
            item.addEventListener('click', function() {
                const zoneId = parseInt(this.dataset.zoneId);

                // Find a matching layer for popup data
                let found = false;
                zonesLayerGroup.eachLayer(layer => {
                    if (layer.zoneData?.id === zoneId && !found) {
                        found = true;
                        highlightedLayer = layer;
                        highlightZonePolygons(zoneId);
                        flyToZone(layer.zoneData, layer);
                        showZonePopup(layer.zoneData);
                    }
                });

                // Update sidebar selection
                highlightSidebarItem(zoneId);
            });
        });
    }

    /**
     * Locate user and show marker on map
     * @param {Object} [opts] - Options: { auto: true } for auto-locate mode
     */
    let locating = false;
    function locationFeedback(message, retry) {
        const notice = document.getElementById('mapLocationNotice');
        if (!notice) return;
        notice.hidden = false;
        document.getElementById('mapLocationMessage').textContent = message;
        const retryButton = document.getElementById('mapLocationRetry');
        retryButton.hidden = !retry;
        retryButton.onclick = () => locateUser();
        document.getElementById('mapLocationClose').onclick = () => { notice.hidden = true; };
    }

    function locateUser(opts) {
        if (locating) return;
        const isAuto = opts?.auto === true;
        if (window.isSecureContext === false) {
            if (!isAuto) locationFeedback('定位需要安全连接，请使用正式网站的 HTTPS 地址打开应用。', false);
            return;
        }
        if (!navigator.geolocation) {
            if (!isAuto) locationFeedback('当前设备未提供定位功能，请检查手机的定位服务。', false);
            return;
        }
        locating = true;
        const button = document.querySelector('.locate-btn');
        if (button) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            button.title = '正在定位…';
        }
        if (!isAuto) locationFeedback('正在定位…请在手机提示中允许访问位置。', false);
        return runtime.requestLocation(navigator.geolocation).then(position => {
            const lat = position.coords.latitude, lng = position.coords.longitude;
            const accuracy = position.coords.accuracy;
            if (!runtime.point([lat, lng]) || !Number.isFinite(accuracy) || accuracy < 0) throw new Error('invalid location');
            if (userMarker) map.removeLayer(userMarker);
            if (userAccuracyCircle) map.removeLayer(userAccuracyCircle);
            userAccuracyCircle = L.circle([lat, lng], {radius:accuracy, color:'#1B4332', fillColor:'#2D6A4F', fillOpacity:0.15, weight:1}).addTo(map);
            userMarker = L.marker([lat, lng], {icon:L.divIcon({className:'user-location-marker',
                html:'<div class="user-location-dot"></div>', iconSize:[22,22], iconAnchor:[11,11]})}).addTo(map);
            const outside = map.options?.maxBounds && !map.options.maxBounds.contains([lat, lng]);
            if (!outside) map.flyTo([lat, lng], 16, {animate:true, duration:1});
            if (!isAuto) locationFeedback((outside ? '当前位置在项目范围外，地图保留项目视图。' : '已定位。') + '精度约 ' + Math.round(accuracy) + ' 米。', false);
        }).catch(error => {
            if (isAuto) return;
            let message = '暂时无法获取位置，请检查手机定位服务和网络后重试。';
            if (error.code === 1) message = '定位权限未开启。请在手机系统及此应用的网站权限中允许位置访问，然后重试。';
            else if (error.code === 3) message = '定位超时，请移至开阔处并检查手机定位服务后重试。';
            locationFeedback(message, true);
        }).finally(() => {
            locating = false;
            if (button) {
                button.disabled = false;
                button.removeAttribute('aria-busy');
                button.title = '定位我';
            }
        });
    }

    /**
     * Add locate me button to map
     */
    function addLocateButton() {
        const locateControl = L.control({ position: 'topright' });

        locateControl.onAdd = function(map) {
            const button = L.DomUtil.create('button', 'locate-btn map-tool-btn');
            button.innerHTML = window.uiIcon('pin');
            button.title = '定位我';
            button.type = 'button';

            L.DomEvent.disableClickPropagation(button);
            L.DomEvent.on(button, 'click', locateUser);

            return button;
        };

        locateControl.addTo(map);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initMap();
            setupSidebarInteraction();
            addLocateButton();
        });
    } else {
        initMap();
        setupSidebarInteraction();
        addLocateButton();
    }

    // Auto-locate is triggered from dashboard.js
    window.addEventListener?.('pageshow', event => {
        if (event.persisted && Date.now() - lastZoneRefresh > 60000) loadZones();
    });

    /**
     * Apply combined map filters (priority + plant)
     */
    window.applyMapFilters = function() {
        const priorities = window.activePriorities || new Set();
        const priorityTouched = window.priorityFilterTouched || false;
        const plants = window.activePlants || new Set();
        const isPlantTouched = window.plantFilterTouched || false;
        const lmFilterTouched = window.landmarkFilterTouched || false;
        const activeLms = window.activeLandmarks || new Set();
        const zoneLmMap = window._zoneLandmarkMap || {};
        const activePatches = window.activePatches || new Set();
        const patchFilterTouched = window.patchFilterTouched || false;

        function matchLandmark(zoneId) {
            if (!lmFilterTouched) return true;
            const lmNames = (zoneLmMap[zoneId] || []).map(l => l.name);
            return lmNames.some(n => activeLms.has(n));
        }

        function matchPatch(zoneData) {
            if (!patchFilterTouched) return true;
            return runtime.matchesPatch(zoneData, patchFilterTouched, activePatches);
        }

        zonesLayerGroup.eachLayer(layer => {
            if (layer.zoneData) {
                const matchPriority = !priorityTouched || priorities.has(layer.zoneData.priority);
                const matchPlant = !isPlantTouched || !layer.zoneData.plantNames || layer.zoneData.plantNames.some(p => plants.has(p));
                const matchLm = matchLandmark(layer.zoneData.id);
                const matchPa = matchPatch(layer.zoneData);
                if (matchPriority && matchPlant && matchLm && matchPa) {
                    const base = layer.originalStyle || defaultStyle;
                    layer.setStyle({ color: base.color, weight: base.weight, opacity: base.opacity, fillColor: base.fillColor, fillOpacity: base.fillOpacity, dashArray: base.dashArray });
                } else {
                    const base = layer.originalStyle || defaultStyle;
                    layer.setStyle({ color: base.color, weight: base.weight, opacity: 0.1, fillColor: base.fillColor, fillOpacity: 0.03, dashArray: base.dashArray });
                }
            }
        });
        zoneLabels.forEach(label => {
            const zoneId = label._zone?.id;
            const matchPriority = !priorityTouched || priorities.has(label._zone?.priority);
            const matchPlant = !isPlantTouched || !label._zone?.plant_names || label._zone.plant_names.some(p => plants.has(p));
            const matchLm = matchLandmark(zoneId);
            const matchPa = matchPatch(label._zone || {});
            const match = matchPriority && matchPlant && matchLm && matchPa;
            label._filterMatch = match;
            const el = label.getElement();
            if (el) el.style.opacity = match ? '1' : '0.1';
            // Filter leader lines for this label's zone
            if (label._leaderLines) {
                label._leaderLines.forEach(line => {
                    line.setStyle({ opacity:match ? (_rCfg.opacity ?? 0.55) : 0.05 });
                });
            }
            (label._ringLabels || []).forEach(sub => {
                sub._filterMatch = match;
                const el = sub.getElement();
                if (el) el.style.opacity = match ? '1' : '0.1';
            });
        });
    };

    window.setLayerVisibility = function(layer, visible) {
        if (layer === 'zones') {
            if (visible) {
                if (!map.hasLayer(zonesLayerGroup)) map.addLayer(zonesLayerGroup);
            } else {
                if (map.hasLayer(zonesLayerGroup)) map.removeLayer(zonesLayerGroup);
            }
        } else if (layer === 'labels') {
            labelsVisible = visible;
            if (visible) {
                if (!map.hasLayer(labelsLayerGroup)) map.addLayer(labelsLayerGroup);
                // Ring sublabels (per-boundary labels shown when 连线 is OFF) are part of
                // the labels layer conceptually; restore them too if they were present.
                if (ringLabelsLayerGroup && !map.hasLayer(ringLabelsLayerGroup)) map.addLayer(ringLabelsLayerGroup);
                updateLabelSizes();
            } else {
                if (map.hasLayer(labelsLayerGroup)) map.removeLayer(labelsLayerGroup);
                // Hide ring sublabels together with the main labels.
                if (ringLabelsLayerGroup && map.hasLayer(ringLabelsLayerGroup)) map.removeLayer(ringLabelsLayerGroup);
            }
            updateLabelSizes();
        } else if (layer === 'leader_lines') {
            // 连线 toggle: ON  → leader lines visible, ring sublabels hidden
            //              OFF → leader lines hidden, each boundary gets its own small label
            window._leaderLinesVisible = visible;
            const z = map.getZoom();
            syncMultiBoundaryDisplay(labelsVisible && z >= LABEL_MIN_ZOOM, z);
        } else if (layer === 'pipelines') {
            if (visible) {
                if (!map.hasLayer(pipelinesLayerGroup)) map.addLayer(pipelinesLayerGroup);
            } else {
                if (map.hasLayer(pipelinesLayerGroup)) map.removeLayer(pipelinesLayerGroup);
            }
        } else if (layer === 'cad_reference' || layer === 'cad_notes' || layer === 'cad_unmatched') {
            const group = layer === 'cad_reference' ? cadReferenceLayerGroup
                : layer === 'cad_notes' ? cadNotesLayerGroup : cadUnmatchedLayerGroup;
            if (visible) map.addLayer(group); else map.removeLayer(group);
        } else if (layer === 'landmarks') {
            if (visible) {
                if (!map.hasLayer(landmarksLayerGroup)) {
                    loadAndRenderLandmarks();
                    map.addLayer(landmarksLayerGroup);
                }
            } else {
                if (map.hasLayer(landmarksLayerGroup)) map.removeLayer(landmarksLayerGroup);
            }
        }
    };

    function loadAndRenderLandmarks() {
        const dataEl = document.getElementById('landmarks-data');
        if (!dataEl) return;
        landmarksLayerGroup.clearLayers();
        landmarkLabels = [];
        try {
            const landmarks = JSON.parse(dataEl.textContent);
            landmarks.forEach(lm => {
                if (!lm.boundary_points || lm.boundary_points.length === 0) return;
                const first = lm.boundary_points[0];
                let rings;
                if (Array.isArray(first) && first.length > 0 && (Array.isArray(first[0]) || first[0] && first[0].lat !== undefined)) {
                    rings = lm.boundary_points;
                } else {
                    rings = [lm.boundary_points];
                }
                rings.forEach(ring => {
                    const latLngs = ring.map(p => {
                        if (Array.isArray(p)) return [p[0], p[1]];
                        if (p.lat !== undefined) return [p.lat, p.lng];
                        return null;
                    }).filter(Boolean);
                    if (latLngs.length >= 3) {
                        L.polygon(latLngs, {
                            color: lm.boundary_color,
                            weight: 2,
                            opacity: 0.6,
                            fillColor: lm.boundary_color,
                            fillOpacity: 0.08,
                            dashArray: '8 4',
                        }).addTo(landmarksLayerGroup);
                    }
                });
                if (lm.center && lm.center.lat != null) {
                    const marker = L.marker([lm.center.lat, lm.center.lng], {
                        interactive: false,
                        icon: L.divIcon({
                            className: 'landmark-label',
                            html: '<div style="transform:translate(-50%,-50%);white-space:nowrap;"><span style="font-weight:600;color:' + lm.boundary_color + ';text-shadow:0 0 4px white,0 0 4px white;">' + escapeHtml(lm.name) + '</span></div>',
                            iconSize: null,
                            iconAnchor: [0, 0],
                        })
                    }).addTo(landmarksLayerGroup);
                    landmarkLabels.push(marker);
                }
            });
            // Apply initial zoom-based label sizing
            if (landmarkLabels.length > 0) updateLabelSizes();
        } catch (e) {}
    }
})();
