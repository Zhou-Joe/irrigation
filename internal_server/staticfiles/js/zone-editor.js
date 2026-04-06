/**
 * Interactive Zone Boundary Editor
 * Allows drawing and modifying polygon boundaries on a map
 */

(function() {
    'use strict';

    let editMap = null;
    let polygon = null;
    let markers = [];
    let history = [];
    const MAX_HISTORY = 20;

    const POLYGON_STYLE = {
        color: '#1B4332',
        weight: 2,
        fillColor: '#2D6A4F',
        fillOpacity: 0.25
    };

    const MARKER_ICON = L.divIcon({
        className: 'boundary-marker',
        html: '<div class="marker-dot"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8]
    });

    const HIGHLIGHT_ICON = L.divIcon({
        className: 'boundary-marker highlight',
        html: '<div class="marker-dot"></div>',
        iconSize: [20, 20],
        iconAnchor: [10, 10]
    });

    /**
     * Initialize the edit map
     */
    function initEditMap() {
        console.log('Initializing edit map...');

        const mapContainer = document.getElementById('editMap');
        if (!mapContainer) {
            console.error('Map container #editMap not found');
            return;
        }

        editMap = L.map('editMap', {
            center: [37.788, -122.432],
            zoom: 13
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(editMap);

        // Load existing boundary points
        const hiddenInput = document.getElementById('boundary_points');
        if (hiddenInput && hiddenInput.value) {
            try {
                const points = JSON.parse(hiddenInput.value);
                console.log('Loaded boundary points:', points);
                loadBoundaryPoints(points);
            } catch (e) {
                console.warn('Could not parse existing boundary points:', e);
            }
        }

        // Map click to add points
        editMap.on('click', function(e) {
            addPoint(e.latlng);
        });

        // Update UI
        updatePointCount();
        updateCoordList();

        console.log('Edit map initialized successfully');
    }

    /**
     * Load boundary points from data
     */
    function loadBoundaryPoints(points) {
        if (!points || points.length === 0) return;

        const latLngs = points.map(p => {
            if (Array.isArray(p)) {
                return L.latLng(p[0], p[1]);
            } else if (p.lat !== undefined && p.lng !== undefined) {
                return L.latLng(p.lat, p.lng);
            }
            return null;
        }).filter(p => p !== null);

        if (latLngs.length === 0) return;

        // Create markers
        latLngs.forEach((latlng, index) => {
            createMarker(latlng, index);
        });

        // Create polygon
        updatePolygon();
        fitMapToPoints();

        // Save initial state to history
        saveToHistory();
    }

    /**
     * Add a new point
     */
    function addPoint(latlng) {
        saveToHistory();
        createMarker(latlng, markers.length);
        updatePolygon();
        updatePointCount();
        updateCoordList();
    }

    /**
     * Create a draggable marker
     */
    function createMarker(latlng, index) {
        const marker = L.marker(latlng, {
            icon: MARKER_ICON,
            draggable: true
        }).addTo(editMap);

        marker._pointIndex = index;

        // Drag events
        marker.on('dragstart', function() {
            saveToHistory();
        });

        marker.on('drag', function(e) {
            updatePolygon();
            updateCoordList();
        });

        marker.on('dragend', function(e) {
            // Index is updated in updateCoordList
        });

        // Right-click to remove
        marker.on('contextmenu', function(e) {
            L.DomEvent.stopPropagation(e);
            removeMarker(marker);
        });

        // Highlight on hover
        marker.on('mouseover', function() {
            marker.setIcon(HIGHLIGHT_ICON);
        });

        marker.on('mouseout', function() {
            marker.setIcon(MARKER_ICON);
        });

        markers.push(marker);
    }

    /**
     * Remove a marker
     */
    function removeMarker(marker) {
        saveToHistory();
        const index = markers.indexOf(marker);
        if (index > -1) {
            editMap.removeLayer(marker);
            markers.splice(index, 1);

            // Re-index remaining markers
            markers.forEach((m, i) => {
                m._pointIndex = i;
            });

            updatePolygon();
            updatePointCount();
            updateCoordList();
        }
    }

    /**
     * Update the polygon from current markers
     */
    function updatePolygon() {
        if (polygon) {
            editMap.removeLayer(polygon);
        }

        if (markers.length >= 3) {
            const latLngs = markers.map(m => m.getLatLng());
            polygon = L.polygon(latLngs, POLYGON_STYLE).addTo(editMap);
        }

        updateHiddenInput();
    }

    /**
     * Update the hidden input with current points
     */
    function updateHiddenInput() {
        const points = markers.map(m => ({
            lat: parseFloat(m.getLatLng().lat.toFixed(6)),
            lng: parseFloat(m.getLatLng().lng.toFixed(6))
        }));

        document.getElementById('boundary_points').value = JSON.stringify(points);
    }

    /**
     * Update the point count display
     */
    function updatePointCount() {
        document.getElementById('pointCount').textContent = markers.length;
    }

    /**
     * Update the coordinate list UI
     */
    function updateCoordList() {
        const container = document.getElementById('coordList');
        container.innerHTML = '';

        markers.forEach((marker, index) => {
            const latlng = marker.getLatLng();
            const row = document.createElement('div');
            row.className = 'coord-row';
            row.innerHTML = `
                <span class="coord-index">${index + 1}</span>
                <input type="number" step="any" class="coord-input lat-input" value="${latlng.lat.toFixed(6)}" data-index="${index}" data-type="lat">
                <input type="number" step="any" class="coord-input lng-input" value="${latlng.lng.toFixed(6)}" data-index="${index}" data-type="lng">
                <button type="button" class="coord-delete" data-index="${index}">×</button>
            `;
            container.appendChild(row);
        });

        // Add event listeners
        container.querySelectorAll('.coord-input').forEach(input => {
            input.addEventListener('change', function() {
                const index = parseInt(this.dataset.index);
                const type = this.dataset.type;
                const marker = markers[index];
                if (marker) {
                    saveToHistory();
                    const latlng = marker.getLatLng();
                    if (type === 'lat') {
                        marker.setLatLng([parseFloat(this.value), latlng.lng]);
                    } else {
                        marker.setLatLng([latlng.lat, parseFloat(this.value)]);
                    }
                    updatePolygon();
                }
            });
        });

        container.querySelectorAll('.coord-delete').forEach(btn => {
            btn.addEventListener('click', function() {
                const index = parseInt(this.dataset.index);
                removeMarker(markers[index]);
            });
        });
    }

    /**
     * Fit map to show all points
     */
    function fitMapToPoints() {
        if (markers.length > 0) {
            const bounds = L.latLngBounds(markers.map(m => m.getLatLng()));
            editMap.fitBounds(bounds, { padding: [30, 30] });
        }
    }

    /**
     * Save current state to history
     */
    function saveToHistory() {
        const state = markers.map(m => ({
            lat: m.getLatLng().lat,
            lng: m.getLatLng().lng
        }));
        history.push(JSON.stringify(state));
        if (history.length > MAX_HISTORY) {
            history.shift();
        }
        updateUndoButton();
    }

    /**
     * Undo last action
     */
    function undo() {
        if (history.length < 2) return;

        history.pop(); // Remove current state
        const prevState = JSON.parse(history[history.length - 1]);

        // Clear current markers
        markers.forEach(m => editMap.removeLayer(m));
        markers = [];

        // Restore previous state
        prevState.forEach(p => {
            createMarker(L.latLng(p.lat, p.lng), markers.length);
        });

        updatePolygon();
        updatePointCount();
        updateCoordList();
        updateUndoButton();
    }

    /**
     * Update undo button state
     */
    function updateUndoButton() {
        const btn = document.getElementById('undoAction');
        btn.disabled = history.length <= 1;
    }

    /**
     * Clear all points
     */
    function clearAllPoints() {
        if (markers.length === 0) return;
        if (!confirm('Are you sure you want to clear all boundary points?')) return;

        saveToHistory();
        markers.forEach(m => editMap.removeLayer(m));
        markers = [];
        updatePolygon();
        updatePointCount();
        updateCoordList();
    }

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', function() {
        initEditMap();

        // Button handlers
        document.getElementById('clearBoundary').addEventListener('click', clearAllPoints);
        document.getElementById('undoAction').addEventListener('click', undo);
    });
})();