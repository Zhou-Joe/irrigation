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
        maxZoom: 19
    });

    // Zone layers group
    let zonesLayerGroup;

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
            maxZoom: 19,
            minZoom: 13,
            maxBounds: bounds,
            maxBoundsViscosity: 1.0,
            layers: [satelliteLayer],
            zoomControl: true
        });

        // Initialize zones layer group
        zonesLayerGroup = L.layerGroup().addTo(map);

        // Load and render zones
        loadZones();
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
     * Render zones on the map
     */
    function renderZones(zones) {
        console.log('renderZones called with', zones.length, 'zones');
        zonesLayerGroup.clearLayers();
        console.log('zonesLayerGroup cleared');

        zones.forEach(zone => {
            console.log('Processing zone:', zone.name, 'boundary_points:', zone.boundary_points);
            if (!zone.boundary_points || zone.boundary_points.length === 0) {
                console.warn('Zone has no boundary points:', zone.name);
                return;
            }

            // Convert boundary points to LatLng array
            const latLngs = zone.boundary_points.map(point => {
                if (Array.isArray(point)) {
                    return [point[0], point[1]];
                } else if (point.lat !== undefined && point.lng !== undefined) {
                    return [point.lat, point.lng];
                }
                console.warn('Invalid point format:', point);
                return null;
            }).filter(p => p !== null);

            if (latLngs.length === 0) {
                console.warn('No valid coordinates for zone:', zone.name);
                return;
            }

            console.log('Creating polygon for zone:', zone.name, 'with', latLngs.length, 'points:', latLngs);

            try {
                // Use custom boundary_color if set
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

                const polygon = L.polygon(latLngs, zoneStyle);
                polygon.zoneData = {
                    id: zone.id,
                    code: zone.code,
                    name: zone.name,
                    status: zone.status,
                    statusDisplay: zone.statusDisplay,
                    plantCount: zone.plantCount,
                    pendingWorkOrders: zone.pendingWorkOrders,
                    pendingRequests: zone.pending_requests || []
                };
                polygon.originalStyle = zoneStyle;

                polygon.on('mouseover', handleMouseOver);
                polygon.on('mouseout', handleMouseOut);
                polygon.on('click', handleClick);

                zonesLayerGroup.addLayer(polygon);
                console.log('Added polygon to layer group. Total layers now:', zonesLayerGroup.getLayers().length);

                const popupContent = createPopupContent(zone);
                polygon.bindPopup(popupContent);

                // Add pending request markers if any
                if (zone.pending_requests && zone.pending_requests.length > 0 && zone.center) {
                    console.log('Adding pending request marker for zone:', zone.name, 'count:', zone.pending_requests.length);
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
        const statusClass = `status-${zone.status}`;
        const plantText = `${zone.plant_count || zone.plantCount || 0} 种植物`;
        const workOrderText = zone.pendingWorkOrders > 0
            ? `${zone.pendingWorkOrders} 个待处理工单`
            : '无待处理工单';

        // Pending water requests section
        let pendingWaterHtml = '';
        const pendingRequests = zone.pending_requests || zone.pendingRequests || [];
        if (pendingRequests.length > 0) {
            pendingWaterHtml = `
                <div class="popup-pending-water" style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #ddd;">
                    <span style="color: #CC7722; font-weight: 600;">💧 ${pendingRequests.length} 个待审批浇水需求</span>
                </div>
            `;
        }

        return `
            <div class="popup-content">
                <h3>${zone.name}</h3>
                <div class="popup-zone-code">编号: ${zone.code}</div>
                <div class="popup-zone-status">
                    <span class="status-badge ${statusClass}">${zone.statusDisplay || zone.status_display}</span>
                </div>
                <div class="popup-zone-plants">${plantText}</div>
                <div class="popup-zone-work-orders">${workOrderText}</div>
                ${pendingWaterHtml}
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
