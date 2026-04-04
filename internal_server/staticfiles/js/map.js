/**
 * Leaflet Map Initialization and Zone Rendering
 * Handles interactive map with irrigation zones
 */

(function() {
    'use strict';

    // Map instance
    let map;

    // Tile layers
    const streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19
    });

    const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        maxZoom: 19
    });

    // Zone layers group
    let zonesLayerGroup;

    // Currently highlighted layer
    let highlightedLayer = null;

    // Original style for reset
    const defaultStyle = {
        color: '#2196f3',
        weight: 2,
        opacity: 0.8,
        fillColor: '#2196f3',
        fillOpacity: 0.2
    };

    const highlightStyle = {
        color: '#ff5722',
        weight: 3,
        opacity: 1,
        fillColor: '#ff5722',
        fillOpacity: 0.4
    };

    /**
     * Initialize the map
     */
    function initMap() {
        // Create map centered on default location
        map = L.map('map', {
            center: [0, 0],
            zoom: 3,
            layers: [streetLayer],
            zoomControl: true,
            layerControl: true
        });

        // Add layer control
        L.control.layers({
            'Street': streetLayer,
            'Satellite': satelliteLayer
        }, {}, {
            position: 'topright',
            collapsed: true
        }).addTo(map);

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
            renderZones(zones);
            fitMapToBounds(zones);
        } catch (error) {
            console.error('Error parsing zones data:', error);
        }
    }

    /**
     * Render zones on the map
     * @param {Array} zones - Array of zone objects
     */
    function renderZones(zones) {
        // Clear existing layers
        zonesLayerGroup.clearLayers();

        zones.forEach(zone => {
            if (!zone.boundary_points || zone.boundary_points.length === 0) {
                return;
            }

            // Convert boundary points to LatLng array
            const latLngs = zone.boundary_points.map(point => [point.lat, point.lng]);

            // Create polygon
            const polygon = L.polygon(latLngs, defaultStyle);

            // Store zone data on the layer
            polygon.zoneData = {
                id: zone.id,
                code: zone.code,
                name: zone.name,
                status: zone.status,
                statusDisplay: zone.statusDisplay,
                plantCount: zone.plantCount,
                pendingWorkOrders: zone.pendingWorkOrders
            };

            // Add event listeners
            polygon.on('mouseover', handleMouseOver);
            polygon.on('mouseout', handleMouseOut);
            polygon.on('click', handleClick);

            // Add to layer group
            zonesLayerGroup.addLayer(polygon);

            // Create popup content
            const popupContent = createPopupContent(zone);
            polygon.bindPopup(popupContent);
        });
    }

    /**
     * Create popup content for a zone
     * @param {Object} zone - Zone data
     * @returns {string} HTML content for popup
     */
    function createPopupContent(zone) {
        const statusClass = `status-${zone.status}`;
        const plantText = `${zone.plantCount} plant${zone.plantCount !== 1 ? 's' : ''}`;
        const workOrderText = zone.pendingWorkOrders > 0
            ? `${zone.pendingWorkOrders} pending work order${zone.pendingWorkOrders !== 1 ? 's' : ''}`
            : 'No pending work orders';

        return `
            <div class="popup-content">
                <h3>${zone.name}</h3>
                <div class="popup-zone-code">Code: ${zone.code}</div>
                <div class="popup-zone-status">
                    <span class="status-badge ${statusClass}">${zone.statusDisplay}</span>
                </div>
                <div class="popup-zone-plants">${plantText}</div>
                <div class="popup-zone-work-orders">${workOrderText}</div>
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
            layer.setStyle(defaultStyle);
        }
    }

    /**
     * Handle click event on zone
     * @param {Event} e - Leaflet event
     */
    function handleClick(e) {
        const layer = e.target;
        const zoneId = layer.zoneData?.id;

        if (zoneId) {
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
        const allPoints = [];

        zones.forEach(zone => {
            if (zone.boundary_points && zone.boundary_points.length > 0) {
                zone.boundary_points.forEach(point => {
                    allPoints.push([point.lat, point.lng]);
                });
            }
        });

        if (allPoints.length > 0) {
            const bounds = L.latLngBounds(allPoints);
            map.fitBounds(bounds, { padding: [50, 50] });
        }
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

                // Find and highlight the corresponding map layer
                zonesLayerGroup.eachLayer(layer => {
                    if (layer.zoneData?.id === zoneId) {
                        // Highlight on map
                        if (highlightedLayer) {
                            highlightedLayer.setStyle(defaultStyle);
                        }
                        highlightedLayer = layer;
                        layer.setStyle(highlightStyle);
                        layer.bringToFront();

                        // Open popup
                        layer.openPopup();

                        // Fit bounds to this zone
                        if (layer.getBounds()) {
                            map.fitBounds(layer.getBounds(), { padding: [50, 50] });
                        }
                    }
                });

                // Update sidebar selection
                highlightSidebarItem(zoneId);
            });
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initMap();
            setupSidebarInteraction();
        });
    } else {
        initMap();
        setupSidebarInteraction();
    }
})();
