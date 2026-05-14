/**
 * Leaflet Map Initialization and Zone Rendering
 * Handles interactive map with irrigation zones
 */

(function() {
    'use strict';

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

    // Zone code label markers
    let zoneLabels = [];

    // Currently highlighted layer
    let highlightedLayer = null;

    // Design system status-based polygon colors
    // Default zone style (fallback when no status)
    const defaultStyle = {
        color: '#2D6A4F',
        weight: 2,
        opacity: 0.8,
        fillColor: '#2D6A4F',
        fillOpacity: 0.25
    };

    // Highlighted/selected zone style
    const highlightStyle = {
        color: '#D4A574',
        weight: 3,
        opacity: 1,
        fillColor: '#D4A574',
        fillOpacity: 0.4
    };

    // Status-based polygon styling (from design system)
    const statusStyles = {
        completed: {
            color: '#40916C',
            weight: 2,
            opacity: 0.8,
            fillColor: '#40916C',
            fillOpacity: 0.35
        },
        in_progress: {
            color: '#CC7722',
            weight: 2,
            opacity: 0.8,
            fillColor: '#CC7722',
            fillOpacity: 0.35
        },
        unarranged: {
            color: '#888888',
            weight: 2,
            opacity: 0.8,
            fillColor: '#888888',
            fillOpacity: 0.25
        },
        canceled: {
            color: '#9B2226',
            weight: 2,
            opacity: 0.8,
            fillColor: '#9B2226',
            fillOpacity: 0.25
        },
        delayed: {
            color: '#7B5544',
            weight: 2,
            opacity: 0.8,
            fillColor: '#7B5544',
            fillOpacity: 0.35
        },
        // Legacy status names for backwards compatibility
        done: {
            color: '#40916C',
            weight: 2,
            opacity: 0.8,
            fillColor: '#40916C',
            fillOpacity: 0.35
        },
        working: {
            color: '#CC7722',
            weight: 2,
            opacity: 0.8,
            fillColor: '#CC7722',
            fillOpacity: 0.35
        },
        scheduled: {
            color: '#52B788',
            weight: 2,
            opacity: 0.8,
            fillColor: '#52B788',
            fillOpacity: 0.25
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

        // Initialize zones layer group
        zonesLayerGroup = L.layerGroup().addTo(map);

        // Initialize pipelines layer group
        pipelinesLayerGroup = L.layerGroup().addTo(map);

        // Load and render zones
        loadZones();

        // Load and render pipelines
        loadPipelines();

        // Update zone label sizes on zoom
        map.on('zoomend', updateLabelSizes);
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
        const label = L.marker(center, {
            interactive: false,
            icon: L.divIcon({
                className: 'zone-label',
                html: `<span style="font-size:${size}px;${rotation}">${code}</span>`,
                iconSize: null,
                iconAnchor: [0, 0]
            })
        });
        label._zone = zone;
        zonesLayerGroup.addLayer(label);
        zoneLabels.push(label);
        return label;
    }

    /**
     * Calculate label font size based on zoom level
     */
    function getLabelFontSize(zoom) {
        return Math.max(5, Math.round(55 * Math.pow(0.7, 19 - zoom)));
    }

    /**
     * Update all zone label sizes on zoom change
     */
    function updateLabelSizes() {
        const baseSize = getLabelFontSize(map.getZoom());
        zoneLabels.forEach(label => {
            const zone = label._zone;
            const scale = zone ? (zone.label_scale || 1.0) : 1.0;
            const size = baseSize * scale;
            const el = label.getElement();
            if (el) {
                const span = el.querySelector('span');
                if (span) span.style.fontSize = size + 'px';
            }
        });
    }

    /**
     * Render zones on the map (supports multi-polygon format)
     */
    function renderZones(zones) {
        console.log('renderZones called with', zones.length, 'zones');
        zonesLayerGroup.clearLayers();
        zoneLabels = [];

        zones.forEach(zone => {
            if (!zone.boundary_points || zone.boundary_points.length === 0) {
                console.warn('Zone has no boundary points:', zone.name);
                return;
            }

            try {
                let zoneStyle;
                if (zone.boundary_color) {
                    zoneStyle = {
                        color: zone.boundary_color,
                        weight: 2,
                        opacity: 0.8,
                        fillColor: zone.boundary_color,
                        fillOpacity: 0.25
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
                };

                if (isMultiPolygonFormat(zone.boundary_points)) {
                    // Multi-polygon: each element is a separate polygon ring
                    let allLatLngs = [];
                    zone.boundary_points.forEach((ring, ringIdx) => {
                        const latLngs = pointsToLatLngs(ring);
                        if (latLngs.length < 3) return;

                        const polygon = L.polygon(latLngs, zoneStyle);
                        polygon.zoneData = zoneData;
                        polygon.originalStyle = zoneStyle;
                        polygon.on('mouseover', handleMouseOver);
                        polygon.on('mouseout', handleMouseOut);
                        polygon.on('click', handleClick);
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

                    const polygon = L.polygon(latLngs, zoneStyle);
                    polygon.zoneData = zoneData;
                    polygon.originalStyle = zoneStyle;
                    polygon.on('mouseover', handleMouseOver);
                    polygon.on('mouseout', handleMouseOut);
                    polygon.on('click', handleClick);
                    zonesLayerGroup.addLayer(polygon);
                    zone._allLatLngs = latLngs;
                    addZoneLabel(zone);
                }

                // Add pending request markers if any
                if (zone.pending_requests && zone.pending_requests.length > 0 && zone.center) {
                    addPendingRequestMarker(zone);
                }
            } catch (err) {
                console.error('Error creating polygon for zone:', zone.name, err);
            }
        });

        console.log('Finished rendering. Total layers:', zonesLayerGroup.getLayers().length);
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
    let _serverSettingsLoaded = false;

    // Load settings from server on init (once), then merge with localStorage
    async function loadSettingsFromServer() {
        try {
            const resp = await fetch('/api/user/preferences', {credentials: 'same-origin'});
            if (!resp.ok) return;
            const data = await resp.json();
            const serverPrefs = data.preferences || {};
            const serverFields = serverPrefs[CARD_SETTINGS_KEY];
            if (serverFields && typeof serverFields === 'object') {
                localStorage.setItem(CARD_SETTINGS_KEY, JSON.stringify(serverFields));
            }
            _serverSettingsLoaded = true;
        } catch (e) {}
    }

    function getCardFieldSettings() {
        try {
            const saved = localStorage.getItem(CARD_SETTINGS_KEY);
            if (saved) {
                const parsed = JSON.parse(saved);
                const defaults = getDefaultCardFieldSettings();
                return Object.assign(defaults, parsed);
            }
        } catch (e) {}
        return getDefaultCardFieldSettings();
    }

    function getDefaultCardFieldSettings() {
        const defaults = {};
        ZONE_CARD_FIELDS.forEach(f => { defaults[f.key] = false; });
        ['priority', 'area', 'patchInfo', 'plantType', 'irrigationForeman'].forEach(k => {
            defaults[k] = true;
        });
        return defaults;
    }

    function saveCardFieldSetting(key, visible) {
        const settings = getCardFieldSettings();
        settings[key] = visible;
        // Save to localStorage immediately
        localStorage.setItem(CARD_SETTINGS_KEY, JSON.stringify(settings));
        // Sync to server (fire-and-forget)
        _syncSettingsToServer(settings);
    }

    async function _syncSettingsToServer(settings) {
        try {
            // Read full preferences, merge, then save
            let allPrefs = {};
            try {
                const resp = await fetch('/api/user/preferences', {credentials: 'same-origin'});
                if (resp.ok) allPrefs = (await resp.json()).preferences || {};
            } catch (e) {}
            allPrefs[CARD_SETTINGS_KEY] = settings;
            await fetch('/api/user/preferences', {
                method: 'PUT',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ''
                },
                body: JSON.stringify({preferences: allPrefs})
            });
        } catch (e) {}
    }

    // Load server settings on page load
    loadSettingsFromServer();

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
                entries.sort((a, b) => {
                    const da = a.date || '', db = b.date || '';
                    const ia = !da || da === '日期格式错误', ib = !db || db === '日期格式错误';
                    if (ia && ib) return 0;
                    if (ia) return 1;
                    if (ib) return -1;
                    return db.localeCompare(da);
                });
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
                    <button class="popup-settings-btn" onclick="togglePopupSettings()" title="自定义显示字段">⚙</button>
                </div>
                ${hasExtra ? '<div class="popup-fields">' + fieldsHtml + faultHtml + pendingHtml + '</div>' : ''}
                <div class="popup-footer">
                    <button class="popup-detail-btn" onclick="window.open('/zone/${zone.id}/detail/', '_blank')">查看区域详情</button>
                </div>
            </div>
        `;
    }

    function buildSettingsHtml(zone) {
        const settings = getCardFieldSettings();
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
                <div class="popup-footer">
                    <button class="popup-detail-btn" onclick="togglePopupSettings()">完成</button>
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
    window.togglePopupSettings = togglePopupSettings;
    window.handleFieldToggle = handleFieldToggle;
    window._toggleNotesExpand = function(listId, btn) {
        const collapsed = document.getElementById(listId + '_collapsed');
        const expanded = document.getElementById(listId + '_expanded');
        if (collapsed && expanded) {
            collapsed.style.display = collapsed.style.display === 'none' ? '' : 'none';
            expanded.style.display = expanded.style.display === 'none' ? '' : 'none';
        }
    };

    /**
     * Handle mouse over event on zone
     * @param {Event} e - Leaflet event
     */
    function handleMouseOver(e) {
        const layer = e.target;
        if (highlightedLayer !== layer) {
            highlightedLayer = layer;
            layer.setStyle(highlightStyle);
            layer.bringToFront();
        }
    }

    /**
     * Handle mouse out event on zone
     * @param {Event} e - Leaflet event
     */
    function handleMouseOut(e) {
        const layer = e.target;
        if (highlightedLayer === layer) {
            highlightedLayer = null;
            // Restore original status-based style
            layer.setStyle(layer.originalStyle || defaultStyle);
        }
    }

    /**
     * Handle click event on zone polygon
     * @param {Event} e - Leaflet event
     */
    function handleClick(e) {
        const layer = e.target;
        const zoneId = layer.zoneData?.id;

        if (zoneId) {
            // Reset previously highlighted layer
            if (highlightedLayer && highlightedLayer !== layer) {
                highlightedLayer.setStyle(highlightedLayer.originalStyle || defaultStyle);
            }
            highlightedLayer = layer;
            layer.setStyle(highlightStyle);
            layer.bringToFront();

            // Zoom to the clicked zone with animation
            if (layer.getBounds()) {
                map.flyToBounds(layer.getBounds(), {
                    padding: [50, 50],
                    duration: 0.8,
                    easeLinearity: 0.25
                });
            }

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

                        // Fly to the zone with smooth animation
                        const bounds = layer.getBounds();
                        console.log('Bounds:', bounds);
                        if (bounds) {
                            map.flyToBounds(bounds, {
                                padding: [50, 50],
                                duration: 0.8,
                                easeLinearity: 0.25
                            });
                        }
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
        const priorities = window.activePriorities || new Set(['critical', 'high', 'medium', 'low', 'abolished']);
        const plants = window.activePlants || new Set();
        const isPlantTouched = window.plantFilterTouched || false;
        const showAllPriorities = priorities.size === 5;

        zonesLayerGroup.eachLayer(layer => {
            if (layer.zoneData) {
                const matchPriority = showAllPriorities || priorities.has(layer.zoneData.priority);
                const matchPlant = !isPlantTouched || !layer.zoneData.plantNames || layer.zoneData.plantNames.some(p => plants.has(p));
                if (matchPriority && matchPlant) {
                    layer.setStyle({ opacity: 0.8, fillOpacity: 0.25 });
                } else {
                    layer.setStyle({ opacity: 0.1, fillOpacity: 0.03 });
                }
            }
        });
        zoneLabels.forEach(label => {
            const zone = zonesData.find(z => z.id === label.zoneId);
            if (!zone) return;
            const matchPriority = showAllPriorities || priorities.has(zone.priority || 'medium');
            const matchPlant = !isPlantTouched || !zone.plant_names || zone.plant_names.some(p => plants.has(p));
            label.element.style.opacity = (matchPriority && matchPlant) ? '1' : '0.1';
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
            zoneLabels.forEach(label => {
                if (visible) {
                    if (!map.hasLayer(label)) map.addLayer(label);
                    label.element.style.display = '';
                } else {
                    if (map.hasLayer(label)) map.removeLayer(label);
                    label.element.style.display = 'none';
                }
            });
        } else if (layer === 'pipelines') {
            if (visible) {
                if (!map.hasLayer(pipelinesLayerGroup)) map.addLayer(pipelinesLayerGroup);
            } else {
                if (map.hasLayer(pipelinesLayerGroup)) map.removeLayer(pipelinesLayerGroup);
            }
        }
    };
})();
