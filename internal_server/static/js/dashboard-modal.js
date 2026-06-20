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
    // WorkItem drill-down picker state (mobile workorder modal)
    var _woRoots = [];
    var _woProjects = [];
    var _woNodeById = {};
    var _woParentById = {};
    var _woPath = [];           // current drill-down location (stack of ids)
    var _woEntries = {};        // work_item_id -> {count,status,text_value,hasPhoto,project}
    var _woEntryPhotos = {};    // work_item_id -> [File]
    var _woProject = null;      // selected project for irrigation section
    var _woLeafTarget = null;   // node id open in the value popup
    var _woCatNode = null;      // WorkItem node selected via 工作类别 dropdowns (drill-down start/floor)
    var _woIrrCats = [];        // irrigation project categories [{code,label}] (FAM/WDI/绿化)
    var _woCanCreateProject = false;
    var _woPlanned = { checked: {}, other: '', reports: [] };  // 计划性维修: selected past 待修 reports + 其他

    // Validate a modal-data API response. Rejects error objects (e.g. {error:'无权限'})
    // so they are never cached and passed to buildForm.
    function isValidFormData(type, data) {
        if (!data || data.error) return false;
        if (type === 'workorder') return Array.isArray(data.sorted_shifts);
        return true; // water_request: no strict required arrays
    }

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
        _zoneConfirmed = false;
        resetWoZoneRecords();

        // Fetch form data in background (cached or from API)
        var dataUrl = type === 'workorder' ? '/api/modal/workorder-data/' : '/api/modal/water-request-data/';
        if (!_formDataCache[type]) {
            fetch(dataUrl, { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (isValidFormData(type, data)) _formDataCache[type] = data;
                })
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
        resetWoZoneRecords();
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
                .then(function (data) {
                    if (!isValidFormData('workorder', data)) {
                        // Surface API errors (e.g. 无权限) instead of building a broken form
                        _currentModal = null;
                        _zoneConfirmed = false;
                        _selectedZoneCodes.clear();
                        showToast(data && data.error ? data.error : '加载表单失败', 'error');
                        return;
                    }
                    _formDataCache.workorder = data;
                    showForm();
                })
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

        if (type === 'workorder') {
            enableTapSelect();
            showWoSelectBar();
        } else {
            showDrawToolBar();
        }
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
        if (_formDataCache[type] && isValidFormData(type, _formDataCache[type])) {
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
        var woSelectBar = $('v2WoSelectBar');
        if (woSelectBar) woSelectBar.style.display = 'none';
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

    function renderZoneSummary() {
        var type = _currentModal || 'workorder';
        var el = $(type === 'workorder' ? 'woZoneSummary' : 'wrZoneSummary');
        if (!el) return;
        var codes = Array.from(_selectedZoneCodes);
        if (codes.length === 0) { el.innerHTML = '<h2>' + (type === 'workorder' ? '工作记录' : '浇水需求') + '</h2>'; return; }
        // Only show the count — listing every selected zone name overflowed the header
        // when many zones were picked. The full selection is still visible on the map.
        el.innerHTML = '<h2>' + (type === 'workorder' ? '工作记录' : '浇水需求') +
            ' <span style="font-size:0.7em;font-weight:500;color:#2D6A4F;">已选 ' + codes.length + ' 个区域</span></h2>';
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

    // ── Workorder zone selection bar: search / common-name multiselect / map ──
    var _woSearchBound = false;
    var _woNameChipsBuilt = false;

    // Source of truth for all zones: prefer the global zonesData list (has every zone,
    // including boundary-less ones), fall back to the map layer group. Returns array of
    // {code, name, land_id, land_name}. Built once per modal session and cached — the zone
    // set is static for a page load, so rescanning 2510 zones on every helper call would be
    // wasteful (buildWoNameChips alone used to do ~120k iterations via per-chip rescans).
    var _woZoneRecords = null;
    function getWoZoneRecords() {
        if (_woZoneRecords) return _woZoneRecords;
        var out = [];
        if (window.zonesData && Array.isArray(window.zonesData)) {
            window.zonesData.forEach(function (z) {
                if (z && z.code) out.push({ code: z.code, name: z.name || '', land_id: z.land_id || null, land_name: z.land_name || '' });
            });
        } else {
            var zl = window._dashboardZonesLayer;
            if (zl) zl.eachLayer(function (l) {
                if (l.zoneData && l.zoneData.code) out.push({ code: l.zoneData.code, name: l.zoneData.name || '', land_id: null, land_name: '' });
            });
        }
        _woZoneRecords = out;
        return out;
    }

    // Invalidate the cache when a new modal session starts (zonesData could in principle
    // differ across sessions if the page reloads partial data).
    function resetWoZoneRecords() { _woZoneRecords = null; }

    function showWoSelectBar() {
        var bar = $('v2WoSelectBar'); if (bar) bar.style.display = '';
        // Default to the search tab on each entry
        switchWoSelectTab('search');
        // Wire the search input once
        if (!_woSearchBound) {
            _woSearchBound = true;
            var input = $('woZoneSearchInput');
            if (input) input.addEventListener('input', function () { renderWoSearchResults(); });
        }
        renderWoSearchResults();
    }

    window.switchWoSelectTab = function (tab) {
        document.querySelectorAll('#v2WoSelectBar .v2-draw-tab').forEach(function (t) {
            t.classList.toggle('active', t.dataset.tab === tab);
        });
        $('woTabSearch').classList.toggle('active', tab === 'search');
        $('woTabName').classList.toggle('active', tab === 'name');
        $('woTabMap').classList.toggle('active', tab === 'map');
        if (tab === 'name') buildWoNameChips();
        if (tab === 'search') renderWoSearchResults();
    };

    // ── Search tab ──
    // Natural (numeric-aware) comparison so "1-1-2" < "1-1-10".
    function naturalCompare(a, b) {
        var ax = [], bx = [];
        a.replace(/(\d+)|(\D+)/g, function (_, $1, $2) { ax.push([$1 ? Infinity : -Infinity, $1 ? parseInt($1, 10) : $2.toLowerCase()]); });
        b.replace(/(\d+)|(\D+)/g, function (_, $1, $2) { bx.push([$1 ? Infinity : -Infinity, $1 ? parseInt($1, 10) : $2.toLowerCase()]); });
        while (ax.length && bx.length) {
            var an = ax.shift(), bn = bx.shift();
            if (an[0] !== bn[0]) return an[0] - bn[0];      // number vs string: numbers sort first
            if (an[1] !== bn[1]) return an[1] < bn[1] ? -1 : 1;
        }
        return ax.length - bx.length;
    }

    // Match priority: 0 = exact code, 1 = code starts-with, 2 = code contains,
    //                 3 = name exact, 4 = name starts-with, 5 = name contains.
    // Lower is better (shows first).
    function matchRank(z, q) {
        var code = (z.code || '').toLowerCase();
        var name = (z.name || '').toLowerCase();
        if (code === q) return 0;
        if (code.indexOf(q) === 0) return 1;
        if (code.indexOf(q) !== -1) return 2;
        if (name && name === q) return 3;
        if (name && name.indexOf(q) === 0) return 4;
        if (name && name.indexOf(q) !== -1) return 5;
        return -1; // no match
    }

    function renderWoSearchResults() {
        var container = $('woZoneSearchResults');
        if (!container) return;
        var input = $('woZoneSearchInput');
        var q = (input && input.value || '').trim().toLowerCase();
        var all = getWoZoneRecords();
        var matches;
        if (!q) {
            // No query: list all, natural-sorted by code
            matches = all.slice().sort(function (a, b) { return naturalCompare(a.code, b.code); });
        } else {
            matches = all.map(function (z) {
                return { z: z, rank: matchRank(z, q) };
            }).filter(function (m) { return m.rank >= 0; })
              .sort(function (a, b) {
                  if (a.rank !== b.rank) return a.rank - b.rank;
                  return naturalCompare(a.z.code, b.z.code);
              }).map(function (m) { return m.z; });
        }
        if (matches.length === 0) {
            container.innerHTML = '<div class="wo-zone-search-empty">未找到匹配的区域</div>';
            return;
        }
        container.innerHTML = '';
        matches.forEach(function (z) {
            var selected = _selectedZoneCodes.has(z.code);
            var item = document.createElement('div');
            item.className = 'wo-zone-search-item' + (selected ? ' selected' : '');
            item.innerHTML =
                '<span><span class="wo-zs-code">' + z.code + '</span>' +
                (z.name ? '<span class="wo-zs-name">' + z.name + '</span>' : '') + '</span>' +
                '<span class="wo-zs-check">' + (selected ? '✓' : '') + '</span>';
            item.addEventListener('click', function () {
                toggleWoZone(z.code, ! _selectedZoneCodes.has(z.code));
                renderWoSearchResults();
                // keep name chips in sync if built
                syncWoNameChipsState();
            });
            container.appendChild(item);
        });
    }

    // ── Common-name multiselect tab (2-level: Land → 通用名称 within that Land) ──
    // Level 1 lists every Land (所属Land). Tapping one opens a bottom-sheet popup
    // (level 2) showing the distinct zone 通用名称 inside that Land, each selectable.
    // After the popup closes the user is back on the tab and can pick another Land, or
    // switch to the search / map tabs — selections accumulate in _selectedZoneCodes.
    function getWoLands() {
        // Build {id,name,zoneCount,nameCount} for lands that contain named zones.
        // nameCount = number of DISTINCT 通用名称 in the land — used to decide whether
        // tapping the land needs a level-2 popup (nameCount > 1) or can toggle directly.
        var landMap = {};
        var order = [];
        getWoZoneRecords().forEach(function (z) {
            if (z.land_id == null || !z.land_name) return;
            if (!landMap[z.land_id]) {
                landMap[z.land_id] = { id: z.land_id, name: z.land_name, zoneCount: 0, names: {} };
                order.push(z.land_id);
            }
            var L = landMap[z.land_id];
            L.zoneCount++;
            if (z.name && !L.names[z.name]) L.names[z.name] = true;
        });
        var lands = order.map(function (id) {
            var L = landMap[id];
            return { id: L.id, name: L.name, zoneCount: L.zoneCount, nameCount: Object.keys(L.names).length };
        });
        lands.sort(function (a, b) { return a.name.localeCompare(b.name, 'zh'); });
        return lands;
    }

    function getWoNamesForLand(landId) {
        var seen = {}, names = [];
        getWoZoneRecords().forEach(function (z) {
            if (z.land_id !== landId) return;
            if (!z.name) return;
            if (!seen[z.name]) { seen[z.name] = true; names.push(z.name); }
        });
        names.sort(function (a, b) { return a.localeCompare(b, 'zh'); });
        return names;
    }

    function buildWoNameChips() {
        var container = $('woNameChips');
        if (!container) return;
        var lands = getWoLands();
        container.innerHTML = '';
        if (lands.length === 0) {
            container.innerHTML = '<div style="font-size:0.85em;color:#aaa;padding:8px;">无所属Land数据</div>';
            return;
        }
        var hint = document.createElement('div');
        hint.style.cssText = 'font-size:0.78em;color:#999;width:100%;margin-bottom:4px;';
        hint.textContent = '点击Land选择其中的通用名称';
        container.appendChild(hint);
        lands.forEach(function (land) {
            var chip = document.createElement('div');
            chip.className = 'v2-chip';
            chip.style.cssText = 'font-size:0.85em;padding:5px 10px;';
            setWoLandChipState(chip, land.id);
            var label = document.createElement('span');
            label.textContent = land.name;
            chip.appendChild(label);
            // Badge: only meaningful when there is more than one name to disambiguate.
            if (land.nameCount > 1) {
                var badge = document.createElement('span');
                badge.style.cssText = 'margin-left:5px;font-size:0.8em;color:#aaa;';
                badge.textContent = '(' + land.nameCount + ')';
                chip.appendChild(badge);
            }
            chip.dataset.landId = land.id;
            chip.addEventListener('click', function () {
                // Single-name land: no level-2 popup needed — toggle that one name directly,
                // behaving like a flat chip (same as the level-1 interaction).
                if (land.nameCount <= 1) {
                    // If anything in this land is selected, clear all of it; otherwise select all.
                    var select = !isWoLandPartiallySelected(land.id);
                    selectZonesByLand(land.id, select);
                    setWoLandChipState(chip, land.id);
                    updateInfoBarText();
                } else {
                    openWoLandNamePopup(land);
                }
            });
            container.appendChild(chip);
        });
    }

    function ensureWoLandNamePopup() {
        // Lazily create the shared bottom-sheet popup for picking names within a land.
        if ($('woLandNamePopup')) return $('woLandNamePopup');
        var overlay = document.createElement('div');
        overlay.id = 'woLandNamePopup';
        overlay.className = 'v2-sheet-overlay';
        overlay.style.zIndex = 4150;
        overlay.innerHTML =
            '<div class="v2-sheet">' +
              '<div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div>' +
              '<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f0f0f0;flex-shrink:0;">' +
                '<span id="woLandNameTitle" style="font-weight:600;"></span>' +
                '<button type="button" id="woLandNameClose" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button>' +
              '</div>' +
              // Use the same flowing chip-group layout as the level-1 tab (flex-wrap) so the
              // 通用名称 chips arrange themselves across rows instead of one-per-line.
              '<div id="woLandNameBody" class="v2-chip-group" style="gap:6px;flex-wrap:wrap;padding:12px 16px;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;flex:1;min-height:0;align-content:flex-start;"></div>' +
              '<div style="padding:12px 16px;border-top:1px solid #f0f0f0;display:flex;gap:10px;flex-shrink:0;">' +
                '<button type="button" id="woLandNameAll" style="flex:1;padding:12px;border:1px solid #2D6A4F;border-radius:10px;font-size:0.92em;font-weight:600;cursor:pointer;background:#fff;color:#2D6A4F;">全选</button>' +
                '<button type="button" id="woLandNameDone" style="flex:1;padding:12px;border:none;border-radius:10px;font-size:0.92em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">完成</button>' +
              '</div>' +
            '</div>';
        document.body.appendChild(overlay);
        overlay.querySelector('#woLandNameClose').addEventListener('click', function () { closeWoLandNamePopup(); });
        overlay.querySelector('#woLandNameDone').addEventListener('click', function () { closeWoLandNamePopup(); });
        return overlay;
    }

    function openWoLandNamePopup(land) {
        var overlay = ensureWoLandNamePopup();
        $('woLandNameTitle').textContent = land.name + ' · 通用名称';
        var body = $('woLandNameBody');
        var names = getWoNamesForLand(land.id);
        body.innerHTML = '';
        if (names.length === 0) {
            body.innerHTML = '<div style="font-size:0.85em;color:#aaa;padding:8px;">该Land下无通用名称</div>';
        }
        names.forEach(function (nm) {
            var chip = document.createElement('div');
            chip.className = 'v2-chip' + (isWoNameSelectedInLand(nm, land.id) ? ' active' : '');
            chip.style.cssText = 'font-size:0.85em;padding:5px 10px;';
            chip.textContent = nm;
            chip.dataset.name = nm;
            chip.addEventListener('click', function () {
                // Land-scoped: only toggle this name's zones WITHIN this land.
                var select = !isWoNameSelectedInLand(nm, land.id);
                selectZonesByNameInLand(nm, land.id, select);
                chip.classList.toggle('active', select);
                // The "全选" state depends on every name in this land being selected.
                allBtn.textContent = isWoLandFullySelected(land.id) ? '清除' : '全选';
                updateInfoBarText();
            });
            body.appendChild(chip);
        });
        // "全选" toggles every zone belonging to this land (across all its names).
        var allBtn = $('woLandNameAll');
        allBtn.onclick = function () {
            var selectAll = !isWoLandFullySelected(land.id);
            selectZonesByLand(land.id, selectAll);
            allBtn.textContent = selectAll ? '清除' : '全选';
            // Refresh per-name chip states inside the popup (land-scoped).
            body.querySelectorAll('.v2-chip[data-name]').forEach(function (c) {
                c.classList.toggle('active', isWoNameSelectedInLand(c.dataset.name, land.id));
            });
            updateInfoBarText();
        };
        allBtn.textContent = isWoLandFullySelected(land.id) ? '清除' : '全选';
        overlay.style.display = 'flex';
    }

    function closeWoLandNamePopup() {
        var overlay = $('woLandNamePopup');
        if (overlay) overlay.style.display = 'none';
        // Keep the underlying tab's land chips in sync with the new selection.
        syncWoNameChipsState();
    }

    // Refresh active state of the level-1 land chips after selection changes elsewhere
    // (e.g. picks made in the search tab or a land's name popup). Three visual states:
    //   none selected  → no class
    //   some selected  → .partial  (light green)
    //   all selected   → .active   (solid green)
    function setWoLandChipState(chip, landId) {
        // One pass over this land's zones (countWoZones) instead of two separate
        // fully/partially scans, since both only need matching vs. selected counts.
        var c = countWoZones(function (z) { return z.land_id === landId; });
        var full = c.matching > 0 && c.selected === c.matching;
        var any = c.selected > 0 && c.selected < c.matching;
        chip.classList.toggle('active', full);
        chip.classList.toggle('partial', any);
    }

    function syncWoNameChipsState() {
        document.querySelectorAll('#woNameChips .v2-chip[data-land-id]').forEach(function (chip) {
            setWoLandChipState(chip, parseInt(chip.dataset.landId, 10));
        });
    }

    // ── Selection query/update helpers ──
    // All operate over the cached zone records and the live _selectedZoneCodes set.
    // A single pass over the records answers "how many matching zones are selected",
    // which is enough to derive fully/partially/none for any group (name-in-land, whole land).

    // Count {matching, selected} for zones satisfying `pred`. matching = total zones in the
    // group, selected = how many of those are currently in _selectedZoneCodes.
    function countWoZones(pred) {
        var matching = 0, selected = 0;
        getWoZoneRecords().forEach(function (z) {
            if (!pred(z)) return;
            matching++;
            if (_selectedZoneCodes.has(z.code)) selected++;
        });
        return { matching: matching, selected: selected };
    }

    // Select/deselect every zone whose record matches `pred` (e.g. by name or land).
    // Works for boundary-less zones too: the overlay is added only if the polygon exists.
    function selectZonesWhere(pred, selected) {
        getWoZoneRecords().forEach(function (z) {
            if (!pred(z)) return;
            var code = z.code;
            if (selected) {
                _selectedZoneCodes.add(code);
                if (!_selectionOverlays[code] && _selectionLayerGroup) addOverlayForCode(code);
            } else {
                _selectedZoneCodes.delete(code);
                removeSelectionOverlay(code);
            }
        });
    }

    // Land-scoped name selection. A 通用名称 can appear under several Lands; the level-2
    // popup is about ONE Land, so its per-name chips and "全选" must consider only that
    // Land's zones (else "全选" disagrees with per-name chips, see git history).
    function isWoNameSelectedInLand(name, landId) {
        var c = countWoZones(function (z) { return z.land_id === landId && z.name === name; });
        return c.matching > 0 && c.selected === c.matching;
    }
    function selectZonesByNameInLand(name, landId, selected) {
        selectZonesWhere(function (z) { return z.land_id === landId && z.name === name; }, selected);
    }

    function selectZonesByLand(landId, selected) {
        selectZonesWhere(function (z) { return z.land_id != null && z.land_id === landId; }, selected);
    }

    // Whole-land selection state, derived from one counting pass each.
    function isWoLandFullySelected(landId) {
        var c = countWoZones(function (z) { return z.land_id === landId; });
        return c.matching > 0 && c.selected === c.matching;
    }
    function isWoLandPartiallySelected(landId) {
        var c = countWoZones(function (z) { return z.land_id === landId; });
        return c.selected > 0 && c.selected < c.matching;
    }

    // Toggle a single zone code selection + overlay (shared by search list & map)
    function toggleWoZone(code, select) {
        if (select) {
            _selectedZoneCodes.add(code);
            if (!_selectionOverlays[code] && _selectionLayerGroup) addOverlayForCode(code);
        } else {
            _selectedZoneCodes.delete(code);
            removeSelectionOverlay(code);
        }
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

    // Compress a photo File via <canvas>: resize so the longest side ≤ maxSize, re-encode
    // as JPEG at `quality`. Returns a Promise<File> (or null if it can't/shouldn't compress,
    // e.g. tiny files where compression would only lose quality). This runs entirely
    // client-side so the uploaded payload is much smaller — submissions are far faster on
    // a slow/cloud-tunnel link.
    function compressPhoto(file, maxSize, quality) {
        if (!file.type || !file.type.startsWith('image/')) return Promise.resolve(null);
        return new Promise(function (resolve) {
            var img = new Image();
            var url = URL.createObjectURL(file);
            img.onload = function () {
                URL.revokeObjectURL(url);
                var w = img.naturalWidth, h = img.naturalHeight;
                // Skip if already small enough.
                if (w <= maxSize && h <= maxSize && file.size < 500000) { resolve(null); return; }
                var scale = Math.min(1, maxSize / Math.max(w, h));
                var cw = Math.round(w * scale), ch = Math.round(h * scale);
                var canvas = document.createElement('canvas');
                canvas.width = cw; canvas.height = ch;
                var ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, cw, ch);
                canvas.toBlob(function (blob) {
                    if (!blob) { resolve(null); return; }
                    var name = (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg';
                    resolve(new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() }));
                }, 'image/jpeg', quality);
            };
            img.onerror = function () { URL.revokeObjectURL(url); resolve(null); };
            img.src = url;
        });
    }

    function buildWorkorderForm(data) {
        var body = $('woModalBody'); if (!body) return;
        if (!data || !Array.isArray(data.sorted_shifts) || data.sorted_shifts.length === 0) {
            // Fallback when modal data is malformed/missing (e.g. API returned an error)
            data = Object.assign({
                sorted_shifts: ['早班', '白班', '夜班'],
                today: '', now_time: '', default_time: '', worker_name: '',
                work_tree: [], projects: []
            }, data || {});
        }
        var shiftChips = data.sorted_shifts.map(function (s, i) {
            return '<div class="v2-chip' + (i === 0 ? ' active' : '') + '" data-val="' + s + '"><input type="radio" name="shift" value="' + s + '" style="display:none;"' + (i === 0 ? ' checked' : '') + '>' + s + '</div>';
        }).join('');

        body.innerHTML =
            '<form id="woModalForm" style="display:contents;"><input type="hidden" name="date" value="' + data.today + '">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;"><span style="font-size:0.85em;color:#888;">' + data.today + ' ' + data.now_time + '</span><span style="font-size:0.85em;color:#888;">' + data.worker_name + '</span></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div style="flex:1.2;"><div class="v2-fl">班次</div><div class="v2-chip-group">' + shiftChips + '</div></div><div style="flex:0.8;"><div class="v2-fl">灌溉组</div><input type="number" name="team_size" value="1" min="0" max="99" class="v2-input" style="text-align:center;"></div><div style="flex:0.8;"><div class="v2-fl">第三方</div><input type="number" name="third_party_count" value="0" min="0" max="99" class="v2-input" style="text-align:center;"></div></div><div id="woHours" style="margin-top:2px;font-size:0.85em;color:#888;"></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">开始时间</div><select name="work_start_time" id="woStart" class="v2-select"><option value="">--</option></select></div><div><div class="v2-fl">完成时间</div><select name="work_end_time" id="woEnd" class="v2-select"><option value="">--</option></select></div></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">工作类别</div><div id="woCatTrigger" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid #ddd;border-radius:8px;cursor:pointer;background:#fff;font-size:16px;"><span id="woCatDisplay" style="color:#bbb;">选择</span><span style="font-size:0.8em;color:#999;">▶</span></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">工作内容</div><div id="woContentTrigger" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid #ddd;border-radius:8px;cursor:pointer;background:#fff;font-size:16px;"><span id="woContentDisplay" style="color:#bbb;">选择</span><span style="font-size:0.8em;color:#999;">▶</span></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div style="flex:0.8;"><div class="v2-fl">待修</div><div class="v2-chip-group"><div class="v2-chip active" data-val=""><input type="radio" name="is_pending_repair" value="" style="display:none;" checked>否</div><div class="v2-chip" data-val="1"><input type="radio" name="is_pending_repair" value="1" style="display:none;">是</div></div></div><div style="flex:1.2;"><div class="v2-fl">疑难</div><div class="v2-chip-group"><div class="v2-chip active" data-val=""><input type="radio" name="is_difficult" value="" style="display:none;" checked>否</div><div class="v2-chip" data-val="1"><input type="radio" name="is_difficult" value="1" style="display:none;">是</div></div></div><div><div class="v2-fl">已处理</div><div class="v2-chip-group"><div class="v2-chip active" data-val=""><input type="radio" name="is_difficult_resolved" value="" style="display:none;" checked>否</div><div class="v2-chip" data-val="1"><input type="radio" name="is_difficult_resolved" value="1" style="display:none;">是</div></div></div></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">备注</div><textarea name="remark" class="v2-textarea" placeholder="可选备注..." rows="2"></textarea></div>' +
            '<div class="v2-fg"><div class="v2-fl">照片/视频 (最多6个)</div><div class="v2-photo-area" id="woPhotoArea"><div class="v2-photo-add v2-photo-camera" id="woPhotoCamera" title="拍摄">📷</div><div class="v2-photo-add" id="woPhotoAdd" title="从相册选择">+</div></div><input type="file" id="woPhotoInput" accept="image/*,video/*" multiple style="display:none;"><input type="file" id="woPhotoCameraInput" accept="image/*,video/*" capture="environment" style="display:none;"></div>' +
            '<input type="hidden" name="entries" id="woEntriesInput" value="[]"><input type="hidden" name="pm_resolved" id="woPmResolved" value=""></form>' +
            '<div id="woCatModal" class="v2-sheet-overlay"><div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px;border-bottom:1px solid #f0f0f0;flex-shrink:0;"><span style="font-weight:600;">选择工作类别</span><button type="button" onclick="document.getElementById(\'woCatModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div style="padding:16px;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;flex:1;min-height:0;"><div style="font-size:0.85em;color:#999;margin-bottom:6px;">类别</div><div class="v2-chip-group" id="woCatPrimary"></div><div id="woCatSubDivider" style="display:none;border-top:1px solid #e0e0e0;margin:12px 0;"></div><div id="woCatSubLabel" style="display:none;font-size:0.85em;color:#999;margin-bottom:6px;">子类别</div><div class="v2-chip-group" id="woCatSub"></div></div></div></div>' +
            '<div id="woTreeModal" class="v2-sheet-overlay"><div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f0f0f0;flex-shrink:0;"><span style="font-weight:600;">工作内容</span><button type="button" onclick="document.getElementById(\'woTreeModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div id="woBreadcrumb" class="v2-wo-bc"></div><div id="woSheetBody" style="flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;padding:8px 16px;min-height:0;"></div><div style="padding:12px 16px;border-top:1px solid #f0f0f0;flex-shrink:0;"><button type="button" onclick="document.getElementById(\'woTreeModal\').style.display=\'none\'" style="width:100%;padding:12px;border:none;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">完成</button></div></div></div>' +
            '<div id="woLeafModal" class="v2-sheet-overlay" style="z-index:4100;"><div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f0f0f0;flex-shrink:0;"><span id="woLeafTitle" style="font-weight:600;"></span><button type="button" onclick="document.getElementById(\'woLeafModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div id="woLeafBody" style="padding:16px;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;flex:1;min-height:0;"></div><div style="padding:12px 16px;border-top:1px solid #f0f0f0;display:flex;gap:10px;flex-shrink:0;"><button type="button" onclick="document.getElementById(\'woLeafModal\').style.display=\'none\'" style="flex:1;padding:12px;border:1px solid #2D6A4F;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#fff;color:#2D6A4F;">取消</button><button type="button" id="woLeafConfirmBtn" style="flex:1;padding:12px;border:none;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">确定</button></div></div></div>';

        // Move the bottom-sheet popups to <body> so they escape the modal container's
        // `transform`. On iOS Safari a transformed ancestor turns position:fixed into
        // position:absolute (relative to that ancestor), so sheets nested in the modal
        // got clipped at the top and overlapped by the modal footer (提交/修改区域).
        ['woCatModal', 'woTreeModal', 'woLeafModal'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el && el.parentNode !== document.body) document.body.appendChild(el);
        });

        injectCSRF(body.querySelector('form'));
        initWorkorderBehaviors(data);
        var sb = $('woSubmitBtn'); if (sb) { sb.disabled = false; sb.textContent = '提交'; }
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

        document.querySelectorAll('#woModalForm .v2-chip-group .v2-chip').forEach(function (c) {
            c.addEventListener('click', function () { c.closest('.v2-chip-group').querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); }); c.classList.add('active'); var inp = c.querySelector('input'); if (inp) inp.checked = true; if (inp && inp.name === 'is_pending_repair') { syncDifficultChips(); clearPendingRepairLeaves(); } });
        });

        // Work-content drill-down picker (replaces the old fault chips).
        indexWorkTree(data.work_tree || []);
        _woProjects = data.projects || [];
        _woIrrCats = data.irrigation_subcategories || [];
        _woCanCreateProject = !!data.can_create_project;
        resetWoState();
        updateWoTrigger();
        // 工作类别: cascading sheet — level-1 chips first; selecting one reveals the next level below.
        // 灌溉项目 is special: 灌溉项目 → FAM/WDI/绿化 → 项目名称 (from DB, or create).
        var catTrigger = $('woCatTrigger'), catModal = $('woCatModal');
        var catPrimary = $('woCatPrimary'), catSub = $('woCatSub');
        function setCatSub(label, items) {
            $('woCatSubLabel').textContent = label;
            $('woCatSubLabel').style.display = '';
            $('woCatSubDivider').style.display = '';
            catSub.innerHTML = '';
            items.forEach(function (it) {
                var c = document.createElement('div'); c.className = 'v2-chip'; c.textContent = it.label;
                c.addEventListener('click', it.onClick);
                catSub.appendChild(c);
            });
        }
        function closeCatModal() { if (catModal) catModal.style.display = 'none'; }
        // Clear 工作内容 selections (counts/toggles/planned) — used when the category or
        // project changes, since prior selections belong to a different subtree/scope.
        function clearWoContent() {
            _woEntries = {}; _woEntryPhotos = {};
            _woPlanned = { checked: {}, other: '', reports: [] };
            updateWoTrigger();
        }
        // Show/hide the 工作内容 row (hide when the selected category has nothing to drill).
        function setContentVisible(show) {
            var trig = $('woContentTrigger');
            var row = trig ? trig.closest('.v2-fg') : null;
            if (row) row.style.display = show ? '' : 'none';
        }
        function pickWoCategory(root, sub) {
            var prevCat = _woCatNode;
            _woProject = null;                       // non-project: no project binding
            _woCatNode = sub ? sub.id : root.id;
            if (prevCat && prevCat !== _woCatNode) clearWoContent();
            var node = sub || root;
            setContentVisible(!!(node.children && node.children.length));
            // Auto-fill a lone toggle leaf (e.g., 培训记录上传) — skip free-text placeholders.
            var kids = node.children || [];
            if (kids.length === 1 && kids[0].value_type === 'toggle' && kids[0].name.indexOf('填写') < 0) {
                var only = kids[0];
                if (!_woEntries[only.id]) {
                    _woEntries[only.id] = { count: 0, status: only.name, text_value: '', hasPhoto: false, project: null };
                    updateWoTrigger();
                }
            }
            var d = $('woCatDisplay');
            if (d) { d.textContent = sub ? (root.name + ' › ' + sub.name) : root.name; d.style.color = '#222'; }
            closeCatModal();
        }
        var PROJECT_TOP = { irrigation_project: 'IRRIGATION', drainage_project: 'DRAINAGE', other_project: 'OTHER' };
        function pickWoProject(root, subLabel, project) {
            var prevCat = _woCatNode, prevProj = _woProject;
            _woCatNode = root.id;
            _woProject = project.id;
            if ((prevCat && prevCat !== _woCatNode) || (prevProj && prevProj !== _woProject)) clearWoContent();
            setContentVisible(true);                 // project sections always have the template
            var d = $('woCatDisplay');
            if (d) { d.textContent = root.name + (subLabel ? ' › ' + subLabel : '') + ' › ' + project.name; d.style.color = '#222'; }
            closeCatModal();
        }
        function showProjectsFor(root, top, sub, subLabel) {
            var items = _woProjects.filter(function (p) {
                if (p.category !== top) return false;
                return top === 'IRRIGATION' ? p.subcategory === sub : !p.subcategory;
            }).map(function (p) {
                return { label: p.name + (p.symbol ? ' · ' + p.symbol : ''), onClick: function () { pickWoProject(root, subLabel, p); } };
            });
            if (_woCanCreateProject) items.push({ label: '＋ 新建项目', onClick: function () { createProject(root, top, sub, subLabel); } });
            setCatSub(subLabel ? ('项目名称（' + subLabel + '）') : '项目名称', items.length ? items : [{ label: '（暂无项目）', onClick: function () {} }]);
        }
        function createProject(root, top, sub, subLabel) {
            var name = prompt('请输入项目名称：');
            if (!name || !name.trim()) return;
            fetch('/api/irrigation-project/create/', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCSRFToken() },
                body: JSON.stringify({ name: name.trim(), category: top, subcategory: sub })
            }).then(function (r) { return r.json(); }).then(function (data) {
                if (data.error) { showToast(data.error, 'error'); return; }
                _woProjects.push(data);
                pickWoProject(root, subLabel, { id: data.id, name: data.name });
            }).catch(function () { showToast('创建项目失败', 'error'); });
        }
        if (catPrimary) {
            // Custom display order for 工作类别 (3 per row): the rest appended after.
            var CAT_ORDER = ['routine_maint', 'routine_support', 'repair_emergency',
                'irrigation_project', 'drainage_project', 'other_project',
                'meeting_training', 'warehouse', 'typhoon_emergency',
                'greenhouse_nursery', 'safety_incident', 'good_deed'];
            var orderedCats = _woRoots.slice().sort(function (a, b) {
                var ia = CAT_ORDER.indexOf(a.section), ib = CAT_ORDER.indexOf(b.section);
                return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
            });
            orderedCats.forEach(function (r) {
                var chip = document.createElement('div'); chip.className = 'v2-chip'; chip.textContent = r.name;
                chip.addEventListener('click', function () {
                    catPrimary.querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); });
                    chip.classList.add('active');
                    catSub.innerHTML = '';
                    var topCat = PROJECT_TOP[r.section];
                    if (topCat) {
                        if (r.section === 'irrigation_project') {
                            setCatSub('项目类别', _woIrrCats.map(function (sc) {
                                return { label: sc.label, onClick: function () { showProjectsFor(r, topCat, sc.code, sc.label); } };
                            }));
                        } else {
                            showProjectsFor(r, topCat, '', '');
                        }
                    } else {
                        var kids = (r.children && r.children.length) ? r.children : null;
                        if (kids) {
                            setCatSub('子类别', kids.map(function (c) { return { label: c.name, onClick: function () { pickWoCategory(r, c); } }; }));
                        } else {
                            $('woCatSubDivider').style.display = 'none';
                            $('woCatSubLabel').style.display = 'none';
                            pickWoCategory(r, null);
                        }
                    }
                });
                catPrimary.appendChild(chip);
            });
        }
        if (catTrigger && catModal) catTrigger.addEventListener('click', function () { catModal.style.display = 'flex'; });
        // Default 工作类别 to 常规维护 › 维保定期检查 (the most common type).
        (function defaultCategory() {
            var rmRoot = null;
            for (var i = 0; i < _woRoots.length; i++) { if (_woRoots[i].section === 'routine_maint') { rmRoot = _woRoots[i]; break; } }
            var sub = null;
            if (rmRoot && rmRoot.children) {
                for (var j = 0; j < rmRoot.children.length; j++) { if (rmRoot.children[j].name === '维保定期检查') { sub = rmRoot.children[j]; break; } }
            }
            if (sub) {
                _woCatNode = sub.id; _woProject = null;
                var dd = $('woCatDisplay');
                if (dd) { dd.textContent = rmRoot.name + ' › ' + sub.name; dd.style.color = '#222'; }
                setContentVisible(true);
            }
        })();
        var contentTrigger = $('woContentTrigger');
        if (contentTrigger) contentTrigger.addEventListener('click', openWoSheet);
        var leafConfirm = $('woLeafConfirmBtn');
        if (leafConfirm) leafConfirm.addEventListener('click', confirmWoLeaf);

        // Photo upload: a 📷 button (input[capture] → opens device camera on mobile) and
        // a + button (gallery / file picker). Both feed the same _photoFiles list and
        // thumbnails via a shared helper, so logic can't drift between the two paths.
        var photoArea = $('woPhotoArea'), photoInput = $('woPhotoInput');
        var cameraInput = $('woPhotoCameraInput');
        function refreshPhotoAddBtns() {
            var show = _photoFiles.length < 6;
            var add = $('woPhotoAdd'), cam = $('woPhotoCamera');
            if (add) add.style.display = show ? '' : 'none';
            if (cam) cam.style.display = show ? '' : 'none';
        }
        function addWoPhotoFiles(files) {
            Array.from(files).forEach(function (f) {
                if (_photoFiles.length >= 6) return;
                var isVid = f.type && f.type.startsWith('video/');
                // Compress photos (resize to max 1600px, JPEG q0.8) before adding to the
                // upload queue. Cuts upload size ~70%+ so submission is fast on a slow link.
                // Videos can't be compressed in-browser; uploaded as-is.
                if (isVid) {
                    addOnePhotoFile(f, isVid);
                } else {
                    compressPhoto(f, 1600, 0.8).then(function (comp) {
                        addOnePhotoFile(comp || f, false);
                    }).catch(function () { addOnePhotoFile(f, false); });
                }
            });
        }
        function addOnePhotoFile(f, isVid) {
            if (_photoFiles.length >= 6) return;
            _photoFiles.push(f);
            // Use an object URL (cheap, works for large video files) instead of a
            // base64 data URL which would balloon memory for multi-MB videos.
            var url = URL.createObjectURL(f);
            var div = document.createElement('div'); div.className = 'v2-photo-thumb';
            var mediaHtml = isVid
                ? '<video src="' + url + '" muted></video><span class="v2-photo-badge">▶</span>'
                : '<img src="' + url + '">';
            div.innerHTML = mediaHtml + '<button type="button" class="v2-photo-rm">×</button>';
            div.querySelector('.v2-photo-rm').addEventListener('click', function () {
                var idx = Array.from(photoArea.querySelectorAll('.v2-photo-thumb')).indexOf(div);
                _photoFiles.splice(idx, 1); div.remove(); URL.revokeObjectURL(url); refreshPhotoAddBtns();
            });
            // Insert before the camera button (first add button) so both add
            // buttons always sit at the end of the row.
            photoArea.insertBefore(div, $('woPhotoCamera'));
            refreshPhotoAddBtns();
        }
        if ($('woPhotoAdd')) $('woPhotoAdd').addEventListener('click', function () { photoInput.click(); });
        if (photoInput) photoInput.addEventListener('change', function () { addWoPhotoFiles(photoInput.files); photoInput.value = ''; });
        if ($('woPhotoCamera')) $('woPhotoCamera').addEventListener('click', function () { if (cameraInput) cameraInput.click(); });
        if (cameraInput) cameraInput.addEventListener('change', function () { addWoPhotoFiles(cameraInput.files); cameraInput.value = ''; });
    }

    function escHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c];
        });
    }

    function ensureWoTreeStyle() {
        if (document.getElementById('v2-wo-style')) return;
        var css = '' +
            '#woCatPrimary{display:flex;flex-wrap:wrap;gap:8px;}' +
            '#woCatPrimary .v2-chip{flex:1 1 calc(33.333% - 8px);justify-content:center;text-align:center;}' +
            '.v2-wo-bc{display:flex;align-items:center;flex-wrap:wrap;gap:4px;padding:8px 12px;border-bottom:1px solid #f0f0f0;font-size:0.82rem;color:#666;line-height:1.4;}' +
            '.v2-wo-crumb{color:#2D6A4F;cursor:pointer;}' +
            '.v2-wo-sep{color:#ccc;}' +
            '.v2-wo-row{display:flex;align-items:center;gap:8px;width:100%;background:none;border:none;border-bottom:1px solid #f5f5f5;padding:13px 4px;font-size:0.95rem;color:#333;cursor:pointer;text-align:left;}' +
            '.v2-wo-row:hover{background:#f6f9f6;}' +
            '.v2-wo-rowname{flex:1;}' +
            '.v2-wo-rowval{font-size:0.85rem;color:#2D6A4F;font-weight:600;background:#e9f3ee;padding:2px 9px;border-radius:10px;white-space:nowrap;}' +
            '.v2-wo-rowval.empty{color:#bbb;font-weight:400;background:#f2f2f2;}' +
            '.v2-wo-chev{color:#bbb;font-size:0.9rem;}' +
            '.v2-wo-projwrap{padding:10px 4px;border-bottom:1px solid #f0f0f0;}' +
            '.v2-wo-projwrap select{width:100%;padding:9px;border:1px solid #d8d8d8;border-radius:8px;font-size:0.92rem;box-sizing:border-box;}' +
            '.v2-wo-filled{margin-top:10px;}' +
            '.v2-wo-ftitle{font-size:0.82rem;color:#999;padding:6px 4px;}' +
            '.v2-wo-fitem{display:flex;align-items:center;gap:8px;padding:8px 4px;border-bottom:1px solid #f5f5f5;font-size:0.86rem;}' +
            '.v2-wo-fpath{flex:1;color:#444;line-height:1.3;}' +
            '.v2-wo-fpath small{display:block;color:#aaa;font-size:0.74rem;}' +
            '.v2-wo-fval{color:#2D6A4F;font-weight:600;font-size:0.85rem;white-space:nowrap;}' +
            '.v2-wo-frm{font-size:0.9rem;color:#c0392b;border:none;background:none;cursor:pointer;}' +
            '.v2-wo-pop input[type=number],.v2-wo-pop select,.v2-wo-pop textarea{width:100%;padding:9px;border:1px solid #d8d8d8;border-radius:8px;font-size:0.95rem;box-sizing:border-box;}' +
            '.v2-wo-pop textarea{resize:vertical;}' +
            '.v2-wo-pop label{display:block;font-size:0.82rem;color:#888;margin:8px 0 4px;}';
        var style = document.createElement('style');
        style.id = 'v2-wo-style';
        style.textContent = css;
        document.head.appendChild(style);
    }

    function indexWorkTree(tree) {
        _woRoots = tree || [];
        _woNodeById = {}; _woParentById = {};
        function walk(node, parent) {
            _woNodeById[node.id] = node;
            if (parent) _woParentById[node.id] = parent;
            (node.children || []).forEach(function (c) { walk(c, node); });
        }
        _woRoots.forEach(function (n) { walk(n, null); });
    }

    function resetWoState() {
        _woEntries = {}; _woEntryPhotos = {}; _woPath = []; _woProject = null; _woCatNode = null;
        _woPlanned = { checked: {}, other: '', reports: [] };
    }

    function currentWoNode() {
        if (!_woPath.length) return null;
        return _woNodeById[_woPath[_woPath.length - 1]];
    }

    function openWoSheet() {
        ensureWoTreeStyle();
        _woPath = _woCatNode ? [_woCatNode] : [];
        var m = $('woTreeModal'); if (m) m.style.display = 'flex';
        renderWoLevel();
    }

    function woAncestorNames(id) {
        var names = [], cur = _woParentById[id];
        while (cur) { names.unshift(cur.name); cur = _woParentById[cur.id]; }
        return names;
    }

    function woValueLabel(node, e) {
        if (!e) return '';
        if (node.value_type === 'count') return '×' + (e.count || 0) + (node.unit ? (' ' + node.unit) : '');
        if (node.value_type === 'status') return e.status || '';
        var t = (e.text_value || '');
        if (node.value_type === 'text_photo') return (t ? t.slice(0, 8) : '📷');
        return t ? t.slice(0, 8) : '✓';
    }

    function drillInto(id) { _woPath.push(id); renderWoLevel(); }
    function drillUpTo(idx) {
        var floor = _woCatNode ? 1 : 0;
        if (idx < 0) _woPath = _woCatNode ? [_woCatNode] : [];
        else _woPath = _woPath.slice(0, Math.max(floor, idx + 1));
        renderWoLevel();
    }

    // 计划性维修: list past 待修 workorders in the current zone (checkable) + 其他 (free text).
    function renderPlannedList(node) {
        var body = $('woSheetBody');
        if (body) body.innerHTML = '<div class="v2-wo-ftitle" style="text-align:center;padding:24px;">加载待修工单…</div>';
        var zones = Array.from(_selectedZoneCodes).join(',');
        fetch('/api/planned-maintenance/pending/?zones=' + encodeURIComponent(zones), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) { renderPlannedListInner(node, (data && data.reports) || []); })
            .catch(function () { renderPlannedListInner(node, []); });
    }

    function renderPlannedListInner(node, reports) {
        var body = $('woSheetBody'); if (!body) return;
        var html = '<div class="v2-wo-ftitle">待修工单（该区域历史 · 勾选本次已处理）</div>';
        if (!reports.length) {
            html += '<div class="v2-wo-ftitle" style="text-align:center;padding:14px;color:#bbb;">暂无待修工单</div>';
        } else {
            reports.forEach(function (rp) {
                var on = !!_woPlanned.checked[rp.id];
                var items = (rp.items && rp.items.length) ? rp.items.join('；') : '待修';
                html += '<button type="button" class="v2-wo-row" data-pm="' + rp.id + '"><span class="v2-wo-rowname">' +
                    escHtml(rp.date || '') + ' 工单#' + rp.id + (rp.worker ? ' · ' + escHtml(rp.worker) : '') +
                    '<small style="display:block;color:#999;font-size:0.78rem;">' + escHtml(items) + '</small></span>' +
                    (on ? '<span class="v2-wo-rowval">✓</span>' : '<span class="v2-wo-rowval empty">○</span>') + '</button>';
            });
        }
        html += '<button type="button" class="v2-wo-row" id="woPmOther"><span class="v2-wo-rowname">其他（自行填写）</span>' +
            '<span class="v2-wo-rowval' + (_woPlanned.other ? '' : ' empty') + '">' +
            (_woPlanned.other ? escHtml(_woPlanned.other.slice(0, 8)) : '填写') + '</span></button>';
        body.innerHTML = html;
        body.querySelectorAll('[data-pm]').forEach(function (b) {
            b.addEventListener('click', function () {
                var rid = b.dataset.pm;
                if (_woPlanned.checked[rid]) delete _woPlanned.checked[rid];
                else _woPlanned.checked[rid] = true;
                syncPlannedEntry(node);
                renderPlannedListInner(node, reports);
            });
        });
        var other = $('woPmOther');
        if (other) other.addEventListener('click', function () {
            var v = prompt('其他计划性维修内容：', _woPlanned.other || '');
            if (v != null) { _woPlanned.other = v.trim(); syncPlannedEntry(node); renderPlannedListInner(node, reports); }
        });
    }

    function syncPlannedEntry(node) {
        var parts = [];
        var ids = Object.keys(_woPlanned.checked);
        if (ids.length) parts.push('处理待修工单 #' + ids.join(', #'));
        if (_woPlanned.other) parts.push('其他: ' + _woPlanned.other);
        if (parts.length) _woEntries[node.id] = { count: 0, status: '', text_value: parts.join(' | '), hasPhoto: false, project: null };
        else delete _woEntries[node.id];
        var pmInput = $('woPmResolved');
        if (pmInput) pmInput.value = ids.join(',');
        updateWoTrigger();
    }

    function renderWoLevel() {
        ensureWoTreeStyle();
        var bc = $('woBreadcrumb'), body = $('woSheetBody');
        if (!body) return;
        var crumbs = [];
        if (!_woCatNode) crumbs.push({ up: -1, name: '全部' });
        _woPath.forEach(function (id, i) { crumbs.push({ up: i, name: ((_woNodeById[id] || {}).name) || '' }); });
        if (bc) {
            bc.innerHTML = crumbs.map(function (c, i) {
                return (i ? '<span class="v2-wo-sep">›</span>' : '') + '<span class="v2-wo-crumb" data-up="' + c.up + '">' + escHtml(c.name) + '</span>';
            }).join('');
            bc.querySelectorAll('.v2-wo-crumb').forEach(function (c) { c.addEventListener('click', function () { drillUpTo(parseInt(c.dataset.up, 10)); }); });
        }

        var cur = currentWoNode();
        if (cur && cur.name === '计划性维修') { renderPlannedList(cur); return; }
        var children = cur ? (cur.children || []) : _woRoots;
        var html = '';
        // Project selector at the 灌溉项目 section root.
        if (cur && cur.section === 'irrigation_project' && _woPath.length === 1 && !_woProject) {
            html += '<div class="v2-wo-projwrap"><select id="woProjectSelect"><option value="">请先选择项目…</option>' +
                _woProjects.map(function (p) { return '<option value="' + p.id + '"' + (_woProject == p.id ? ' selected' : '') + '>' + escHtml(p.category_display) + ' · ' + escHtml(p.name) + '</option>'; }).join('') +
                '</select></div>';
        }
        children.forEach(function (ch) {
            if (ch.children && ch.children.length) {
                html += '<button type="button" class="v2-wo-row" data-drill="' + ch.id + '"><span class="v2-wo-rowname">' + escHtml(ch.name) + '</span><span class="v2-wo-chev">›</span></button>';
            } else {
                var e = _woEntries[ch.id];
                var label = e ? '<span class="v2-wo-rowval">' + escHtml(woValueLabel(ch, e)) + '</span>' : (ch.value_type === 'toggle' ? '<span class="v2-wo-rowval empty">○</span>' : '<span class="v2-wo-rowval empty">填写</span>');
                html += '<button type="button" class="v2-wo-row" data-leaf="' + ch.id + '"><span class="v2-wo-rowname">' + escHtml(ch.name) + '</span>' + label + '</button>';
            }
        });
        if (!children.length) html += '<div class="v2-wo-ftitle" style="text-align:center;padding:24px;">无子项</div>';

        var filledIds = Object.keys(_woEntries);
        if (filledIds.length) {
            html += '<div class="v2-wo-filled"><div class="v2-wo-ftitle">已填 (' + filledIds.length + ')</div>';
            filledIds.forEach(function (id) {
                var n = _woNodeById[id]; if (!n) return;
                html += '<div class="v2-wo-fitem"><div class="v2-wo-fpath">' + escHtml(n.name) + '<small>' + escHtml(woAncestorNames(id).join(' › ')) + '</small></div>' +
                    '<span class="v2-wo-fval">' + escHtml(woValueLabel(n, _woEntries[id])) + '</span>' +
                    '<button type="button" class="v2-wo-frm" data-rm="' + id + '">✕</button></div>';
            });
            html += '</div>';
        }

        body.innerHTML = html;
        body.querySelectorAll('[data-drill]').forEach(function (b) { b.addEventListener('click', function () { drillInto(parseInt(b.dataset.drill, 10)); }); });
        body.querySelectorAll('[data-leaf]').forEach(function (b) { b.addEventListener('click', function () { var nd = _woNodeById[parseInt(b.dataset.leaf, 10)]; if (nd && nd.value_type === 'toggle') toggleWoSelection(nd); else openWoLeafPopup(nd); }); });
        body.querySelectorAll('[data-rm]').forEach(function (b) { b.addEventListener('click', function (ev) { ev.stopPropagation(); removeWoEntry(parseInt(b.dataset.rm, 10)); }); });
        var ps = $('woProjectSelect');
        if (ps) ps.addEventListener('change', function () { _woProject = ps.value ? parseInt(ps.value, 10) : null; });
    }

    // Toggle (no-count) leaf: tap to select/deselect.
    function toggleWoSelection(node) {
        if (!node) return;
        if (node.is_project_scoped && !_woProject) { showToast('请先选择项目', 'error'); return; }
        if (_woEntries[node.id]) {
            delete _woEntries[node.id];
            delete _woEntryPhotos[node.id];
        } else {
            _woEntries[node.id] = { count: 0, status: node.name, text_value: '', hasPhoto: false, project: node.is_project_scoped ? _woProject : null };
        }
        // 联动: tapping a 待修 leaf also flips the header 待修 chip to "是" so the
        // pending-repair flag is captured in one place. (Mirrors the desktop tree form.)
        if (node.name === '待修' && _woEntries[node.id]) setRadioChip('is_pending_repair', '1');
        renderWoLevel();
        updateWoTrigger();
    }

    // 待修 (top-level toggle) ⇒ auto-flag 疑难=是 / 已处理=否. Mirrors server safety net.
    function syncDifficultChips() {
        var on = chipValue('is_pending_repair') === '1';
        if (on) {
            setRadioChip('is_difficult', '1');           // 疑难 = 是
            setRadioChip('is_difficult_resolved', '');   // 疑难未解决
        }
    }
    // Reverse linkage: when the header 待修 chip is turned OFF, drop any selected
    // 待修 leaves in the work-content tree so the two stay consistent.
    function clearPendingRepairLeaves() {
        if (chipValue('is_pending_repair') === '1') return;  // only on "否"
        var changed = false;
        Object.keys(_woEntries).forEach(function (id) {
            var nd = _woNodeById[id];
            if (nd && nd.name === '待修') { delete _woEntries[id]; delete _woEntryPhotos[id]; changed = true; }
        });
        if (changed) { renderWoLevel(); updateWoTrigger(); }
    }
    function chipValue(name) {
        var checked = document.querySelector('#woModalForm input[name="' + name + '"]:checked');
        return checked ? checked.value : '';
    }
    function setRadioChip(name, val) {
        var inputs = document.querySelectorAll('#woModalForm input[name="' + name + '"]');
        if (!inputs.length) return;
        Array.prototype.forEach.call(inputs, function (r) {
            var on = r.value === val;
            r.checked = on;
            var chip = r.closest('.v2-chip');
            if (chip) chip.classList.toggle('active', on);
        });
    }

    function openWoLeafPopup(node) {
        if (!node) return;
        if (node.is_project_scoped && !_woProject) { showToast('请先选择项目', 'error'); return; }
        _woLeafTarget = node.id;
        $('woLeafTitle').textContent = node.name;
        var e = _woEntries[node.id] || {};
        var inner = '<div class="v2-wo-pop">';
        if (node.value_type === 'count') {
            inner += '<label>数量' + (node.unit ? '（单位：' + escHtml(node.unit) + '）' : '') + '</label>' +
                '<input type="number" id="woLeafCount" min="0" inputmode="numeric" value="' + (typeof e.count === 'number' ? e.count : 1) + '">';
        } else if (node.value_type === 'status') {
            inner += '<label>状态</label><select id="woLeafStatus"><option value="">--</option>' +
                (node.status_options || []).map(function (o) { return '<option' + (e.status === o ? ' selected' : '') + '>' + escHtml(o) + '</option>'; }).join('') + '</select>';
        } else {
            inner += '<label>内容</label><textarea id="woLeafText" rows="3" placeholder="描述…">' + escHtml(e.text_value || '') + '</textarea>';
            if (node.value_type === 'text_photo') inner += '<label>照片</label><input type="file" id="woLeafFile" accept="image/*" multiple>';
        }
        inner += '</div>';
        $('woLeafBody').innerHTML = inner;
        $('woLeafModal').style.display = 'flex';
    }

    function closeWoLeafPopup() { var m = $('woLeafModal'); if (m) m.style.display = 'none'; _woLeafTarget = null; }

    function confirmWoLeaf() {
        var node = _woNodeById[_woLeafTarget];
        if (!node) { closeWoLeafPopup(); return; }
        var count = 0, status = '', text = '', hasData = false, hasPhoto = false;
        if (node.value_type === 'count') {
            count = parseInt(($('woLeafCount') || {}).value || 0, 10) || 0; hasData = count > 0;
        } else if (node.value_type === 'status') {
            status = ($('woLeafStatus') || {}).value || ''; hasData = !!status;
        } else {
            text = (($('woLeafText') || {}).value || '').trim();
            if (node.value_type === 'text_photo') {
                var f = $('woLeafFile'); var nf = f ? Array.from(f.files) : [];
                if (nf.length) { _woEntryPhotos[node.id] = nf; hasPhoto = true; }
                else if (_woEntryPhotos[node.id] && _woEntryPhotos[node.id].length) hasPhoto = true;
                hasData = !!(text || hasPhoto);
            } else { hasData = !!text; }
        }
        if (!hasData) { delete _woEntries[node.id]; delete _woEntryPhotos[node.id]; }
        else _woEntries[node.id] = { count: count, status: status, text_value: text, hasPhoto: hasPhoto, project: node.is_project_scoped ? _woProject : null };
        closeWoLeafPopup(); renderWoLevel(); updateWoTrigger();
    }

    function removeWoEntry(id) {
        delete _woEntries[id]; delete _woEntryPhotos[id];
        renderWoLevel(); updateWoTrigger();
    }

    function updateWoTrigger() {
        var n = Object.keys(_woEntries).length;
        var d = $('woContentDisplay');
        if (d) { d.textContent = n ? ('已填 ' + n + ' 项') : '选择'; d.style.color = n ? '#222' : '#bbb'; }
    }

    function collectWoEntries() {
        return Object.keys(_woEntries).map(function (id) {
            var e = _woEntries[id];
            return { work_item: parseInt(id, 10), project: e.project || null, count: e.count || 0, status: e.status || '', text_value: e.text_value || '' };
        });
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
        // Collect entries. If the user picked a 工作类别 (root WorkItem) but didn't drill
        // into specific content, still record the category as an entry so the report shows
        // that category instead of falling back to "旧版记录". Group nodes have no value,
        // so this is a zero-count marker the server ignores as a real count but keeps for
        // the section/category grouping.
        var entries = collectWoEntries();
        if (_woCatNode && !entries.some(function (e) { return e.work_item === _woCatNode; })) {
            entries.push({ work_item: _woCatNode, project: null, count: 0, status: '', text_value: '' });
        }
        var entriesInput = $('woEntriesInput'); if (entriesInput) entriesInput.value = JSON.stringify(entries);
        var fd = new FormData(form); _photoFiles.forEach(function (f) { fd.append('report_photos', f); });
        Object.keys(_woEntryPhotos).forEach(function (id) { _woEntryPhotos[id].forEach(function (f) { fd.append('ep_' + id, f); }); });
        var btn = $('woSubmitBtn'); btn.disabled = true; btn.textContent = '提交中...';
        fetch('/mobile/workorder/v2/', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); }).then(function (data) {
                if (data.success) {
                    showToast(data.message, 'success');
                    btn.disabled = false; btn.textContent = '提交';
                    setTimeout(function () { closeV2Modal('workorder'); }, 1500);
                }
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
