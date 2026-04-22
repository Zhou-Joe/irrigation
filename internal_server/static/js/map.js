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
        attribution: '&copy; Esri, Maxar, Earthstar Geographics',
        maxNativeZoom: 19,
        maxZoom: 22
    });

    // Fallback tile layer for high zoom levels (GeoQ)
    const fallbackLayer = L.tileLayer('https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}', {
        attribution: '&copy; GeoQ 智图',
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
        // Center point adjusted ~1.07km north-east, bounds (2km radius)
        const centerLat = 31.145794 + 0.010; // offset ~1.1km north
        const centerLng = 121.656804 + 0.012; // offset ~1.1km east
        const latOffset = 0.018; // ~2km in latitude
        const lngOffset = 0.021; // ~2km in longitude at lat 31°

        const southWest = L.latLng(centerLat - latOffset, centerLng - lngOffset);
        const northEast = L.latLng(centerLat + latOffset, centerLng + lngOffset);
        const bounds = L.latLngBounds(southWest, northEast);

        // Create map centered on location with satellite layer
        map = L.map('map', {
            center: [centerLat, centerLng],
            zoom: 15,
            maxZoom: 22,
            minZoom: 13,
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
     * Add a zone code label at the centroid of a polygon
     */
    function addZoneLabel(code, latLngs) {
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
        const center = [latSum / count, lngSum / count];

        const size = getLabelFontSize(map.getZoom());
        const label = L.marker(center, {
            interactive: false,
            icon: L.divIcon({
                className: 'zone-label',
                html: `<span style="font-size:${size}px">${code}</span>`,
                iconSize: null,
                iconAnchor: [0, 0]
            })
        });
        zonesLayerGroup.addLayer(label);
        zoneLabels.push(label);
        return label;
    }

    /**
     * Calculate label font size based on zoom level
     */
    function getLabelFontSize(zoom) {
        return Math.max(8, Math.round(55 * Math.pow(0.7, 19 - zoom)));
    }

    /**
     * Update all zone label sizes on zoom change
     */
    function updateLabelSizes() {
        const size = getLabelFontSize(map.getZoom());
        zoneLabels.forEach(label => {
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

                const popupContent = createPopupContent(zone);
                const zoneData = {
                    id: zone.id,
                    code: zone.code,
                    name: zone.name,
                    status: zone.status,
                    statusDisplay: zone.statusDisplay,
                    plantCount: zone.plantCount,
                    pendingWorkOrders: zone.pendingWorkOrders,
                    pendingRequests: zone.pending_requests || []
                };

                if (isMultiPolygonFormat(zone.boundary_points)) {
                    // Multi-polygon: each element is a separate polygon ring
                    zone.boundary_points.forEach((ring, ringIdx) => {
                        const latLngs = pointsToLatLngs(ring);
                        if (latLngs.length < 3) return;

                        const polygon = L.polygon(latLngs, zoneStyle);
                        polygon.zoneData = zoneData;
                        polygon.originalStyle = zoneStyle;
                        polygon.bindPopup(popupContent);
                        polygon.on('mouseover', handleMouseOver);
                        polygon.on('mouseout', handleMouseOut);
                        polygon.on('click', handleClick);
                        zonesLayerGroup.addLayer(polygon);
                        addZoneLabel(zone.code, latLngs);
                    });
                } else {
                    // Legacy single-polygon format
                    const latLngs = pointsToLatLngs(zone.boundary_points);
                    if (latLngs.length < 3) return;

                    const polygon = L.polygon(latLngs, zoneStyle);
                    polygon.zoneData = zoneData;
                    polygon.originalStyle = zoneStyle;
                    polygon.bindPopup(popupContent);
                    polygon.on('mouseover', handleMouseOver);
                    polygon.on('mouseout', handleMouseOut);
                    polygon.on('click', handleClick);
                    zonesLayerGroup.addLayer(polygon);
                    addZoneLabel(zone.code, latLngs);
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

    /**
     * Create popup content for a zone
     * @param {Object} zone - Zone data
     * @returns {string} HTML content for popup
     */
    function createPopupContent(zone) {
        // Stats summary
        const plantCount = zone.plant_count || zone.plantCount || 0;
        const equipmentCount = zone.equipment_count || 0;
        const faultCount = zone.recent_fault_count || 0;

        // Pending water requests section
        let pendingWaterHtml = '';
        const pendingRequests = zone.pending_requests || zone.pendingRequests || [];
        if (pendingRequests.length > 0) {
            pendingWaterHtml = `
                <div class="popup-pending-water" style="margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.2);">
                    <span style="color: #CC7722; font-weight: 600;">💧 ${pendingRequests.length} 个待审批浇水需求</span>
                </div>
            `;
        }

        // Fault warning (only show if there are faults)
        let faultHtml = '';
        if (faultCount > 0) {
            faultHtml = `
                <div style="display: inline-block; background: rgba(204,119,34,0.2); color: #CC7722; padding: 4px 10px; border-radius: 8px; font-size: 0.85em; margin-top: 8px;">
                    ⚠️ 近30天 ${faultCount} 次故障
                </div>
            `;
        }

        return `
            <div class="popup-content" style="min-width: 180px;">
                <h3 style="margin: 0 0 4px 0; font-size: 1.1em; color: #1B4332;">${zone.name}</h3>
                <div style="font-size: 0.85em; color: #666; margin-bottom: 8px;">编号: ${zone.code}</div>

                <!-- Stats row -->
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <div style="background: rgba(82,183,136,0.15); color: #52B788; padding: 4px 10px; border-radius: 8px; font-size: 0.85em;">
                        🌱 ${plantCount} 种植物
                    </div>
                    <div style="background: rgba(64,145,108,0.15); color: #40916C; padding: 4px 10px; border-radius: 8px; font-size: 0.85em;">
                        🔧 ${equipmentCount} 设备
                    </div>
                </div>

                ${faultHtml}
                ${pendingWaterHtml}

                <!-- View detail button -->
                <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.2);">
                    <button onclick="window.location.href='/zone/${zone.id}/detail/'" style="
                        background: #2D6A4F;
                        color: white;
                        border: none;
                        padding: 8px 16px;
                        border-radius: 8px;
                        cursor: pointer;
                        font-size: 0.9em;
                        width: 100%;
                        transition: background 0.2s;
                    " onmouseover="this.style.background='#1B4332'" onmouseout="this.style.background='#2D6A4F'">
                        查看区域详情
                    </button>
                </div>
            </div>
        `;
    }

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

            // Open popup
            layer.openPopup();
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

                        // Open popup
                        layer.openPopup();

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
            locateBtn.textContent = '定位中...';
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
                    locateBtn.textContent = '📍 定位我';
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
                    locateBtn.textContent = '📍 定位我';
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
            button.innerHTML = '📍';
            button.title = '';
            // Design system button styling
            button.style.cssText = 'background: #EDE8DC; border: 2px solid #1B4332; border-radius: 8px; padding: 8px 12px; font-size: 18px; cursor: pointer; margin-bottom: 10px; transition: all 150ms ease;';
            button.onmouseover = () => {
                button.style.background = '#D4A574';
                button.style.borderColor = '#D4A574';
            };
            button.onmouseout = () => {
                button.style.background = '#EDE8DC';
                button.style.borderColor = '#1B4332';
            };

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
})();
