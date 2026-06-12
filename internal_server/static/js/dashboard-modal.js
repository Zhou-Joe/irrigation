/* dashboard-modal.js — V2 workorder & water request as dashboard modal popups */
(function () {
    'use strict';

    var _currentModal = null;
    var _mapMode = false;
    var _selectedZoneCodes = new Set();
    var _selectionLayerGroup = null;
    var _selectionOverlays = {};
    var _closeTimeout = null;

    var _drawMode = null;
    var _drawPoints = [];
    var _tempMarkers = [];
    var _tempPolyline = null;
    var _drawnShapes = [];
    var _shapeIdCounter = 0;
    var _rectStartLL = null;
    var _circleCenter = null;
    var _circleStep = 0;
    var _shapeColors = ['#e74c3c', '#2980b9', '#8e44ad', '#e67e22', '#16a085', '#c0392b', '#2c3e50'];

    var _formDataCache = { workorder: null, water_request: null };
    var _photoFiles = [];
    var _faultEntries = [];

    function getMap() { return window._map; }
    function $(id) { return document.getElementById(id); }

    // P1-5: Unified CSRF helper — delegates to shared global when available
    function getCSRFToken() {
        if (typeof window._getCSRFToken === 'function') return window._getCSRFToken();
        // Fallback
        var cookie = document.cookie.split('; ').find(function (c) { return c.startsWith('csrftoken='); });
        if (cookie) return cookie.split('=')[1];
        var el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el) return el.value;
        return '';
    }

    function injectCSRF(formEl) {
        if (!formEl) return;
        var token = getCSRFToken();
        if (!token) return;
        var input = document.createElement('input');
        input.type = 'hidden'; input.name = 'csrfmiddlewaretoken'; input.value = token;
        formEl.insertBefore(input, formEl.firstChild);
    }

    function showToast(msg, type) {
        var t = $('v2ModalToast');
        if (!t) return;
        t.textContent = msg;
        t.className = 'show ' + (type || '');
        setTimeout(function () { t.className = ''; }, 3000);
    }

    // P1-4: Shared helper to create selection overlay for a zone code
    function addOverlayForCode(code) {
        var zl = window._dashboardZonesLayer;
        if (!zl || !_selectionLayerGroup) return;
        var overlays = [];
        zl.eachLayer(function (zlayer) {
            if (zlayer.zoneData && zlayer.zoneData.code === code && zlayer.getLatLngs) {
                var hl = L.polygon(zlayer.getLatLngs(), { color: '#2D6A4F', weight: 2.5, fillColor: '#2D6A4F', fillOpacity: 0.35, interactive: false });
                _selectionLayerGroup.addLayer(hl);
                overlays.push(hl);
            }
        });
        _selectionOverlays[code] = overlays;
    }

    window.openV2Modal = function (type) {
        // Cancel any pending hide timeout from a previous close
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        if (_currentModal) closeV2Modal(_currentModal);
        // closeV2Modal may have set a new timeout — cancel that too
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        _currentModal = type;
        _selectedZoneCodes.clear();
        _photoFiles = [];
        _faultEntries = [];
        _zoneConfirmed = false;

        // Fetch form data in background (cached or from API)
        var dataUrl = type === 'workorder' ? '/api/modal/workorder-data/' : '/api/modal/water-request-data/';
        if (!_formDataCache[type]) {
            fetch(dataUrl, { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) { _formDataCache[type] = data; })
                .catch(function () {});
        }

        // Zone-first flow: go directly to map mode
        enterMapMode(type);
    };

    // Quick workorder: skip map mode, pre-select zones, go straight to form
    window.quickWorkorder = function (zoneCodes) {
        // Cancel any pending hide timeout from a previous close
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        if (_currentModal) closeV2Modal(_currentModal);
        // closeV2Modal may have set a new timeout — cancel that too
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        _currentModal = 'workorder';
        _selectedZoneCodes.clear();
        _photoFiles = [];
        _faultEntries = [];
        zoneCodes.forEach(function (c) { _selectedZoneCodes.add(c); });
        _zoneConfirmed = true;

        // Ensure form data is loaded, then show form
        var showForm = function () {
            if (_formDataCache.workorder) {
                buildForm('workorder', _formDataCache.workorder);
            }
            var backdrop = $('woModalBackdrop');
            var container = $('woModalContainer');
            if (backdrop) backdrop.style.display = '';
            if (container) { container.style.display = ''; container.classList.add('open'); }
            renderZoneSummary();
        };

        if (_formDataCache.workorder) {
            showForm();
        } else {
            fetch('/api/modal/workorder-data/', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) { _formDataCache.workorder = data; showForm(); })
                .catch(function () { showToast('加载表单失败', 'error'); });
        }
    };

    window.closeV2Modal = function (type) {
        if (!type) type = _currentModal;
        // P0-3: skip zone validation when closing/canceling
        _zoneConfirmed = true;
        var exitOk = _mapMode ? exitMapMode() : true;
        var backdrop = $(type === 'workorder' ? 'woModalBackdrop' : 'wrModalBackdrop');
        var container = $(type === 'workorder' ? 'woModalContainer' : 'wrModalContainer');
        if (container) container.classList.remove('open');
        if (_closeTimeout) clearTimeout(_closeTimeout);
        _closeTimeout = setTimeout(function () {
            if (backdrop) backdrop.style.display = 'none';
            if (container) container.style.display = 'none';
            _closeTimeout = null;
        }, 300);
        clearSelection();
        _zoneConfirmed = false;
        _currentModal = null;
        // Reset zone summaries
        var woZS = $('woZoneSummary'); if (woZS) woZS.innerHTML = '<h2>工作记录</h2>';
        var wrZS = $('wrZoneSummary'); if (wrZS) wrZS.innerHTML = '<h2>浇水需求</h2>';
    };

    window.enterMapMode = function (type) {
        if (!type) type = _currentModal;
        var map = getMap();
        if (!map) { showToast('地图未加载，请刷新页面', 'error'); return; }
        _mapMode = true;
        window._v2ModalMapMode = type;
        // Clear any stale close timeout
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        if (!_selectionLayerGroup) _selectionLayerGroup = L.layerGroup().addTo(map);

        // Hide the entire modal container so map is fully clickable
        var backdrop = $(type === 'workorder' ? 'woModalBackdrop' : 'wrModalBackdrop');
        var container = $(type === 'workorder' ? 'woModalContainer' : 'wrModalContainer');
        if (backdrop) backdrop.style.display = 'none';
        if (container) container.style.display = 'none';

        // Show info bar and bottom action bar
        var infoBar = $('v2MapInfoBar');
        if (infoBar) { infoBar.style.display = ''; updateInfoBarText(); }
        var actionBar = $('v2MapActionBar');
        if (actionBar) { actionBar.style.display = ''; updateActionBar(); }

        if (type === 'workorder') enableTapSelect();
        else showDrawToolBar();
    };

    // P0-3: exitMapMode returns boolean — false when zone validation blocks exit
    window.exitMapMode = function () {
        _mapMode = false;
        window._v2ModalMapMode = null;
        var type = _currentModal;
        // Cancel any pending close timeout (safety)
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }

        // Zone-first: first exit = confirm zones & show form
        if (!_zoneConfirmed) {
            var minLabel = type === 'workorder' ? '选择' : '绘制';
            if (_selectedZoneCodes.size === 0) {
                showToast('请先在地图上' + minLabel + '至少一个区域', 'error');
                _mapMode = true;
                window._v2ModalMapMode = type;
                return false;
            }
            _zoneConfirmed = true;
        }

        // Restore modal container
        var backdrop = $(type === 'workorder' ? 'woModalBackdrop' : 'wrModalBackdrop');
        var container = $(type === 'workorder' ? 'woModalContainer' : 'wrModalContainer');
        if (backdrop) backdrop.style.display = '';
        if (container) { container.style.display = ''; container.classList.add('open'); }

        // Build form if not yet rendered
        if (_formDataCache[type]) {
            var bodyId = type === 'workorder' ? 'woModalBody' : 'wrModalBody';
            var body = $(bodyId);
            if (body && (!body.querySelector('form') || body.querySelector('.loading'))) {
                buildForm(type, _formDataCache[type]);
            }
        }

        // Show selected zones above form
        renderZoneSummary();

        var infoBar = $('v2MapInfoBar');
        if (infoBar) infoBar.style.display = 'none';
        var actionBar = $('v2MapActionBar');
        if (actionBar) actionBar.style.display = 'none';
        var drawBar = $('v2DrawToolBar');
        if (drawBar) drawBar.style.display = 'none';
        disableMapInteraction();
        return true;
    };

    var _tapHandler = null;
    var _zoneConfirmed = false;

    function findZoneLayerGroup() {
        // Primary: use the exposed global
        if (window._dashboardZonesLayer) return window._dashboardZonesLayer;
        // Fallback: search map's layer groups for one with zone polygons
        var map = getMap();
        if (!map) return null;
        var found = null;
        map.eachLayer(function (layer) {
            if (found) return;
            if (layer.eachLayer && !found) {
                layer.eachLayer(function (sub) {
                    if (sub.zoneData && sub.zoneData.code) { found = layer; }
                });
            }
        });
        if (found) window._dashboardZonesLayer = found;
        return found;
    }

    function enableTapSelect() {
        var zl = findZoneLayerGroup();
        var map = getMap();
        if (!zl || !map) { showToast('区域图层未加载，请刷新页面', 'error'); return; }

        // Per-layer click handler — works reliably on both desktop and mobile
        _tapHandler = function (e) {
            L.DomEvent.stopPropagation(e);
            var layer = e.target;
            if (!layer._v2Selectable || !layer.zoneData || !layer.zoneData.code) return;
            var code = layer.zoneData.code;
            if (_selectedZoneCodes.has(code)) {
                _selectedZoneCodes.delete(code);
                removeSelectionOverlay(code);
            } else {
                _selectedZoneCodes.add(code);
                addSelectionOverlay(layer);
            }
            updateInfoBarText();
        };

        zl.eachLayer(function (layer) {
            if (layer.zoneData && layer.zoneData.code) {
                layer._v2Selectable = true;
                layer.on('click', _tapHandler);
            }
        });
    }

    function addSelectionOverlay(srcPolygon) {
        var code = srcPolygon.zoneData.code;
        addOverlayForCode(code);
    }

    function removeSelectionOverlay(code) {
        var overlays = _selectionOverlays[code];
        if (!overlays || !_selectionLayerGroup) return;
        overlays.forEach(function (hl) { _selectionLayerGroup.removeLayer(hl); });
        delete _selectionOverlays[code];
    }

    function clearSelection() {
        _selectedZoneCodes.clear();
        if (_selectionLayerGroup) _selectionLayerGroup.clearLayers();
        _selectionOverlays = {};
        _drawnShapes.forEach(function (s) {
            if (s.handles) s.handles.forEach(function (h) { getMap().removeLayer(h); });
            if (s.layer) getMap().removeLayer(s.layer);
        });
        _drawnShapes = [];
        var infoBar = $('v2MapInfoBar');
        if (infoBar) infoBar.style.display = 'none';
    }

    function disableMapInteraction() {
        // Remove per-layer tap handler
        var zl = window._dashboardZonesLayer;
        if (zl && _tapHandler) { zl.eachLayer(function (l) { l.off('click', _tapHandler); }); _tapHandler = null; }
        // Clean up selectable flags
        if (zl) zl.eachLayer(function (l) { delete l._v2Selectable; });
        cancelDraw();
    }

    function updateInfoBarText() {
        var infoBar = $('v2MapInfoBar');
        if (!infoBar) return;
        var codes = Array.from(_selectedZoneCodes);
        var type = _currentModal;
        var hint = type === 'water_request' ? '请使用绘图工具绘制区域' : '请在地图上选择区域';
        if (codes.length === 0) {
            infoBar.innerHTML = '<span style="color:#888;">' + hint + '</span>';
            return;
        }
        if (type === 'water_request') {
            infoBar.innerHTML = '<span style="font-weight:600;color:#2D6A4F;">' + codes.length + '</span> 个区域已选择';
        } else {
            var display = codes.length > 5 ? codes.slice(0, 5).join(', ') + '...' : codes.join(', ');
            infoBar.innerHTML = '<span style="font-weight:600;color:#2D6A4F;">' + codes.length + '</span> 个区域: ' + display;
        }
    }

    function updateActionBar() {
        var confirmBtn = $('v2ActConfirm');
        if (!confirmBtn) return;
        confirmBtn.textContent = !_zoneConfirmed ? '确认区域' : '返回表单';
    }

    function getZoneNameMap() {
        var map = {};
        var zl = window._dashboardZonesLayer;
        if (zl) zl.eachLayer(function (l) {
            if (l.zoneData && l.zoneData.code && l.zoneData.name) map[l.zoneData.code] = l.zoneData.name;
        });
        // Fallback: try sidebar items
        if (Object.keys(map).length === 0) {
            document.querySelectorAll('.zone-item[data-zone-code]').forEach(function (el) {
                var code = el.getAttribute('data-zone-code');
                var nameEl = el.querySelector('.zone-name');
                if (code && nameEl) map[code] = nameEl.textContent.trim();
            });
        }
        return map;
    }

    function renderZoneSummary() {
        var type = _currentModal || 'workorder';
        var el = $(type === 'workorder' ? 'woZoneSummary' : 'wrZoneSummary');
        if (!el) return;
        var codes = Array.from(_selectedZoneCodes);
        if (codes.length === 0) { el.innerHTML = '<h2>' + (type === 'workorder' ? '工作记录' : '浇水需求') + '</h2>'; return; }
        // Deduplicate zone names
        var nameMap = getZoneNameMap();
        var seenNames = {};
        var uniqueNames = [];
        codes.forEach(function (c) {
            var name = nameMap[c] || c;
            if (!seenNames[name]) { seenNames[name] = true; uniqueNames.push(name); }
        });
        var tags = uniqueNames.map(function (n) {
            return '<span style="background:#e8f5e9;color:#2D6A4F;padding:2px 7px;border-radius:10px;font-size:0.85em;font-weight:500;white-space:nowrap;">' + n + '</span>';
        }).join('');
        el.innerHTML = '<div style="font-size:0.85em;color:#888;margin-bottom:4px;">已选 <span style="font-weight:600;color:#2D6A4F;">' + codes.length + '</span> 个区域</div><div style="display:flex;flex-wrap:wrap;gap:3px;max-height:2.4em;overflow:hidden;line-height:1.2;">' + tags + '</div>';
    }

    window._clearModalSelection = function () { clearSelection(); updateInfoBarText(); };

    var _patchChipsBuilt = false;

    window.switchDrawTab = function (tab) {
        document.querySelectorAll('.v2-draw-tab').forEach(function (t) { t.classList.toggle('active', t.dataset.tab === tab); });
        $('v2TabPatch').classList.toggle('active', tab === 'patch');
        $('v2TabDraw').classList.toggle('active', tab === 'draw');
        if (tab === 'patch') { cancelDraw(); getMap().getContainer().style.cursor = ''; }
    };

    function showDrawToolBar() {
        var bar = $('v2DrawToolBar'); if (bar) bar.style.display = '';
        // Build patch chips once
        if (!_patchChipsBuilt) {
            _patchChipsBuilt = true;
            var patchEl = document.getElementById('patches-data');
            if (patchEl && patchEl.textContent) {
                try {
                    var patches = JSON.parse(patchEl.textContent);
                    var container = $('v2PatchChips');
                    if (container) {
                        patches.forEach(function (p) {
                            var chip = document.createElement('div');
                            chip.className = 'v2-chip';
                            chip.style.cssText = 'font-size:0.85em;padding:3px 8px;';
                            chip.textContent = p.name || p.code;
                            chip.dataset.patchId = p.id;
                            chip.addEventListener('click', function () {
                                chip.classList.toggle('active');
                                selectZonesByPatch(p.id, chip.classList.contains('active'));
                            });
                            container.appendChild(chip);
                        });
                    }
                } catch (e) {}
            }
        }
    }

    function selectZonesByPatch(patchId, selected) {
        var zl = window._dashboardZonesLayer;
        if (!zl) return;
        zl.eachLayer(function (l) {
            if (l.zoneData && l.zoneData.patchId == patchId && l.zoneData.code) {
                var code = l.zoneData.code;
                if (selected) {
                    _selectedZoneCodes.add(code);
                    if (!_selectionOverlays[code] && _selectionLayerGroup) {
                        addOverlayForCode(code);
                    }
                } else {
                    _selectedZoneCodes.delete(code);
                    removeSelectionOverlay(code);
                }
            }
        });
        updateInfoBarText();
    }

    window.activateModalDrawTool = function (tool) {
        cancelDraw();
        _drawMode = tool;
        var map = getMap();
        map.getContainer().style.cursor = 'crosshair';
        document.querySelectorAll('.modal-draw-chip').forEach(function (c) { c.classList.toggle('active', c.dataset.tool === tool); });
        var isMobile = 'ontouchstart' in window || window.innerWidth <= 768;
        var hints = { rect: isMobile ? '依次点击两个对角点绘制矩形' : '点击并拖拽绘制矩形', circle: '点击中心，再点击边缘确定半径', polygon: '依次点击各顶点，≥3个点后点击完成' };
        var hint = $('v2DrawHint');
        if (hint) hint.textContent = hints[tool] || '';
        if (tool === 'polygon') { map.on('click', onDrawPolygonClick); }
        else if (tool === 'rect') {
            if (isMobile) {
                map.on('click', onDrawRectClick);
            } else {
                map.on('mousedown', onDrawRectStart); map.on('mouseup', onDrawRectEnd);
            }
        }
        else if (tool === 'circle') { map.on('click', onDrawCircleClick); }
        map.on('mousemove', onDrawMouseMove);
    };

    function cancelDraw() {
        _drawMode = null; _drawPoints = []; _rectTapStep = 0;
        _tempMarkers.forEach(function (m) { getMap().removeLayer(m); }); _tempMarkers = [];
        _polyVertexMarkers.forEach(function (m) { getMap().removeLayer(m); }); _polyVertexMarkers = [];
        if (_tempPolyline) { getMap().removeLayer(_tempPolyline); _tempPolyline = null; }
        if (_livePolygon) { getMap().removeLayer(_livePolygon); _livePolygon = null; }
        var map = getMap();
        map.off('click', onDrawPolygonClick);
        map.off('mousedown', onDrawRectStart); map.off('mouseup', onDrawRectEnd);
        map.off('click', onDrawRectClick);
        map.off('click', onDrawCircleClick); map.off('mousemove', onDrawMouseMove);
        if (map) map.getContainer().style.cursor = '';
    }

    function nextShapeColor() { return _shapeColors[_drawnShapes.length % _shapeColors.length]; }

    function onDrawRectStart(e) { _rectStartLL = e.latlng; }
    function onDrawRectEnd(e) {
        if (!_rectStartLL) return;
        var p1 = _rectStartLL, p2 = e.latlng; _rectStartLL = null;
        var color = nextShapeColor();
        var layer = L.rectangle([p1, p2], { color: color, weight: 2, fillColor: color, fillOpacity: 0.15 }).addTo(getMap());
        queryAndAddShape('rect', layer, [{ lat: Math.min(p1.lat, p2.lat), lng: Math.min(p1.lng, p2.lng) }, { lat: Math.max(p1.lat, p2.lat), lng: Math.max(p1.lng, p2.lng) }]);
        cancelDraw();
    }
    // Mobile: two-tap rectangle (tap corner 1, then corner 2)
    var _rectTapStep = 0;
    function onDrawRectClick(e) {
        if (_rectTapStep === 0) {
            _rectStartLL = e.latlng; _rectTapStep = 1;
            var marker = L.circleMarker(e.latlng, { radius: 6, color: '#e74c3c', fillColor: '#e74c3c', fillOpacity: 0.8, weight: 2 });
            marker.addTo(getMap()); _tempMarkers.push(marker);
            var hint = $('v2DrawHint');
            if (hint) hint.textContent = '点击第二个对角点完成矩形';
        } else {
            var p1 = _rectStartLL, p2 = e.latlng; _rectStartLL = null; _rectTapStep = 0;
            var color = nextShapeColor();
            var layer = L.rectangle([p1, p2], { color: color, weight: 2, fillColor: color, fillOpacity: 0.15 }).addTo(getMap());
            queryAndAddShape('rect', layer, [{ lat: Math.min(p1.lat, p2.lat), lng: Math.min(p1.lng, p2.lng) }, { lat: Math.max(p1.lat, p2.lat), lng: Math.max(p1.lng, p2.lng) }]);
            cancelDraw();
            // Re-activate rect tool for quick next draw
            activateModalDrawTool('rect');
        }
    }
    function onDrawCircleClick(e) {
        if (_circleStep === 0) {
            _circleCenter = e.latlng; _circleStep = 1;
            _tempMarkers.push(L.circleMarker(_circleCenter, { radius: 4, color: '#2D6A4F', fillColor: '#2D6A4F', fillOpacity: 1 }).addTo(getMap()));
        } else {
            var radius = _circleCenter.distanceTo(e.latlng);
            var color = nextShapeColor();
            var layer = L.circle(_circleCenter, { radius: radius, color: color, weight: 2, fillColor: color, fillOpacity: 0.15 }).addTo(getMap());
            queryAndAddShape('circle', layer, [], _circleCenter.lat, _circleCenter.lng, radius);
            cancelDraw(); _circleStep = 0; _circleCenter = null;
        }
    }
    var _polyVertexMarkers = [];
    var _livePolygon = null;

    function updateLivePolygon() {
        var map = getMap();
        // Rebuild points from marker positions (they may have been dragged)
        _drawPoints = _polyVertexMarkers.map(function (m) { return m.getLatLng(); });
        if (_tempPolyline) { map.removeLayer(_tempPolyline); _tempPolyline = null; }
        if (_livePolygon) { map.removeLayer(_livePolygon); _livePolygon = null; }
        if (_drawPoints.length >= 3) {
            _livePolygon = L.polygon(_drawPoints, { color: '#2D6A4F', weight: 2, fillColor: '#2D6A4F', fillOpacity: 0.12, dashArray: '6,4' }).addTo(map);
        } else if (_drawPoints.length === 2) {
            _tempPolyline = L.polyline(_drawPoints, { color: '#2D6A4F', weight: 2, dashArray: '5,5' }).addTo(map);
        }
    }

    function onDrawPolygonClick(e) {
        var map = getMap();
        var ll = e.latlng;
        _drawPoints.push(ll);
        // Create draggable vertex marker
        var marker = L.marker(ll, {
            draggable: true,
            icon: L.divIcon({
                className: '',
                html: '<div style="width:14px;height:14px;border-radius:50%;background:#2D6A4F;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.3);cursor:grab;"></div>',
                iconSize: [14, 14],
                iconAnchor: [7, 7]
            })
        }).addTo(map);
        marker.on('drag', function () { updateLivePolygon(); });
        _polyVertexMarkers.push(marker);

        updateLivePolygon();

        // Auto-finish if >= 3 points — show finish button
        var hint = $('v2DrawHint');
        if (_drawPoints.length >= 3) {
            if (hint) hint.innerHTML = '已添加 <b>' + _drawPoints.length + '</b> 个点 · 拖动调整 · <button onclick="finishPolygonDraw()" style="background:#2D6A4F;color:#fff;border:none;border-radius:8px;padding:4px 12px;font-size:0.9em;cursor:pointer;">完成多边形</button>';
        } else {
            if (hint) hint.textContent = '已添加 ' + _drawPoints.length + ' 个点，至少需要3个';
        }
    }

    window.finishPolygonDraw = function () {
        if (_drawPoints.length < 3) { showToast('至少需要3个顶点', 'error'); return; }
        var color = nextShapeColor();
        var layer = L.polygon(_drawPoints, { color: color, weight: 2, fillColor: color, fillOpacity: 0.15 }).addTo(getMap());
        queryAndAddShape('polygon', layer, _drawPoints.map(function (ll) { return { lat: ll.lat, lng: ll.lng }; }));
        cancelDraw();
        // Re-activate polygon tool
        activateModalDrawTool('polygon');
    };
    function onDrawMouseMove(e) {
        if (_drawMode === 'circle' && _circleCenter && _circleStep === 1) {
            if (_tempPolyline) getMap().removeLayer(_tempPolyline);
            _tempPolyline = L.polyline([_circleCenter, e.latlng], { color: '#2D6A4F', weight: 2, dashArray: '5,5' }).addTo(getMap());
        }
    }

    function queryAndAddShape(type, layer, points, centerLat, centerLng, radius) {
        var id = ++_shapeIdCounter;
        var params = new URLSearchParams({ type: type, points: JSON.stringify(points) });
        if (centerLat !== undefined) params.set('center_lat', centerLat);
        if (centerLng !== undefined) params.set('center_lng', centerLng);
        if (radius !== undefined) params.set('radius', radius);
        var shape = { id: id, type: type, layer: layer, zoneCodes: [], color: layer.options.color, handles: [] };
        _drawnShapes.push(shape);
        // Add draggable handles for editing the shape
        addShapeHandles(shape);
        fetch('/api/zones-in-area/?' + params.toString())
            .then(function (r) { return r.json(); })
            .then(function (data) {
                shape.zoneCodes = data.zone_codes;
                data.zone_codes.forEach(function (code) {
                    _selectedZoneCodes.add(code);
                    if (!_selectionOverlays[code] && _selectionLayerGroup) {
                        addOverlayForCode(code);
                    }
                });
                updateInfoBarText(); renderShapeListInModal();
            });
        renderShapeListInModal();
    }

    var _handleIcon = L.divIcon({
        className: '',
        html: '<div style="width:12px;height:12px;border-radius:50%;background:#fff;border:2px solid #2D6A4F;box-shadow:0 1px 3px rgba(0,0,0,0.3);cursor:grab;"></div>',
        iconSize: [12, 12],
        iconAnchor: [6, 6]
    });

    var _centerHandleIcon = L.divIcon({
        className: '',
        html: '<div style="width:14px;height:14px;border-radius:50%;background:#2D6A4F;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.3);cursor:move;"></div>',
        iconSize: [14, 14],
        iconAnchor: [7, 7]
    });

    function addShapeHandles(shape) {
        var map = getMap();
        if (!map) return;
        if (shape.type === 'rect') {
            // Rectangle: 4 corner handles + center move handle
            var ll = shape.layer.getLatLngs()[0];
            // Corners: SW, NW, NE, SE (Leaflet polygon order)
            var corners = [ll[0], ll[1], ll[2], ll[3]];
            shape._rectCorners = corners;
            // 4 corner handles for resize
            corners.forEach(function (pt, i) {
                var handle = L.marker(pt, { draggable: true, icon: _handleIcon }).addTo(map);
                handle._cornerIdx = i;
                handle.on('drag', function () { updateRectFromCorner(shape, i, handle.getLatLng()); });
                handle.on('dragend', function () { requeryShape(shape); });
                shape.handles.push(handle);
            });
            // Center handle for move
            var bounds = shape.layer.getBounds();
            var center = bounds.getCenter();
            var centerHandle = L.marker(center, { draggable: true, icon: _centerHandleIcon }).addTo(map);
            centerHandle._isCenter = true;
            centerHandle.on('dragstart', function () {
                shape._moveStartBounds = shape.layer.getBounds();
                shape._moveStartCenter = centerHandle.getLatLng();
            });
            centerHandle.on('drag', function () {
                if (!shape._moveStartBounds) return;
                var cur = centerHandle.getLatLng();
                var dLat = cur.lat - shape._moveStartCenter.lat;
                var dLng = cur.lng - shape._moveStartCenter.lng;
                var ob = shape._moveStartBounds;
                var nb = L.latLngBounds(
                    L.latLng(ob.getSouthWest().lat + dLat, ob.getSouthWest().lng + dLng),
                    L.latLng(ob.getNorthEast().lat + dLat, ob.getNorthEast().lng + dLng)
                );
                shape.layer.setBounds(nb);
                // Move corner handles
                var newCorners = [nb.getSouthWest(), L.latLng(nb.getNorth(), nb.getWest()), nb.getNorthEast(), L.latLng(nb.getSouth(), nb.getEast())];
                shape._rectCorners = newCorners;
                for (var ci = 0; ci < 4; ci++) { shape.handles[ci].setLatLng(newCorners[ci]); }
            });
            centerHandle.on('dragend', function () { shape._moveStartBounds = null; requeryShape(shape); });
            shape.handles.push(centerHandle);
        } else if (shape.type === 'polygon') {
            var ll2 = shape.layer.getLatLngs()[0];
            ll2.forEach(function (pt, i) {
                var handle = L.marker(pt, { draggable: true, icon: _handleIcon }).addTo(map);
                handle.on('drag', function () { updateShapeFromHandle(shape); });
                handle.on('dragend', function () { updateShapeFromHandle(shape); requeryShape(shape); });
                shape.handles.push(handle);
            });
            // Center handle for move
            var bounds2 = shape.layer.getBounds();
            var center2 = bounds2.getCenter();
            var ch2 = L.marker(center2, { draggable: true, icon: _centerHandleIcon }).addTo(map);
            ch2._isCenter = true;
            ch2.on('dragstart', function () {
                shape._moveStartLL = shape.layer.getLatLngs()[0].map(function (p) { return L.latLng(p.lat, p.lng); });
                shape._moveStartCenter = ch2.getLatLng();
            });
            ch2.on('drag', function () {
                if (!shape._moveStartLL) return;
                var cur = ch2.getLatLng();
                var dLat = cur.lat - shape._moveStartCenter.lat;
                var dLng = cur.lng - shape._moveStartCenter.lng;
                var newLL = shape._moveStartLL.map(function (p) { return L.latLng(p.lat + dLat, p.lng + dLng); });
                shape.layer.setLatLngs([newLL]);
                for (var vi = 0; vi < newLL.length; vi++) { shape.handles[vi].setLatLng(newLL[vi]); }
            });
            ch2.on('dragend', function () { shape._moveStartLL = null; requeryShape(shape); });
            shape.handles.push(ch2);
        } else if (shape.type === 'circle') {
            var center3 = shape.layer.getLatLng();
            var ch3 = L.marker(center3, { draggable: true, icon: _centerHandleIcon }).addTo(map);
            ch3.on('drag', function () { shape.layer.setLatLng(ch3.getLatLng()); });
            ch3.on('dragend', function () { requeryShape(shape); });
            shape.handles.push(ch3);
            // Edge handle for radius
            var edgeLL = destinationPoint(center3.lat, center3.lng, shape.layer.getRadius(), 90);
            var eh = L.marker(edgeLL, { draggable: true, icon: _handleIcon }).addTo(map);
            eh.on('drag', function () {
                var newR = ch3.getLatLng().distanceTo(eh.getLatLng());
                shape.layer.setRadius(Math.max(10, newR));
            });
            eh.on('dragend', function () { requeryShape(shape); });
            shape.handles.push(eh);
        }
    }

    function updateRectFromCorner(shape, idx, newLL) {
        var c = shape._rectCorners.slice();
        c[idx] = newLL;
        // Opposite corner stays fixed, adjacents move along axes
        var opp = (idx + 2) % 4;
        // Rebuild rectangle: fixed opposite corner + dragged corner define the new rect
        var lat1 = c[opp].lat, lng1 = c[opp].lng;
        var lat2 = newLL.lat, lng2 = newLL.lng;
        var sw = L.latLng(Math.min(lat1, lat2), Math.min(lng1, lng2));
        var ne = L.latLng(Math.max(lat1, lat2), Math.max(lng1, lng2));
        var nw = L.latLng(ne.lat, sw.lng);
        var se = L.latLng(sw.lat, ne.lng);
        var newCorners = [sw, nw, ne, se];
        shape.layer.setLatLngs([newCorners]);
        shape._rectCorners = newCorners;
        // Update other handles (skip current idx and center)
        for (var ci = 0; ci < 4; ci++) {
            if (ci !== idx) shape.handles[ci].setLatLng(newCorners[ci]);
        }
        // Update center handle
        var centerIdx = shape.handles.length - 1;
        if (shape.handles[centerIdx]._isCenter) {
            shape.handles[centerIdx].setLatLng(L.latLngBounds(sw, ne).getCenter());
        }
    }

    function updateShapeFromHandle(shape) {
        var newLL = [];
        for (var i = 0; i < shape.handles.length; i++) {
            if (shape.handles[i]._isCenter) break;
            newLL.push(shape.handles[i].getLatLng());
        }
        shape.layer.setLatLngs([newLL]);
    }

    function destinationPoint(lat, lng, dist, bearing) {
        var R = 6371000;
        var d = dist;
        var brng = bearing * Math.PI / 180;
        var lat1 = lat * Math.PI / 180, lng1 = lng * Math.PI / 180;
        var lat2 = Math.asin(Math.sin(lat1) * Math.cos(d / R) + Math.cos(lat1) * Math.sin(d / R) * Math.cos(brng));
        var lng2 = lng1 + Math.atan2(Math.sin(brng) * Math.sin(d / R) * Math.cos(lat1), Math.cos(d / R) - Math.sin(lat1) * Math.sin(lat2));
        return L.latLng(lat2 * 180 / Math.PI, lng2 * 180 / Math.PI);
    }

    function requeryShape(shape) {
        var params;
        if (shape.type === 'circle') {
            var c = shape.layer.getLatLng();
            var r = shape.layer.getRadius();
            params = new URLSearchParams({ type: 'circle', points: '[]', center_lat: c.lat, center_lng: c.lng, radius: r });
        } else {
            var ll = shape.layer.getLatLngs()[0];
            var pts = ll.map(function (p) { return { lat: p.lat, lng: p.lng }; });
            params = new URLSearchParams({ type: shape.type, points: JSON.stringify(pts) });
        }
        fetch('/api/zones-in-area/?' + params.toString())
            .then(function (r) { return r.json(); })
            .then(function (data) { shape.zoneCodes = data.zone_codes; rebuildSelectionFromShapes(); renderShapeListInModal(); });
    }

    window.removeModalShape = function (id) {
        var idx = _drawnShapes.findIndex(function (s) { return s.id === id; });
        if (idx < 0) return;
        // Remove handles
        _drawnShapes[idx].handles.forEach(function (h) { getMap().removeLayer(h); });
        getMap().removeLayer(_drawnShapes[idx].layer);
        _drawnShapes.splice(idx, 1);
        rebuildSelectionFromShapes(); renderShapeListInModal();
    };

    function rebuildSelectionFromShapes() {
        _selectedZoneCodes.clear(); if (_selectionLayerGroup) _selectionLayerGroup.clearLayers(); _selectionOverlays = {};
        if (!_selectionLayerGroup) return;
        _drawnShapes.forEach(function (s) { s.zoneCodes.forEach(function (code) {
            _selectedZoneCodes.add(code);
            if (!_selectionOverlays[code]) {
                addOverlayForCode(code);
            }
        }); });
        updateInfoBarText();
    }

    function renderShapeListInModal() {
        var container = $('wrShapeList'); if (!container) return;
        container.innerHTML = '';
        _drawnShapes.forEach(function (s, idx) {
            var typeLabel = { rect: '矩形', circle: '圆形', polygon: '多边形' }[s.type] || s.type;
            var item = document.createElement('div');
            item.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:6px 10px;background:#f0f7f4;border-radius:6px;margin-bottom:4px;font-size:0.85em;';
            item.innerHTML = '<div style="display:flex;align-items:center;gap:6px;color:#2D6A4F;"><span style="width:10px;height:10px;border-radius:50%;background:' + s.color + ';flex-shrink:0;"></span><span>' + typeLabel + ' #' + (idx + 1) + '</span><span style="background:#2D6A4F;color:#fff;padding:1px 7px;border-radius:10px;font-size:0.85em;">' + s.zoneCodes.length + ' 区域</span></div><button type="button" onclick="removeModalShape(' + s.id + ')" style="border:none;background:none;cursor:pointer;color:#c0392b;font-size:1em;">✕</button>';
            container.appendChild(item);
        });
    }

    function buildForm(type, data) {
        if (type === 'workorder') buildWorkorderForm(data);
        else buildWaterRequestForm(data);
    }

    function buildWorkorderForm(data) {
        var body = $('woModalBody'); if (!body) return;
        var shiftChips = data.sorted_shifts.map(function (s, i) {
            return '<label class="v2-chip' + (i === 0 ? ' active' : '') + '" data-val="' + s + '"><input type="radio" name="shift" value="' + s + '" style="display:none;"' + (i === 0 ? ' checked' : '') + '>' + s + '</label>';
        }).join('');

        body.innerHTML =
            '<form id="woModalForm" style="display:contents;"><input type="hidden" name="date" value="' + data.today + '">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;"><span style="font-size:0.85em;color:#888;">' + data.today + ' ' + data.now_time + '</span><span style="font-size:0.85em;color:#888;">' + data.worker_name + '</span></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div style="flex:1.2;"><div class="v2-fl">班次</div><div class="v2-chip-group">' + shiftChips + '</div></div><div style="flex:0.8;"><div class="v2-fl">灌溉组</div><input type="number" name="team_size" value="1" min="0" max="99" class="v2-input" style="text-align:center;"></div><div style="flex:0.8;"><div class="v2-fl">第三方</div><input type="number" name="third_party_count" value="0" min="0" max="99" class="v2-input" style="text-align:center;"></div></div><div id="woHours" style="margin-top:2px;font-size:0.85em;color:#888;"></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">开始时间</div><select name="work_start_time" id="woStart" class="v2-select"><option value="">--</option></select></div><div><div class="v2-fl">完成时间</div><select name="work_end_time" id="woEnd" class="v2-select"><option value="">--</option></select></div></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div style="flex:1;"><div class="v2-fl">工作类别</div><div id="woCatTrigger" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid #ddd;border-radius:8px;cursor:pointer;background:#fff;font-size:16px;"><span id="woCatDisplay" style="color:#bbb;">选择</span><span style="font-size:0.8em;color:#999;">▶</span></div><input type="hidden" name="work_category" id="woCatInput"></div><div style="flex:1;"><div class="v2-fl">故障详情</div><div id="woFaultTrigger" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid #ddd;border-radius:8px;cursor:pointer;background:#fff;font-size:16px;"><span id="woFaultDisplay" style="color:#bbb;">选择</span><span style="font-size:0.8em;color:#999;">▶</span></div><input type="hidden" name="fault_entries" id="woFaultInput"></div></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">疑难</div><div class="v2-chip-group"><label class="v2-chip active" data-val=""><input type="radio" name="is_difficult" value="" style="display:none;" checked>否</label><label class="v2-chip" data-val="1"><input type="radio" name="is_difficult" value="1" style="display:none;">是</label></div></div><div><div class="v2-fl">已处理</div><div class="v2-chip-group"><label class="v2-chip active" data-val=""><input type="radio" name="is_difficult_resolved" value="" style="display:none;" checked>否</label><label class="v2-chip" data-val="1"><input type="radio" name="is_difficult_resolved" value="1" style="display:none;">是</label></div></div></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">工作内容</div><textarea name="work_content" class="v2-textarea" placeholder="请描述工作内容..." rows="3"></textarea></div>' +
            '<div class="v2-fg"><div class="v2-fl">照片 (最多6张)</div><div class="v2-photo-area" id="woPhotoArea"><div class="v2-photo-add" id="woPhotoAdd">+</div></div><input type="file" id="woPhotoInput" accept="image/*" multiple style="display:none;"></div>' +
            '<input type="hidden" name="remark" value=""></form>' +
            '<div id="woCatModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:4000;align-items:flex-end;justify-content:center;"><div style="background:#fff;border-radius:16px 16px 0 0;width:100%;max-width:420px;max-height:70vh;overflow-y:auto;"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px;border-bottom:1px solid #f0f0f0;"><span style="font-weight:600;">选择工作类别</span><button onclick="document.getElementById(\'woCatModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div style="padding:16px;"><div style="font-size:0.85em;color:#999;margin-bottom:6px;">主类别</div><div class="v2-chip-group" id="woCatPrimary"></div><div id="woSubcatDivider" style="display:none;border-top:1px solid #e0e0e0;margin:12px 0;"></div><div id="woSubcatLabel" style="display:none;font-size:0.85em;color:#999;margin-bottom:6px;">子类别</div><div class="v2-chip-group" id="woSubcat"></div></div><div style="padding:12px 16px;border-top:1px solid #f0f0f0;"><button onclick="document.getElementById(\'woCatModal\').style.display=\'none\'" style="width:100%;padding:12px;border:none;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">确定</button></div></div></div>' +
            '<div id="woFaultModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:4000;align-items:flex-end;justify-content:center;"><div style="background:#fff;border-radius:16px 16px 0 0;width:100%;max-width:420px;max-height:70vh;overflow-y:auto;"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px;border-bottom:1px solid #f0f0f0;"><span style="font-weight:600;">故障详情</span><button onclick="document.getElementById(\'woFaultModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div style="padding:16px;"><div style="font-size:0.85em;color:#999;margin-bottom:6px;">故障类别</div><div class="v2-chip-group" id="woFaultPrimary"></div><div id="woFaultSubDivider" style="display:none;border-top:1px solid #e0e0e0;margin:12px 0;"></div><div id="woFaultSubLabel" style="display:none;font-size:0.85em;color:#999;margin-bottom:6px;">故障子项</div><div class="v2-chip-group" id="woFaultSub"></div></div><div style="padding:12px 16px;border-top:1px solid #f0f0f0;"><button onclick="document.getElementById(\'woFaultModal\').style.display=\'none\'" style="width:100%;padding:12px;border:none;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">确定</button></div></div></div>';

        injectCSRF(body.querySelector('form'));
        initWorkorderBehaviors(data);
    }

    function initWorkorderBehaviors(data) {
        function populateTime(sel, def) {
            for (var h = 0; h < 24; h++) for (var m = 0; m < 60; m += 15) {
                var v = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
                var o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o);
            }
            if (def) sel.value = def;
        }
        var startSel = $('woStart'), endSel = $('woEnd');
        populateTime(startSel, data.default_time);
        var parts = data.default_time.split(':').map(Number), nm = parts[1] + 15, nh = parts[0];
        if (nm >= 60) { nm -= 60; nh++; } if (nh >= 24) nh = 0;
        populateTime(endSel, String(nh).padStart(2, '0') + ':' + String(nm).padStart(2, '0'));

        function calcHours() {
            var s = startSel.value, e = endSel.value;
            var ts = parseInt(document.querySelector('[name="team_size"]') ? document.querySelector('[name="team_size"]').value : 0) || 0;
            var tp = parseInt(document.querySelector('[name="third_party_count"]') ? document.querySelector('[name="third_party_count"]').value : 0) || 0;
            if (!s || !e) { $('woHours').textContent = ''; return; }
            var sh = s.split(':').map(Number), eh = e.split(':').map(Number);
            var dur = (eh[0] * 60 + eh[1]) - (sh[0] * 60 + sh[1]); if (dur <= 0) dur += 1440;
            var dh = dur / 60, th = Math.round(dh * ts * 2) / 2, tph = Math.round(dh * tp * 2) / 2;
            $('woHours').innerHTML = '工时: <span style="color:#2D6A4F;font-weight:600;">' + th + 'h</span>' + (tph > 0 ? ' / 第三方: <span style="color:#2D6A4F;font-weight:600;">' + tph + 'h</span>' : '');
        }
        startSel.addEventListener('change', calcHours); endSel.addEventListener('change', calcHours);
        document.querySelector('[name="team_size"]').addEventListener('input', calcHours);
        document.querySelector('[name="third_party_count"]').addEventListener('input', calcHours);
        calcHours();

        document.querySelectorAll('#woModalBody .v2-chip-group:first-of-type .v2-chip').forEach(function (c) {
            c.addEventListener('click', function () { c.closest('.v2-chip-group').querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); }); c.classList.add('active'); c.querySelector('input').checked = true; });
        });
        var chipGroups = document.querySelectorAll('#woModalBody .v2-chip-group');
        for (var i = 1; i < chipGroups.length; i++) { (function (group) {
            group.querySelectorAll('.v2-chip').forEach(function (c) { c.addEventListener('click', function () { group.querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); }); c.classList.add('active'); c.querySelector('input').checked = true; }); });
        })(chipGroups[i]); }

        var selectedCatId = null, catPrimary = $('woCatPrimary'), subcatGrid = $('woSubcat');
        data.category_tree.forEach(function (cat) {
            var chip = document.createElement('div'); chip.className = 'v2-chip'; chip.textContent = cat.name;
            chip.addEventListener('click', function () {
                catPrimary.querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); }); chip.classList.add('active'); subcatGrid.innerHTML = '';
                if (cat.children.length > 0) { $('woSubcatDivider').style.display = ''; $('woSubcatLabel').style.display = '';
                    cat.children.forEach(function (sub) { var sc = document.createElement('div'); sc.className = 'v2-chip'; sc.textContent = sub.name; sc.dataset.id = sub.id;
                        sc.addEventListener('click', function () { subcatGrid.querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); }); sc.classList.add('active'); selectedCatId = sub.id; });
                        subcatGrid.appendChild(sc); });
                } else { $('woSubcatDivider').style.display = 'none'; $('woSubcatLabel').style.display = 'none'; selectedCatId = cat.id; }
            }); catPrimary.appendChild(chip);
        });
        $('woCatTrigger').addEventListener('click', function () { $('woCatModal').style.display = 'flex'; });
        var catModal = $('woCatModal'), catObserver = new MutationObserver(function () {
            if (catModal.style.display === 'none') { var activeSub = subcatGrid.querySelector('.v2-chip.active');
                var catId = activeSub ? activeSub.dataset.id : (catPrimary.querySelector('.v2-chip.active') ? selectedCatId : null);
                if (catId) { $('woCatInput').value = catId; var name = '';
                    data.category_tree.forEach(function (c) { if (c.id == catId) name = c.name; c.children.forEach(function (s) { if (s.id == catId) name = s.name; }); });
                    $('woCatDisplay').textContent = name || '已选择'; $('woCatDisplay').style.color = '#222'; } }
        }); catObserver.observe(catModal, { attributes: true, attributeFilter: ['style'] });

        _faultEntries = []; var faultPrimary = $('woFaultPrimary'), faultSubGrid = $('woFaultSub');
        data.fault_tree.forEach(function (fc) {
            var chip = document.createElement('div'); chip.className = 'v2-chip'; chip.textContent = fc.name;
            chip.addEventListener('click', function () {
                faultPrimary.querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); }); chip.classList.add('active'); faultSubGrid.innerHTML = '';
                if (fc.subtypes.length > 0) { $('woFaultSubDivider').style.display = ''; $('woFaultSubLabel').style.display = '';
                    fc.subtypes.forEach(function (sub) { var sc = document.createElement('div'); sc.className = 'v2-chip'; sc.textContent = sub.name; sc.dataset.id = sub.id;
                        sc.addEventListener('click', function () {
                            if (sc.classList.contains('active')) {
                                sc.classList.remove('active');
                                var idx = _faultEntries.findIndex(function (e) { return e.fault_subtype == sub.id; });
                                if (idx >= 0) _faultEntries.splice(idx, 1);
                            } else {
                                var cnt = prompt('请输入「' + sub.name + '」的故障数量:', '1');
                                if (cnt === null) return; // cancelled
                                cnt = parseInt(cnt);
                                if (isNaN(cnt) || cnt < 1) cnt = 1;
                                sc.classList.add('active');
                                sc.textContent = sub.name + ' ×' + cnt;
                                _faultEntries.push({ fault_subtype: sub.id, count: cnt });
                            }
                            if (!sc.classList.contains('active')) sc.textContent = sub.name;
                            updateFaultDisplay(data.fault_tree);
                        }); faultSubGrid.appendChild(sc); }); }
            }); faultPrimary.appendChild(chip);
        });
        $('woFaultTrigger').addEventListener('click', function () { $('woFaultModal').style.display = 'flex'; });

        var photoArea = $('woPhotoArea'), photoInput = $('woPhotoInput');
        $('woPhotoAdd').addEventListener('click', function () { photoInput.click(); });
        photoInput.addEventListener('change', function () {
            Array.from(photoInput.files).forEach(function (f) { if (_photoFiles.length >= 6) return; _photoFiles.push(f);
                var reader = new FileReader(); reader.onload = function (e) {
                    var div = document.createElement('div'); div.className = 'v2-photo-thumb';
                    div.innerHTML = '<img src="' + e.target.result + '"><button type="button" class="v2-photo-rm">×</button>';
                    div.querySelector('.v2-photo-rm').addEventListener('click', function () { var idx = Array.from(photoArea.querySelectorAll('.v2-photo-thumb')).indexOf(div); _photoFiles.splice(idx, 1); div.remove(); $('woPhotoAdd').style.display = _photoFiles.length < 6 ? '' : 'none'; });
                    photoArea.insertBefore(div, $('woPhotoAdd')); $('woPhotoAdd').style.display = _photoFiles.length < 6 ? '' : 'none';
                }; reader.readAsDataURL(f);
            }); photoInput.value = '';
        });
    }

    function updateFaultDisplay(faultTree) {
        var display = $('woFaultDisplay');
        if (_faultEntries.length > 0) {
            display.textContent = _faultEntries.map(function (e) { var n = ''; faultTree.forEach(function (fc) { fc.subtypes.forEach(function (s) { if (s.id == e.fault_subtype) n = s.name; }); }); return n + '×' + e.count; }).join(', ');
            display.style.color = '#222';
        } else { display.textContent = '选择'; display.style.color = '#bbb'; }
        $('woFaultInput').value = JSON.stringify(_faultEntries);
    }

    function buildWaterRequestForm(data) {
        var body = $('wrModalBody'); if (!body) return;
        var typeChips = data.request_type_choices.map(function (item, i) {
            return '<div class="v2-chip modal-req-chip' + (i === 0 ? ' active' : '') + '" data-val="' + item[0] + '">' + item[1] + '</div>';
        }).join('');
        body.innerHTML = '<form id="wrModalForm" style="display:contents;"><input type="hidden" name="date" value="' + data.today + '">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;"><span style="font-size:0.85em;color:#888;">' + data.today + ' ' + data.now_time + '</span><span style="font-size:0.85em;color:#888;">' + data.user_name + '</span></div>' +
            '<div class="v2-fg"><div class="v2-fl">需求类型</div><div class="v2-chip-group">' + typeChips + '</div><input type="hidden" name="request_type" id="wrTypeInput" value="' + data.request_type_choices[0][0] + '"></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">开始时间</div><select name="start_time" id="wrStart" class="v2-select"><option value="">--</option></select></div><div><div class="v2-fl">结束时间</div><select name="end_time" id="wrEnd" class="v2-select"><option value="">--</option></select></div></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">备注</div><textarea name="remark" class="v2-textarea" placeholder="可选备注..." rows="2"></textarea></div>' +
            '<div class="v2-fg"><div class="v2-fl">已绘制区域</div><div id="wrShapeList"></div></div></form>';
        injectCSRF(body.querySelector('form'));
        // Populate time selects with 30-min intervals
        var pad = function (n) { return String(n).padStart(2, '0'); };
        function populateTime30(sel, def) {
            for (var h = 0; h < 24; h++) for (var m = 0; m < 60; m += 30) {
                var v = pad(h) + ':' + pad(m);
                var o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o);
            }
            if (def) sel.value = def;
        }
        var now = new Date();
        var curM = now.getMinutes();
        var snapM = curM < 30 ? '00' : '30';
        var defStart = pad(now.getHours()) + ':' + snapM;
        var endH = now.getHours() + 2; if (endH >= 24) endH -= 24;
        var defEnd = pad(endH) + ':' + snapM;
        populateTime30($('wrStart'), defStart);
        populateTime30($('wrEnd'), defEnd);
        document.querySelectorAll('.modal-req-chip').forEach(function (chip) {
            chip.addEventListener('click', function () { document.querySelectorAll('.modal-req-chip').forEach(function (c) { c.classList.remove('active'); }); chip.classList.add('active'); $('wrTypeInput').value = chip.dataset.val; });
        });
    }

    window.submitV2Workorder = function () {
        var codes = Array.from(_selectedZoneCodes);
        if (codes.length === 0) { showToast('请在地图上选择至少一个区域', 'error'); return; }
        var form = $('woModalForm'); if (!form) return;
        form.querySelectorAll('input[name="zones"]').forEach(function (i) { i.remove(); });
        codes.forEach(function (code) { var input = document.createElement('input'); input.type = 'hidden'; input.name = 'zones'; input.value = code; form.appendChild(input); });
        var fd = new FormData(form); _photoFiles.forEach(function (f) { fd.append('photos', f); });
        var btn = $('woSubmitBtn'); btn.disabled = true; btn.textContent = '提交中...';
        fetch('/mobile/workorder/v2/', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); }).then(function (data) {
                if (data.success) { showToast(data.message, 'success'); setTimeout(function () { closeV2Modal('workorder'); }, 1500); }
                else { showToast(data.message, 'error'); btn.disabled = false; btn.textContent = '提交'; }
            }).catch(function (err) { showToast('提交失败: ' + err, 'error'); btn.disabled = false; btn.textContent = '提交'; });
    };

    window.submitV2WaterRequest = function () {
        var codes = Array.from(_selectedZoneCodes);
        if (codes.length === 0) { showToast('请在地图上绘制选择至少一个区域', 'error'); return; }
        var startTime = $('wrStart') ? $('wrStart').value : '', endTime = $('wrEnd') ? $('wrEnd').value : '';
        if (!startTime || !endTime) { showToast('请填写需求时间段', 'error'); return; }
        var form = $('wrModalForm'), fd = form ? new FormData(form) : new FormData();
        fd.set('zone_codes', JSON.stringify(codes));
        // Combine date + time into datetime for server
        var dateVal = fd.get('date') || new Date().toISOString().split('T')[0];
        fd.set('start_datetime', dateVal + 'T' + startTime);
        fd.set('end_datetime', dateVal + 'T' + endTime);
        fd.delete('date'); fd.delete('start_time'); fd.delete('end_time');
        var btn = $('wrSubmitBtn'); btn.disabled = true; btn.textContent = '提交中...';
        fetch('/mobile/water-request/v2/', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); }).then(function (data) {
                if (data.success) { showToast(data.message, 'success'); setTimeout(function () { closeV2Modal('water_request'); }, 1500); }
                else { showToast(data.message, 'error'); btn.disabled = false; btn.textContent = '提交'; }
            }).catch(function (err) { showToast('提交失败: ' + err, 'error'); btn.disabled = false; btn.textContent = '提交'; });
    };

})();
