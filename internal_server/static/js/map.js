/**
 * Leaflet Map Initialization and Zone Rendering
 * Handles interactive map with irrigation zones
 */

(function() {
    'use strict';

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

    // Fallback tile layer for high zoom levels (GeoQ)
    const fallbackLayer = L.tileLayer('https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}', {
        attribution: '',
        minZoom: 19,
        maxZoom: 22,
        opacity: 0.7
    });

    // Hybrid layer group - satellite for normal zoom, fallback for high zoom
    const hybridLayer = L.layerGroup([satelliteLayer, fallbackLayer]);

    // Zone layers group
    let zonesLayerGroup;

    // Pipeline layers group
    let pipelinesLayerGroup;

    // Zone label layers group (separate from boundaries for independent toggle)
    let labelsLayerGroup;

    // Leader lines layer group (separate from labels for independent toggle)
    let leaderLinesLayerGroup;

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

    // Ring anchor — centroid if inside polygon, nearest boundary point to label if not
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
        return zone.smooth_override != null ? zone.smooth_override : _smoothIter;
    }

    // Default zone style (fallback when no status)
    const defaultStyle = {
        color: '#2D6A4F',
        weight: _bCfg.weight || 2,
        opacity: _bCfg.opacity || 0.8,
        fillColor: '#2D6A4F',
        fillOpacity: _bCfg.fillOpacity != null ? _bCfg.fillOpacity : 0.12,
        dashArray: _dash(_bCfg.dashStyle)
    };

    // Highlighted/selected zone style
    const highlightStyle = {
        color: '#D4A574',
        weight: 3,
        opacity: 1,
        fillColor: '#D4A574',
        fillOpacity: 0.25
    };

    // Status-based polygon styling (from design system)
    const _bW = _bCfg.weight || 2;
    const _bO = _bCfg.opacity || 0.7;
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
        const centerLat = 31.145794 + 0.010; // offset ~1.1km north
        const centerLng = 121.656804 + 0.012; // offset ~1.1km east
        const latOffset = 0.027; // ~3km in latitude
        const lngOffset = 0.032; // ~3km in longitude at lat 31°

        const southWest = L.latLng(centerLat - latOffset, centerLng - lngOffset);
        const northEast = L.latLng(centerLat + latOffset, centerLng + lngOffset);
        const bounds = L.latLngBounds(southWest, northEast);

        // Create map centered on location with satellite layer
        map = L.map('map', {
            center: [centerLat, centerLng],
            zoom: 15,
            maxZoom: 22,
            minZoom: 15,
            maxBounds: bounds,
            maxBoundsViscosity: 1.0,
            layers: [hybridLayer],
            zoomControl: true
        });

        // Expose map instance for external use (sidebar resize)
        window._map = map;

        // Initialize leader lines layer group (rendered below zones so boundaries occlude lines)
        leaderLinesLayerGroup = L.layerGroup().addTo(map);

        // Initialize zones layer group (rendered on top of leader lines)
        zonesLayerGroup = L.layerGroup().addTo(map);

        // Initialize pipelines layer group
        pipelinesLayerGroup = L.layerGroup().addTo(map);

        // Initialize labels layer group (separate for independent layer control)
        labelsLayerGroup = L.layerGroup().addTo(map);

        // Initialize landmarks layer group (not added by default - user toggles via layer control)
        landmarksLayerGroup = L.layerGroup();

        // Load and render zones
        loadZones();

        // Load and render pipelines
        loadPipelines();

        // Update zone label sizes on zoom
        map.on('zoomend', updateLabelSizes);

        // Close popup when clicking on empty map space
        map.on('click', function(e) {
            // Only close if click was directly on the map, not on a polygon
            if (e.originalEvent.target.closest('.leaflet-overlay-pane')) return;
            hideZonePopup();
        });
    }

    /**
     * Load zones from the embedded JSON data
     */
    function loadZones() {
        const zonesDataElement = document.getElementById('zones-data');
        if (!zonesDataElement) {
            console.error('Zones data element not found');
            return;
        }

        try {
            const zones = JSON.parse(zonesDataElement.textContent);
            console.log('Loaded zones:', zones.length, 'zones');
            renderZones(zones);
            fitMapToBounds(zones);
        } catch (error) {
            console.error('Error parsing zones data:', error);
        }
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
                html: `<div style="transform:translate(-50%,-50%);white-space:nowrap;"><span style="${labelStyle}">${getCodeForZoom(code, map.getZoom())}</span></div>`,
                iconSize: null,
                iconAnchor: [0, 0]
            })
        });
        label._zone = zone;
        label._originalCenter = center;
        labelsLayerGroup.addLayer(label);
        zoneLabels.push(label);

        // Add leader lines from label to each polygon centroid (for multi-boundary zones)
        if (isMultiPolygonFormat(zone.boundary_points) && zone.boundary_points.length > 1) {
            label._leaderLines = [];
            zone.boundary_points.forEach(ring => {
                const ringPts = pointsToLatLngs(ring);
                if (ringPts.length < 3) return;
                const smoothPts = _smoothLL(ringPts, _zoneSmooth(zone));
                const ringCenter = _ringAnchor(smoothPts, center[0], center[1]);
                const line = L.polyline([center, ringCenter], {
                    color: zone.boundary_color || '#2D6A4F',
                    weight: _rCfg.weight || 2.5,
                    opacity: _rCfg.opacity != null ? _rCfg.opacity : 0.55,
                    dashArray: _dash(_rCfg.dashStyle),
                    interactive: false
                });
                leaderLinesLayerGroup.addLayer(line);
                label._leaderLines.push(line);
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
     * Update all zone label sizes on zoom change
     */
    function updateLabelSizes() {
        const zoom = map.getZoom();
        const showLabels = zoom >= LABEL_MIN_ZOOM;
        const baseSize = getLabelFontSize(zoom);

        // Group labels by truncated code when zoomed out
        if (showLabels && zoom < 18) {
            // Build groups keyed by truncated code
            const groups = {};
            zoneLabels.forEach(label => {
                const zone = label._zone;
                if (!zone) return;
                const key = getCodeForZoom(zone.code, zoom);
                if (!groups[key]) groups[key] = [];
                groups[key].push(label);
            });
            // For each group, show only one label at the group centroid
            Object.entries(groups).forEach(([key, labels]) => {
                // Compute group centroid
                let latSum = 0, lngSum = 0, count = 0;
                labels.forEach(l => {
                    const c = l._originalCenter;
                    if (c) { latSum += c[0]; lngSum += c[1]; count++; }
                });
                const groupCenter = count > 0 ? [latSum / count, lngSum / count] : labels[0]._originalCenter;

                labels.forEach((label, i) => {
                    const el = label.getElement();
                    if (i === 0) {
                        // Show representative label at group centroid
                        if (el) el.style.display = '';
                        label.setLatLng(groupCenter);
                        const zone = label._zone;
                        const scale = zone ? (zone.label_scale || 1.0) : 1.0;
                        const size = baseSize * scale;
                        const span = el ? el.querySelector('span') : null;
                        if (span) {
                            span.style.fontSize = size + 'px';
                            span.textContent = key;
                        }
                    } else {
                        if (el) el.style.display = 'none';
                    }
                    // Hide leader lines for grouped labels
                    if (label._leaderLines) {
                        label._leaderLines.forEach(line => {
                            const le = line.getElement();
                            if (le) le.style.display = 'none';
                        });
                    }
                });
            });
        } else {
            // Full zoom: show all individual labels at original positions
            zoneLabels.forEach(label => {
                const el = label.getElement();
                if (el) {
                    el.style.display = showLabels ? '' : 'none';
                    if (showLabels) {
                        const zone = label._zone;
                        const scale = zone ? (zone.label_scale || 1.0) : 1.0;
                        const size = baseSize * scale;
                        const span = el.querySelector('span');
                        if (span) {
                            span.style.fontSize = size + 'px';
                            span.textContent = zone ? zone.code : '';
                        }
                    }
                }
                // Restore original position
                if (label._originalCenter) label.setLatLng(label._originalCenter);
                // Show/hide leader lines with labels
                if (label._leaderLines) {
                    label._leaderLines.forEach(line => {
                        const le = line.getElement();
                        if (le) le.style.display = showLabels ? '' : 'none';
                    });
                }
            });
        }
        // Landmark labels: same zoom-based scaling, no per-item scale
        const lmSize = baseSize * 0.85;
        landmarkLabels.forEach(label => {
            const el = label.getElement();
            if (el) {
                el.style.display = showLabels ? '' : 'none';
                if (showLabels) {
                    const span = el.querySelector('span');
                    if (span) span.style.fontSize = lmSize + 'px';
                }
            }
        });
    }

    /**
     * Render zones on the map (supports multi-polygon format)
     */
    function renderZones(zones) {
        zonesLayerGroup.clearLayers();
        labelsLayerGroup.clearLayers();
        if (leaderLinesLayerGroup) leaderLinesLayerGroup.clearLayers();
        zoneLabels = [];

        zones.forEach(zone => {
            if (!zone.boundary_points || zone.boundary_points.length === 0) {
                return;
            }

            try {
                let zoneStyle;
                if (zone.boundary_color) {
                    zoneStyle = {
                        color: zone.boundary_color,
                        weight: _bW,
                        opacity: _bO,
                        fillColor: zone.boundary_color,
                        fillOpacity: _bFO,
                        dashArray: _bD
                    };
                } else {
                    zoneStyle = getStyleForStatus(zone.status);
                }

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
                    hasRemarks: zone.has_remarks || false,
                    hasConfirmedRemarks: zone.has_confirmed_remarks || false,
                };

                if (isMultiPolygonFormat(zone.boundary_points)) {
                    // Multi-polygon: each element is a separate polygon ring
                    let allLatLngs = [];
                    zone.boundary_points.forEach((ring, ringIdx) => {
                        const latLngs = pointsToLatLngs(ring);
                        if (latLngs.length < 3) return;

                        const polygon = L.polygon(_smoothLL(latLngs, _zoneSmooth(zone)), zoneStyle);
                        polygon.zoneData = zoneData;
                        polygon.originalStyle = zoneStyle;
                        polygon.on('mouseover', handleMouseOver);
                        polygon.on('mouseout', handleMouseOut);
                        polygon.on('click', handleClick);
                        polygon.bindTooltip(`${zone.code} ${zone.name || ''}`, {sticky: true});
                        zonesLayerGroup.addLayer(polygon);
                        allLatLngs = allLatLngs.concat(latLngs);
                    });
                    // Only one label per zone, centered on all rings combined
                    if (allLatLngs.length > 0) {
                        zone._allLatLngs = allLatLngs;
                        addZoneLabel(zone);
                    }
                } else {
                    // Legacy single-polygon format
                    const latLngs = pointsToLatLngs(zone.boundary_points);
                    if (latLngs.length < 3) return;

                    const polygon = L.polygon(_smoothLL(latLngs, _zoneSmooth(zone)), zoneStyle);
                    polygon.zoneData = zoneData;
                    polygon.originalStyle = zoneStyle;
                    polygon.on('mouseover', handleMouseOver);
                    polygon.on('mouseout', handleMouseOut);
                    polygon.on('click', handleClick);
                    polygon.bindTooltip(`${zone.code} ${zone.name || ''}`, {sticky: true});
                    zonesLayerGroup.addLayer(polygon);
                    zone._allLatLngs = latLngs;
                    addZoneLabel(zone);
                }

                // Add pending request markers if any
                if (zone.pending_requests && zone.pending_requests.length > 0 && zone.center) {
                    addPendingRequestMarker(zone);
                }

                // Add remark indicator markers if any
                if ((zone.has_remarks || zone.has_confirmed_remarks) && zone.center) {
                    addRemarkMarker(zone);
                }
            } catch (err) {
                console.error('Error creating polygon for zone:', zone.name, err);
            }
        });

        // Apply initial label visibility based on current zoom
        updateLabelSizes();
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

        // Build tooltip content (only water requests now)
        let tooltipLines = zone.pending_requests.map(req => {
            return `💧 ${req.type_display}`;
        }).join('<br>');

        marker.bindTooltip(`
            <div style="font-size: 12px;">
                <strong>待审批浇水需求 (${pendingCount})</strong><br>
                ${tooltipLines}<br>
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
    ];

    const CARD_SETTINGS_KEY = 'zoneProfileCardFields';

    function getCardFieldSettings() {
        try {
            const saved = localStorage.getItem(CARD_SETTINGS_KEY);
            if (saved) return JSON.parse(saved);
        } catch (e) {}
        // Default: all fields hidden
        const defaults = {};
        ZONE_CARD_FIELDS.forEach(f => { defaults[f.key] = false; });
        return defaults;
    }

    function saveCardFieldSetting(key, visible) {
        const settings = getCardFieldSettings();
        settings[key] = visible;
        localStorage.setItem(CARD_SETTINGS_KEY, JSON.stringify(settings));
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
                    const d = e.date || '';
                    const displayDate = d && d !== '日期格式错误'
                        ? d.replace(/-0*/g, '/').replace(/^20/, '')
                        : '';
                    return `<div style="display:flex;gap:4px;font-size:0.82em;padding:1px 0;"><span style="color:var(--color-primary);flex-shrink:0;min-width:56px;">${displayDate}</span><span style="color:#555;word-break:break-all;">${e.content || ''}</span></div>`;
                }).join('');
                const collapsedHtml = entries.slice(0, maxShow).map(e => {
                    const d = e.date || '';
                    const displayDate = d && d !== '日期格式错误'
                        ? d.replace(/-0*/g, '/').replace(/^20/, '')
                        : '';
                    return `<div style="display:flex;gap:4px;font-size:0.82em;padding:1px 0;"><span style="color:var(--color-primary);flex-shrink:0;min-width:56px;">${displayDate}</span><span style="color:#555;word-break:break-all;">${e.content || ''}</span></div>`;
                }).join('');
                const remaining = entries.length - maxShow;
                const moreBtn = remaining > 0
                    ? `<div class="notes-expand-btn" style="font-size:0.78em;color:var(--color-primary);padding-top:1px;cursor:pointer;text-decoration:underline;" onclick="window._toggleNotesExpand('${listId}', this)">还有 ${remaining} 条记录</div>`
                    : '';
                fieldsHtml += `<div class="popup-field" style="flex-direction:column;align-items:stretch;gap:2px;"><span class="popup-field-label">${f.label}</span><div id="${listId}_collapsed" style="margin-left:0;">${collapsedHtml}${moreBtn}</div><div id="${listId}_expanded" style="margin-left:0;display:none;">${allHtml}<div class="notes-expand-btn" style="font-size:0.78em;color:var(--color-primary);padding-top:1px;cursor:pointer;text-decoration:underline;" onclick="window._toggleNotesExpand('${listId}', this)">收起</div></div></div>`;
            } else {
                fieldsHtml += `<div class="popup-field"><span class="popup-field-label">${f.label}</span><span class="popup-field-value">${val}</span></div>`;
            }
        });

        // Fault warning
        let faultHtml = '';
        if (zone.recentFaultCount > 0) {
            faultHtml = `<div class="popup-alert">⚠️ 近30天 ${zone.recentFaultCount} 次故障</div>`;
        }

        // Pending requests
        let pendingHtml = '';
        const pendingCount = (zone.pendingRequests || []).length;
        if (pendingCount > 0) {
            pendingHtml = `<div class="popup-alert popup-alert-warn">💧 ${pendingCount} 个待审批浇水需求</div>`;
        }

        const hasExtra = fieldsHtml || faultHtml || pendingHtml;

        return `
            <div class="popup-card">
                <div class="popup-header">
                    <div>
                        <div class="popup-title">${zone.code} - ${zone.name}</div>
                        ${statusInfo ? `<span class="popup-status-badge" style="background: ${statusInfo.color}18; color: ${statusInfo.color};">${statusInfo.label}</span>` : ''}
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;">
                        <button class="popup-settings-btn" onclick="togglePopupSettings()" title="自定义显示字段">⚙</button>
                        <button class="popup-close-btn" onclick="window.hideZonePopup()" title="关闭">✕</button>
                    </div>
                </div>
                ${hasExtra ? '<div class="popup-fields">' + fieldsHtml + faultHtml + pendingHtml + '</div>' : ''}
                <div class="popup-footer">
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
                    <button class="popup-settings-btn" onclick="togglePopupSettings()" title="返回">✕</button>
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

    function showZonePopup(zoneData) {
        const panel = document.getElementById('zonePopupPanel');
        if (!panel) return;
        currentPopupZoneData = zoneData;
        popupSettingsOpen = false;
        panel.innerHTML = buildPopupHtml(zoneData);
        panel.style.display = '';
    }

    function hideZonePopup() {
        const panel = document.getElementById('zonePopupPanel');
        if (!panel) return;
        panel.style.display = 'none';
        currentPopupZoneData = null;
        popupSettingsOpen = false;
        unhighlightZonePolygons();
        document.querySelectorAll('.zone-item.active').forEach(el => el.classList.remove('active'));
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
    window.handleFieldToggle = handleFieldToggle;

    window.handleSmoothCustomToggle = function(checked) {
        const slider = document.getElementById('smoothOverrideSlider');
        if (slider) slider.disabled = !checked;
        if (!checked && slider) slider.value = _smoothIter;
    };

    function _getCSRF() {
        const fromInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (fromInput) return fromInput.value;
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

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
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': _getCSRF()},
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
        // Find and remove existing polygons for this zone, then re-add with new smooth
        zonesLayerGroup.eachLayer(layer => {
            if (layer.zoneData && layer.zoneData.id === zoneData.id) {
                zonesLayerGroup.removeLayer(layer);
            }
        });
        // Re-add from zonesData
        const zone = zonesData.find(z => z.id === zoneData.id);
        if (!zone || !zone.boundary_points) return;
        zone.smooth_override = zoneData.smooth_override;

        let zoneStyle;
        const color = zone.boundary_color || '#2D6A4F';
        if (zone.status === 'in_progress') {
            zoneStyle = {...statusStyles.in_progress, color};
        } else if (zone.status === 'completed') {
            zoneStyle = {...statusStyles.completed, color};
        } else {
            zoneStyle = {...defaultStyle, color};
        }

        if (isMultiPolygonFormat(zone.boundary_points)) {
            zone.boundary_points.forEach(ring => {
                const ll = pointsToLatLngs(ring);
                if (ll.length < 3) return;
                const poly = L.polygon(_smoothLL(ll, _zoneSmooth(zone)), zoneStyle);
                poly.zoneData = {id: zone.id, code: zone.code, name: zone.name};
                poly.originalStyle = zoneStyle;
                poly.on('mouseover', handleMouseOver);
                poly.on('mouseout', handleMouseOut);
                poly.on('click', handleClick);
                poly.bindTooltip(`${zone.code} ${zone.name || ''}`, {sticky: true});
                zonesLayerGroup.addLayer(poly);
            });
        } else {
            const ll = pointsToLatLngs(zone.boundary_points);
            if (ll.length < 3) return;
            const poly = L.polygon(_smoothLL(ll, _zoneSmooth(zone)), zoneStyle);
            poly.zoneData = {id: zone.id, code: zone.code, name: zone.name};
            poly.originalStyle = zoneStyle;
            poly.on('mouseover', handleMouseOver);
            poly.on('mouseout', handleMouseOut);
            poly.on('click', handleClick);
            poly.bindTooltip(`${zone.code} ${zone.name || ''}`, {sticky: true});
            zonesLayerGroup.addLayer(poly);
        }
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
    function handleMouseOver(e) {
        const layer = e.target;
        const zoneId = layer.zoneData?.id;
        if (zoneId) highlightZonePolygons(zoneId);
    }

    /**
     * Handle mouse out event on zone
     * @param {Event} e - Leaflet event
     */
    function handleMouseOut(e) {
        e.target.closeTooltip();
        unhighlightZonePolygons();
    }

    /**
     * Handle click event on zone polygon
     * @param {Event} e - Leaflet event
     */
    function handleClick(e) {
        const layer = e.target;
        const zoneId = layer.zoneData?.id;

        if (zoneId) {
            highlightZonePolygons(zoneId);

            // Highlight the corresponding sidebar item
            highlightSidebarItem(zoneId);

            // Show fixed popup panel
            showZonePopup(layer.zoneData);
        }
    }

    /**
     * Fit map bounds to show all zones
     * @param {Array} zones - Array of zone objects
     */
    function fitMapToBounds(zones) {
        // Keep map at predefined center - don't auto-adjust
        // The map is already centered at the specified location
    }

    /**
     * Load pipelines from embedded JSON data
     */
    function loadPipelines() {
        const pipelinesDataElement = document.getElementById('pipelines-data');
        if (!pipelinesDataElement) {
            console.log('No pipelines data element found');
            return;
        }

        try {
            const pipelines = JSON.parse(pipelinesDataElement.textContent);
            console.log('Loaded pipelines:', pipelines.length);
            renderPipelines(pipelines);
        } catch (error) {
            console.error('Error parsing pipelines data:', error);
        }
    }

    /**
     * Render pipelines as polylines on the map
     */
    function renderPipelines(pipelines) {
        pipelinesLayerGroup.clearLayers();

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

            const lineStyle = {
                color: pipeline.line_color,
                weight: pipeline.line_weight || 3,
                opacity: 0.9,
            };

            const polyline = L.polyline(latLngs, lineStyle);
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

            const popupContent = `
                <div class="popup-content">
                    <h3>${pipeline.name}</h3>
                    <div>编号: ${pipeline.code}</div>
                    <div>
                        <span style="background: ${pipeline.line_color}20; color: ${pipeline.line_color}; padding: 2px 8px; border-radius: 8px; font-size: 0.9em;">
                            ${pipeline.pipeline_type_display}
                        </span>
                    </div>
                    <div style="margin-top: 6px;">关联区域: ${zoneList}</div>
                </div>
            `;
            polyline.bindPopup(popupContent);

            polyline.on('mouseover', function(e) {
                this.setStyle({ weight: (pipeline.line_weight || 3) + 2, opacity: 1 });
            });
            polyline.on('mouseout', function(e) {
                this.setStyle({ weight: pipeline.line_weight || 3, opacity: 0.9 });
            });

            pipelinesLayerGroup.addLayer(polyline);
        });
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
                console.log('Sidebar click: zoneId =', zoneId);

                // Check how many layers we have
                const layers = zonesLayerGroup.getLayers();
                console.log('Total layers in group:', layers.length);
                console.log('Layer zoneData IDs:', layers.map(l => l.zoneData?.id));

                let found = false;
                // Find and highlight the corresponding map layer
                zonesLayerGroup.eachLayer(layer => {
                    console.log('Checking layer.zoneData.id:', layer.zoneData?.id, 'type:', typeof layer.zoneData?.id, 'vs zoneId:', zoneId, 'type:', typeof zoneId);
                    if (layer.zoneData?.id === zoneId) {
                        found = true;
                        console.log('Found matching layer for zone:', zoneId);

                        // Reset previously highlighted layer
                        if (highlightedLayer && highlightedLayer !== layer) {
                            highlightedLayer.setStyle(highlightedLayer.originalStyle || defaultStyle);
                        }
                        highlightedLayer = layer;
                        layer.setStyle(highlightStyle);
                        layer.bringToFront();

                        // Show fixed popup panel
                        showZonePopup(layer.zoneData);

                        // Fly to the zone with smooth animation (disabled)
                        // const bounds = layer.getBounds();
                        // if (bounds) {
                        //     map.flyToBounds(bounds, {
                        //         padding: [50, 50],
                        //         duration: 0.8,
                        //         easeLinearity: 0.25
                        //     });
                        // }
                    }
                });

                if (!found) {
                    console.warn('No matching layer found for zoneId:', zoneId);
                }

                // Update sidebar selection
                highlightSidebarItem(zoneId);
            });
        });
    }

    /**
     * Locate user and show marker on map
     */
    function locateUser() {
        if (!('geolocation' in navigator)) {
            alert('您的浏览器不支持定位功能');
            return;
        }

        // Show loading state
        const locateBtn = document.querySelector('.locate-btn');
        if (locateBtn) {
            locateBtn.disabled = true;
            locateBtn.textContent = '...';
        }

        navigator.geolocation.getCurrentPosition(
            function(position) {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                const accuracy = position.coords.accuracy;

                // Remove existing marker
                if (userMarker) {
                    map.removeLayer(userMarker);
                }
                if (userAccuracyCircle) {
                    map.removeLayer(userAccuracyCircle);
                }

                // Add accuracy circle
                userAccuracyCircle = L.circle([lat, lng], {
                    radius: accuracy,
                    color: '#1B4332',
                    fillColor: '#2D6A4F',
                    fillOpacity: 0.15,
                    weight: 1
                }).addTo(map);

                // Add user marker
                userMarker = L.marker([lat, lng], {
                    icon: L.divIcon({
                        className: 'user-location-marker',
                        html: '<div style="background: #1B4332; width: 16px; height: 16px; border: 3px solid white; border-radius: 50%; box-shadow: 0 0 0 2px #1B4332, 0 2px 8px rgba(27, 67, 50, 0.3);"></div>',
                        iconSize: [22, 22],
                        iconAnchor: [11, 11]
                    })
                }).addTo(map);

                // Pan map to user location
                map.flyTo([lat, lng], 16, {
                    animate: true,
                    duration: 1.5
                });

                // Reset button
                if (locateBtn) {
                    locateBtn.disabled = false;
                    locateBtn.textContent = '⌖';
                }

                // Open popup with location info
                L.popup()
                    .setLatLng([lat, lng])
                    .setContent(`<div><strong>您的位置</strong><br>精度: ~${Math.round(accuracy)}米</div>`)
                    .openOn(map);
            },
            function(error) {
                // Reset button
                if (locateBtn) {
                    locateBtn.disabled = false;
                    locateBtn.textContent = '⌖';
                }

                // Show error
                let message = '无法获取您的位置';
                if (error.code === error.PERMISSION_DENIED) {
                    message = '定位权限被拒绝，请在浏览器设置中允许定位。';
                } else if (error.code === error.TIMEOUT) {
                    message = '定位请求超时，请重试。';
                }
                alert(message);
                console.error('Location error:', error);
            },
            {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 0
            }
        );
    }

    /**
     * Add locate me button to map
     */
    function addLocateButton() {
        const locateControl = L.control({ position: 'topright' });

        locateControl.onAdd = function(map) {
            const button = L.DomUtil.create('button', 'locate-btn');
            button.innerHTML = '⌖';
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

    /**
     * Auto locate user on page load
     */
    function autoLocate() {
        if (!('geolocation' in navigator)) {
            console.log('Geolocation not supported');
            return;
        }

        console.log('Auto-locating...');
        navigator.geolocation.getCurrentPosition(
            function(position) {
                console.log('Auto-locate success:', position.coords.latitude, position.coords.longitude);
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                const accuracy = position.coords.accuracy;

                // Remove existing marker if any
                if (userMarker) {
                    map.removeLayer(userMarker);
                }
                if (userAccuracyCircle) {
                    map.removeLayer(userAccuracyCircle);
                }

                // Add accuracy circle
                userAccuracyCircle = L.circle([lat, lng], {
                    radius: accuracy,
                    color: '#1B4332',
                    fillColor: '#2D6A4F',
                    fillOpacity: 0.15,
                    weight: 1
                }).addTo(map);

                // Add user marker
                userMarker = L.marker([lat, lng], {
                    icon: L.divIcon({
                        className: 'user-location-marker',
                        html: '<div style="background: #D4A574; width: 16px; height: 16px; border: 3px solid white; border-radius: 50%; box-shadow: 0 0 0 2px #D4A574, 0 2px 8px rgba(212, 165, 74, 0.4);"></div>',
                        iconSize: [22, 22],
                        iconAnchor: [11, 11]
                    })
                }).addTo(map);

                // Fly to user location
                map.flyTo([lat, lng], 16, {
                    animate: true,
                    duration: 1.0
                });
            },
            function(error) {
                console.log('Auto-locate failed:', error.code, error.message);
            },
            {
                enableHighAccuracy: true,
                timeout: 15000,
                maximumAge: 60000 // Allow cached position for faster response
            }
        );
    }

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
            const pid = zoneData.patchId;
            if (pid == null) return true;
            return activePatches.has(String(pid));
        }

        zonesLayerGroup.eachLayer(layer => {
            if (layer.zoneData) {
                const matchPriority = !priorityTouched || priorities.has(layer.zoneData.priority);
                const matchPlant = !isPlantTouched || !layer.zoneData.plantNames || layer.zoneData.plantNames.some(p => plants.has(p));
                const matchLm = matchLandmark(layer.zoneData.id);
                const matchPa = matchPatch(layer.zoneData);
                if (matchPriority && matchPlant && matchLm && matchPa) {
                    layer.setStyle({ opacity: 0.7, fillOpacity: 0.15 });
                } else {
                    layer.setStyle({ opacity: 0.1, fillOpacity: 0.03 });
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
            const el = label.getElement();
            if (el) el.style.opacity = match ? '1' : '0.1';
            // Filter leader lines for this label's zone
            if (label._leaderLines) {
                label._leaderLines.forEach(line => {
                    const le = line.getElement();
                    if (le) le.style.opacity = match ? '' : '0.05';
                });
            }
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
            if (visible) {
                if (!map.hasLayer(labelsLayerGroup)) map.addLayer(labelsLayerGroup);
                updateLabelSizes();
            } else {
                if (map.hasLayer(labelsLayerGroup)) map.removeLayer(labelsLayerGroup);
            }
        } else if (layer === 'leader_lines') {
            if (visible) {
                if (!map.hasLayer(leaderLinesLayerGroup)) map.addLayer(leaderLinesLayerGroup);
            } else {
                if (map.hasLayer(leaderLinesLayerGroup)) map.removeLayer(leaderLinesLayerGroup);
            }
        } else if (layer === 'pipelines') {
            if (visible) {
                if (!map.hasLayer(pipelinesLayerGroup)) map.addLayer(pipelinesLayerGroup);
            } else {
                if (map.hasLayer(pipelinesLayerGroup)) map.removeLayer(pipelinesLayerGroup);
            }
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
                            html: '<div style="transform:translate(-50%,-50%);white-space:nowrap;"><span style="font-weight:600;color:' + lm.boundary_color + ';text-shadow:0 0 4px white,0 0 4px white;">' + lm.name + '</span></div>',
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
