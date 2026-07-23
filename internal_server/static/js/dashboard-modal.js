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
    // Edit mode state. When set, submitV2Workorder sends report_id + report_photos_remove
    // so the server updates the existing report instead of creating a new one.
    var _editingReportId = null;
    // PMWorkOrder edit mode: when set, submit sends pm_order_id (not report_id).
    var _editingPmOrderId = null;
    var _pmGwoId = null;  // PM GeneratedWorkOrder id for extension requests
    // Set BEFORE buildForm during an edit open so initWorkorderBehaviors can skip
    // the create-only default-category selection. _editingReportId is set later
    // (after the fetch resolves), so it can't gate the IIFE directly.
    var _pendingEdit = false;
    var _existingPhotos = [];      // [{path}] persisted report photos shown with × remove
    var _photoRemove = new Set();  // paths the user removed (sent as report_photos_remove)

    // Validate a modal-data API response. Rejects error objects (e.g. {error:'无权限'})
    // so they are never cached and passed to buildForm.
    function isValidFormData(type, data) {
        if (!data || data.error) return false;
        if (type === 'workorder') return Array.isArray(data.sorted_shifts);
        if (type === 'inventory') return Array.isArray(data.inventory_tree);
        return true; // water_request: no strict required arrays
    }

    // Map a modal type to its element-id prefix (workorder→wo, water_request→wr, inventory→inv).
    function _modalPrefix(type) {
        return type === 'workorder' ? 'wo' : type === 'inventory' ? 'inv' : 'wr';
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
                var hl = L.polygon(zlayer.getLatLngs(), { color: '#C0392B', weight: 3, fillColor: '#C0392B', fillOpacity: 1, interactive: false });
                _selectionLayerGroup.addLayer(hl);
                overlays.push(hl);
            }
        });
        _selectionOverlays[code] = overlays;
    }

    // Reconcile the red selection overlays on the map with _selectedZoneCodes.
    // Called after the Set changes so the map always reflects the selection —
    // including when the form opens pre-filled (PM completion / quick / edit)
    // which otherwise only populate the Set without drawing overlays.
    function syncSelectionOverlays() {
        var map = getMap();
        if (!map) return;
        if (!_selectionLayerGroup) _selectionLayerGroup = L.layerGroup().addTo(map);
        // Remove overlays for codes no longer selected.
        Object.keys(_selectionOverlays).forEach(function (code) {
            if (!_selectedZoneCodes.has(code)) {
                (_selectionOverlays[code] || []).forEach(function (lyr) { _selectionLayerGroup.removeLayer(lyr); });
                delete _selectionOverlays[code];
            }
        });
        // Add overlays for newly selected codes.
        _selectedZoneCodes.forEach(function (code) {
            if (!_selectionOverlays[code]) addOverlayForCode(code);
        });
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
        _editingReportId = null; _editingPmOrderId = null; _pendingEdit = false; _existingPhotos = []; _photoRemove.clear();   // create mode

        // Fetch form data in background (cached or from API)
        var dataUrl = type === 'workorder' ? '/api/modal/workorder-data/'
                    : type === 'inventory' ? '/api/modal/inventory-data/'
                    : '/api/modal/water-request-data/';
        if (!_formDataCache[type]) {
            fetch(dataUrl, { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (isValidFormData(type, data)) _formDataCache[type] = data;
                })
                .catch(function () {});
        }

        // Inventory opens the form directly (no zone-first step). The zone is an
        // optional association the user can add later from the footer button.
        if (type === 'inventory') {
            _zoneConfirmed = true;  // zone not required for inventory
            _editingTxnId = null;   // create mode
            var showInv = function () {
                var p = _modalPrefix('inventory');
                buildForm('inventory', _formDataCache.inventory);
                var bd = $(p + 'ModalBackdrop'), ct = $(p + 'ModalContainer');
                if (bd) bd.style.display = '';
                if (ct) { ct.style.display = ''; ct.classList.add('open'); }
            };
            if (_formDataCache.inventory) { showInv(); }
            else {
                fetch('/api/modal/inventory-data/', { credentials: 'same-origin' })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (isValidFormData('inventory', data)) { _formDataCache.inventory = data; showInv(); }
                        else { showToast('加载库存数据失败', 'error'); }
                    })
                    .catch(function () { showToast('加载库存数据失败', 'error'); });
            }
            return;
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
        _editingReportId = null; _editingPmOrderId = null; _pendingEdit = false; _existingPhotos = []; _photoRemove.clear();   // create mode

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
            syncSelectionOverlays();   // paint red on the map for pre-filled zones
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

    // Edit an existing workorder: open the same mobile modal as create, but
    // pre-fill it with the report's zones/header/entries/photos. The work-reports
    // list / detail 编辑 buttons link to the dashboard with ?edit_workorder=<id>,
    // which triggers this on dashboard load.
    // Open the workorder CREATE form seeded for completing a PM task.
    // Dispatch stores the task on the GWO (no WorkReport shell), so completion
    // is a create flow: _pmGwoId is sent on submit so the server builds an
    // is_pm=True WorkReport, links it to the GWO, and marks the GWO completed.
    // Mirrors quickWorkorder (build the form directly — openV2Modal would route
    // workorder into map/zone-first mode instead of showing the form).
    window.openV2ModalForPm = function (gwoId) {
        if (!gwoId) return;
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        if (_currentModal) closeV2Modal(_currentModal);
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        _currentModal = 'workorder';
        _selectedZoneCodes.clear();
        _photoFiles = [];
        _zoneConfirmed = true;   // skip the zone-first gate; zones pre-filled below
        _editingReportId = null; _editingPmOrderId = null; _pendingEdit = false; _existingPhotos = []; _photoRemove.clear();   // create mode
        _pmGwoId = String(gwoId);
        resetWoZoneRecords();

        // GWO seed data (zones/date/remark) fetched alongside the form structure,
        // then applied once the form is built so the worker doesn't re-enter them.
        var pmSeed = null;

        var applySeed = function () {
            if (!pmSeed) return;
            // Pre-select the GWO's zones.
            (pmSeed.zone_codes || []).forEach(function (c) { _selectedZoneCodes.add(c); });
            // Date: set the visible <select> if the option exists, else hidden input.
            if (pmSeed.scheduled_date) {
                var dateSel = $('woDate'), dateHidden = $('woDateHidden'), headerDate = $('woHeaderDate');
                if (dateSel) {
                    var opt = dateSel.querySelector('option[value="' + pmSeed.scheduled_date + '"]');
                    if (opt) dateSel.value = pmSeed.scheduled_date;
                }
                if (dateHidden) dateHidden.value = pmSeed.scheduled_date;
                if (headerDate) headerDate.textContent = pmSeed.scheduled_date;
            }
            // Remark.
            if (pmSeed.remark != null) {
                var rm = document.querySelector('#woModalForm [name="remark"]');
                if (rm) rm.value = pmSeed.remark;
            }
            renderZoneSummary();
            syncSelectionOverlays();   // paint red on the map for pre-filled zones
        };

        var showForm = function () {
            if (_formDataCache.workorder) {
                buildForm('workorder', _formDataCache.workorder);
            }
            var backdrop = $('woModalBackdrop');
            var container = $('woModalContainer');
            if (backdrop) backdrop.style.display = '';
            if (container) { container.style.display = ''; container.classList.add('open'); }
            applySeed();
            // Reflect the PM task in the title so the worker sees what to complete.
            var titleEl = document.querySelector('#woModalContainer .modal-title, #woModalContainer h2, #woModalContainer h3');
            if (titleEl) { titleEl.textContent = '完成 PM 任务 (PM-' + gwoId + ')'; }
        };

        // Fetch both the GWO seed and the form data, then render.
        var seedP = fetch('/settings/pm/gwo/' + gwoId + '/detail/', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) { pmSeed = d; })
            .catch(function () { /* seed optional — form still works without it */ });

        var formP;
        if (_formDataCache.workorder) {
            formP = Promise.resolve();
        } else {
            formP = fetch('/api/modal/workorder-data/', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!isValidFormData('workorder', data)) {
                        _currentModal = null;
                        _zoneConfirmed = false;
                        showToast(data && data.error ? data.error : '加载表单失败', 'error');
                        return Promise.reject(new Error('bad form data'));
                    }
                    _formDataCache.workorder = data;
                });
        }
        Promise.all([seedP, formP]).then(showForm).catch(function () { /* already surfaced */ });
    };

    window.openV2ModalForEdit = function (reportId) {
        if (!reportId) return;
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        if (_currentModal) closeV2Modal(_currentModal);
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        _currentModal = 'workorder';
        _selectedZoneCodes.clear();
        _photoFiles = [];
        _existingPhotos = []; _photoRemove.clear();
        _pendingEdit = true;   // suppress create-only default category in buildForm
        _editingReportId = null;  // set only after data loads + pre-fill succeeds
        resetWoZoneRecords();

        // Show the modal container immediately with a loading state, so the user
        // always sees the form pop out — even before the data fetch resolves.
        var backdrop = $('woModalBackdrop');
        var container = $('woModalContainer');
        if (backdrop) backdrop.style.display = '';
        if (container) { container.style.display = ''; container.classList.add('open'); }
        var body = $('woModalBody');
        if (body) body.innerHTML = '<div style="text-align:center;padding:40px;color:#888;">加载工单中...</div>';
        var sb = $('woSubmitBtn'); if (sb) { sb.disabled = true; sb.textContent = '保存'; }

        fetch('/api/modal/workorder-data/?report_id=' + encodeURIComponent(reportId), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!isValidFormData('workorder', data) || !data.header) {
                    closeV2Modal('workorder');
                    showToast(data && data.error ? data.error : '加载工单失败', 'error');
                    return;
                }
                _formDataCache.workorder = data;
                // Seed selected zones from the report (skip map mode).
                (data.header.h_zones || []).forEach(function (c) { _selectedZoneCodes.add(c); });
                _zoneConfirmed = true;

                // Build the form, then apply the edit pre-fill. The pre-fill is
                // wrapped so a DOM hiccup on any single field never prevents the
                // form from showing.
                buildForm('workorder', data);
                try { applyWoEditPrefill(data); } catch (e) { /* keep form visible */ }
                _editingReportId = reportId;
                renderZoneSummary();
                syncSelectionOverlays();   // paint red on the map for the report's zones
                if (sb) sb.disabled = false;
            })
            .catch(function () { showToast('加载工单失败', 'error'); if (sb) { sb.disabled = false; sb.textContent = '保存'; } });
    };

    // Open an existing PMWorkOrder in edit/view mode (mirrors openV2ModalForEdit
    // but fetches by pm_order_id and sets _editingPmOrderId so submit updates the
    // PMWorkOrder, not a WorkReport).
    window.openV2ModalForPmEdit = function (pmOrderId) {
        if (!pmOrderId) return;
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        if (_currentModal) closeV2Modal(_currentModal);
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        _currentModal = 'workorder';
        _selectedZoneCodes.clear();
        _photoFiles = [];
        _existingPhotos = []; _photoRemove.clear();
        _pendingEdit = true;
        _editingReportId = null; _editingPmOrderId = null;
        resetWoZoneRecords();

        var backdrop = $('woModalBackdrop');
        var container = $('woModalContainer');
        if (backdrop) backdrop.style.display = '';
        if (container) { container.style.display = ''; container.classList.add('open'); }
        var body = $('woModalBody');
        if (body) body.innerHTML = '<div style="text-align:center;padding:40px;color:#888;">加载工单中...</div>';
        var sb = $('woSubmitBtn'); if (sb) { sb.disabled = true; sb.textContent = '保存'; }

        fetch('/api/modal/workorder-data/?pm_order_id=' + encodeURIComponent(pmOrderId), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!isValidFormData('workorder', data) || !data.header) {
                    closeV2Modal('workorder');
                    showToast(data && data.error ? data.error : '加载工单失败', 'error');
                    return;
                }
                _formDataCache.workorder = data;
                (data.header.h_zones || []).forEach(function (c) { _selectedZoneCodes.add(c); });
                _zoneConfirmed = true;
                buildForm('workorder', data);
                try { applyWoEditPrefill(data); } catch (e) { /* keep form visible */ }
                _editingPmOrderId = pmOrderId;
                renderZoneSummary();
                syncSelectionOverlays();
                if (sb) sb.disabled = false;
            })
            .catch(function () { showToast('加载工单失败', 'error'); if (sb) { sb.disabled = false; sb.textContent = '保存'; } });
    };

    // Write the existing report's values into the modal form built by
    // buildWorkorderForm. Mirrors applyHeader()/applyExisting() from the desktop
    // tree-form template (workorder_tree_form.html), adapted to this modal's IDs.
    function applyWoEditPrefill(data) {
        var h = data.header || {};
        // Reset PM extension state from any prior modal open (state-leak guard).
        _pmGwoId = null;
        var staleExt = document.getElementById('pmExtSection');
        if (staleExt) staleExt.remove();
        // Date: set the visible <select> if the option exists, else the hidden input.
        var dateSel = $('woDate'), dateHidden = $('woDateHidden'), headerDate = $('woHeaderDate');
        if (h.h_date) {
            if (dateSel) {
                var opt = dateSel.querySelector('option[value="' + h.h_date + '"]');
                if (opt) dateSel.value = h.h_date;
            }
            if (dateHidden) dateHidden.value = h.h_date;
            if (headerDate) headerDate.textContent = h.h_date;
        }
        // Shift / 待修 / 疑难 / 已处理 chips: activate the matching chip in each group.
        function activateChip(name, val) {
            var grp = document.querySelector('#woModalForm .v2-chip-group input[name="' + name + '"][value="' + val + '"]');
            if (!grp) return;
            var chip = grp.closest('.v2-chip');
            chip.closest('.v2-chip-group').querySelectorAll('.v2-chip').forEach(function (x) { x.classList.remove('active'); });
            chip.classList.add('active'); grp.checked = true;
        }
        if (h.h_shift) activateChip('shift', h.h_shift);
        activateChip('is_pending_repair', h.h_is_pending_repair ? '1' : '');
        activateChip('is_difficult', h.h_is_difficult ? '1' : '');
        activateChip('is_difficult_resolved', h.h_is_difficult_resolved ? '1' : '');
        // Counts, times, remark.
        setVal('[name="team_size"]', h.h_team_size != null ? h.h_team_size : 1);
        setVal('[name="third_party_count"]', h.h_third_party_count != null ? h.h_third_party_count : 0);
        if ($('woStart') && h.h_work_start_time) $('woStart').value = h.h_work_start_time;
        if ($('woEnd') && h.h_work_end_time) $('woEnd').value = h.h_work_end_time;
        if (h.h_remark != null) setVal('[name="remark"]', h.h_remark);
        // Recompute the hours line.
        if ($('woStart')) { var ev = document.createEvent('Event'); ev.initEvent('change', true, true); $('woStart').dispatchEvent(ev); $('woEnd').dispatchEvent(ev); }

        // Tree entries: restore count/status/text_value into _woEntries, keyed by
        // work_item id. (Per-entry photos are not re-shown in the leaf popup — they
        // are preserved server-side and re-submitted only if re-uploaded.)
        _woEntries = {}; _woEntryPhotos = {};
        (data.existing || []).forEach(function (e) {
            if (e.work_item == null) return;
            _woEntries[e.work_item] = {
                count: e.count || 0, status: e.status || '',
                text_value: e.text_value || '', hasPhoto: !!(e.photos && e.photos.length),
                project: e.project || null
            };
        });
        updateWoTrigger();

        // Persisted report photos: render thumbnails with × remove (added to
        // report_photos_remove on submit). New uploads append via the normal path.
        _existingPhotos = Array.isArray(data.report_photos) ? data.report_photos.slice() : [];
        renderWoExistingPhotos();

        // Prefill the material-consumption cart from the report's existing
        // outbound transaction (edit mode).
        prefillWoMaterials(Array.isArray(data.existing_materials) ? data.existing_materials : []);
        // Restore the material destination from the existing txn.
        if (data.existing_material_dest) {
            _woMatDest.subtype = data.existing_material_dest.entry_subtype || '日常维护';
            _woMatDest.projectId = data.existing_material_dest.project_id || null;
            _woMatDest.counterparty = data.existing_material_dest.counterparty || '';
            _woMatDest.other = '';
        }

        // Restore the 工作类别 (category) selection from the existing entries.
        // Without this, the default routine-maint category would be submitted on
        // re-save and silently flip the report's category to 日常维护.
        try { restoreWoCategory(data.existing || []); } catch (e) { /* keep form usable */ }

        // PM auto-dispatched work order: pre-fill 工作类别=常规维护 › 维保定期检查
        // and seed a work-content entry with the JobPlan name. restoreWoCategory
        // is a no-op for these (entries empty), so this branch takes over.
        // NOTE: pickWoCategory lives inside the initWorkorderBehaviors closure and
        // isn't accessible here, so we set _woCatNode + the display label inline —
        // mirroring what restoreWoCategory does above.
        if (h.h_pm_job_plan) {
            // Derive the category from the PM leaf node (h_pm_work_item) by
            // walking up _woParentById — robust to category renames, unlike
            // matching by the Chinese display name '维保定期检查'.
            var pmLeaf = (h.h_pm_work_item != null) ? _woNodeById[h.h_pm_work_item] : null;
            var rmRoot = null, pmSub = null;
            if (pmLeaf) {
                var cur = pmLeaf;
                while (cur) {
                    var parent = _woParentById[cur.id];
                    if (!parent) { rmRoot = cur; break; }
                    pmSub = cur;   // direct child of root = the sub-category
                    cur = parent;
                }
            }
            if (rmRoot && pmSub) {
                _woCatNode = pmSub.id;
                _woProject = null;
                var pmDisp = $('woCatDisplay');
                if (pmDisp) { pmDisp.textContent = rmRoot.name + ' › ' + pmSub.name; pmDisp.style.color = '#222'; }
                var pmTrig = $('woContentTrigger');
                var pmRow = pmTrig ? pmTrig.closest('.v2-fg') : null;
                if (pmRow) pmRow.style.display = '';
                if (typeof updateWoMatDest === 'function') updateWoMatDest();
            }
            // Seed the JobPlan name into the PM leaf entry AFTER setting the
            // category, so the content tree shows it.
            if (h.h_pm_work_item != null && _woNodeById[h.h_pm_work_item]) {
                _woEntries[h.h_pm_work_item] = {
                    count: 0, status: '', text_value: h.h_pm_job_plan,
                    hasPhoto: false, project: null
                };
                updateWoTrigger();
            }
            // Inject "申请延期" button for PM work orders.
            if (h.h_pm_gwo_id) {
                _pmGwoId = h.h_pm_gwo_id;
                var body = $('woModalBody');
                if (body && !document.getElementById('pmExtSection')) {
                    var todayStr = new Date().toISOString().slice(0, 10);
                    var extDiv = document.createElement('div');
                    extDiv.id = 'pmExtSection';
                    extDiv.style.cssText = 'margin-top:12px;padding:10px;border:1px dashed #d1e7dd;border-radius:8px;background:#f8fdfb;';
                    extDiv.innerHTML =
                        '<details style="font-size:.85rem;">' +
                        '<summary style="cursor:pointer;color:#2D6A4F;font-weight:600;">📅 无法按时完成？申请延期</summary>' +
                        '<div style="margin-top:8px;display:flex;flex-direction:column;gap:6px;">' +
                        '<label style="font-size:.8rem;color:#666;">期望延期到 <input type="date" id="pmExtDate" min="' + todayStr + '" style="margin-left:6px;padding:4px 6px;border:1px solid #ddd;border-radius:6px;"></label>' +
                        '<input type="text" id="pmExtReason" placeholder="延期理由（如：下雨设备故障等）" style="padding:6px 8px;border:1px solid #ddd;border-radius:6px;font-size:.85rem;">' +
                        '<button type="button" class="btn-sm btn-secondary" onclick="submitPmExtension()" style="align-self:flex-start;">提交延期申请</button>' +
                        '</div></details>';
                    body.appendChild(extDiv);
                }
            }
        }

        var sb = $('woSubmitBtn'); if (sb) { sb.textContent = '保存'; }
    }

    // Reconstruct _woCatNode / _woProject for edit mode from the report's existing
    // entries. Each entry's work_item id resolves to a node in _woNodeById; walking
    // up _woParentById reaches the root (whose section is the category type). This
    // mirrors pickWoCategory/pickWoProject so the restored state round-trips.
    function restoreWoCategory(existing) {
        // Find a representative entry: prefer one with a work_item present in the tree.
        var rep = null;
        for (var i = 0; i < existing.length; i++) {
            var wid = existing[i].work_item;
            if (wid != null && _woNodeById[wid]) { rep = existing[i]; break; }
        }
        if (!rep) return;  // nothing to restore; leave the (create-default) category

        var node = _woNodeById[rep.work_item];
        // Walk to the root (parent === null) and remember the direct child of the
        // root — that's the `sub` level pickWoCategory(root, sub) selects.
        var cur = node, root = node, sub = null;
        while (cur) {
            var parent = _woParentById[cur.id];
            if (!parent) { root = cur; break; }
            sub = cur;           // this node is a candidate sub (one below root)
            cur = parent;
        }
        var display = $('woCatDisplay');
        var setDisplay = function (text) { if (display) { display.textContent = text; display.style.color = '#222'; } };
        var setContentRow = function (visible) {
            var trig = $('woContentTrigger');
            var row = trig ? trig.closest('.v2-fg') : null;
            if (row) row.style.display = visible ? '' : 'none';
        };

        var PROJECT_SECTIONS = { irrigation_project: 1, drainage_project: 1, other_project: 1 };
        if (PROJECT_SECTIONS[root.section]) {
            // Project-typed category: _woCatNode is the root, _woProject the entry's project.
            _woCatNode = root.id;
            _woProject = rep.project || null;
            var proj = _woProject ? (_woProjects.filter(function (p) { return p.id === _woProject; })[0]) : null;
            setDisplay(root.name + (proj ? ' › ' + (proj.name || '') : ''));
            setContentRow(true);
        } else {
            // Normal category: if the root has children, _woCatNode is the sub that is
            // an ancestor of (or equal to) the entry node. Otherwise it's the root.
            var chosen = (root.children && root.children.length) ? (sub || root) : root;
            _woCatNode = chosen.id;
            _woProject = null;
            setDisplay(chosen === root ? root.name : (root.name + ' › ' + chosen.name));
            setContentRow(!!(chosen.children && chosen.children.length));
        }
        if (typeof updateWoMatDest === 'function') updateWoMatDest();
        updateWoTrigger();
    }

    // Edit an existing inventory transaction: open the same modal as create, but
    // pre-fill it with the txn's operation/subtype/date/lines/etc. Mirrors
    // openV2ModalForEdit for workorders. Triggered from the ledger 编辑 button
    // via ?edit_inventory=<id>.
    window.openV2ModalForEditInv = function (txnId) {
        if (!txnId) return;
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        if (_currentModal) closeV2Modal(_currentModal);
        if (_closeTimeout) { clearTimeout(_closeTimeout); _closeTimeout = null; }
        _currentModal = 'inventory';
        _selectedZoneCodes.clear();
        _zoneConfirmed = true;          // inventory never requires a zone
        _editingTxnId = null;           // set only after pre-fill succeeds

        var p = _modalPrefix('inventory');
        var bd = $(p + 'ModalBackdrop'), ct = $(p + 'ModalContainer');
        if (bd) bd.style.display = '';
        if (ct) { ct.style.display = ''; ct.classList.add('open'); }
        var body = $(p + 'ModalBody');
        if (body) body.innerHTML = '<div style="text-align:center;padding:40px;color:#888;">加载库存记录中...</div>';
        var sb = $('invSubmitBtn'); if (sb) { sb.disabled = true; sb.textContent = '保存'; }

        fetch('/api/modal/inventory-data/?txn_id=' + encodeURIComponent(txnId), { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!isValidFormData('inventory', data)) {
                    closeV2Modal('inventory');
                    showToast(data && data.error ? data.error : '加载库存记录失败', 'error');
                    return;
                }
                buildForm('inventory', data);
                try { applyInvEditPrefill(data); } catch (e) { /* keep form usable */ }
                _editingTxnId = txnId;
                if (sb) sb.disabled = false;
            })
            .catch(function () { showToast('加载库存记录失败', 'error'); if (sb) { sb.disabled = false; sb.textContent = '保存'; } });
    };

    // Write the existing txn's values into the inventory modal built by
    // buildInventoryForm. Mirrors applyWoEditPrefill.
    function applyInvEditPrefill(data) {
        var h = data.header || {};
        // Operation type: activate the matching chip + hidden input.
        if (h.operation) {
            document.querySelectorAll('.inv-op-chip').forEach(function (c) {
                c.classList.toggle('active', c.dataset.val === h.operation);
            });
            var opInput = $('invOpInput'); if (opInput) opInput.value = h.operation;
        }
        // Subtype chips are rebuilt by _invBuildSubtypes() (called in buildForm);
        // activate the one matching the saved entry_subtype.
        if (h.entry_subtype) {
            document.querySelectorAll('.inv-sub-chip').forEach(function (c) {
                c.classList.toggle('active', c.dataset.val === h.entry_subtype);
            });
            var subInput = $('invSubInput'); if (subInput) subInput.value = h.entry_subtype;
        }
        _invSyncCondFields();   // show order_no / project / counterparty rows as needed
        // Date.
        if (h.date) {
            var dateSel = $('invDate');
            if (dateSel) {
                var opt = dateSel.querySelector('option[value="' + h.date + '"]');
                if (opt) dateSel.value = h.date; else dateSel.value = h.date;
            }
        }
        // Order no / counterparty / remark.
        if (h.order_no != null) { var on = $('invOrderNo'); if (on) on.value = h.order_no; }
        if (h.counterparty != null) { var cp = $('invCounterparty'); if (cp) cp.value = h.counterparty; }
        var rm = document.querySelector('#invModalForm [name="remark"]'); if (rm && h.remark != null) rm.value = h.remark;
        // 出库-项目: activate the project-category chip + project-name chip.
        if (h.operation === '出库' && h.entry_subtype === '项目' && h.project_id) {
            if (h.project_category) {
                document.querySelectorAll('.inv-pcat-chip').forEach(function (c) {
                    if (c.dataset.val === h.project_category) c.click();   // cascades into name chips
                });
            }
            document.querySelectorAll('.inv-pname-chip').forEach(function (c) {
                c.classList.toggle('active', String(c.dataset.val) === String(h.project_id));
            });
            var pj = $('invProjInput'); if (pj) pj.value = h.project_id;
        }
        // Material cart: rebuild from existing_lines (id/name/stock/quantity/unit).
        _invCart = (data.existing_lines || []).map(function (ln) {
            return { id: ln.category, name: ln.name, stock: ln.stock, quantity: ln.quantity, unit: ln.unit || '' };
        });
        _invRenderCart();
        // Zone association (optional).
        if (h.zone_id) _selectedZoneCodes.add(String(h.zone_id));
        // Submit button label.
        var sb = $('invSubmitBtn'); if (sb) sb.textContent = '保存';
    }

    function renderWoExistingPhotos() {
        var photoArea = $('woPhotoArea');
        if (!photoArea) return;
        // Clear any previously rendered existing-photo thumbs (keep add buttons + new uploads).
        photoArea.querySelectorAll('.v2-photo-thumb.existing').forEach(function (n) { n.remove(); });
        var surviving = _existingPhotos.filter(function (p) { return !_photoRemove.has(p); });
        var camBtn = $('woPhotoCamera');
        surviving.forEach(function (p) {
            var div = document.createElement('div');
            div.className = 'v2-photo-thumb existing';
            var isVid = /\.(mp4|mov|m4v|webm|ogg|avi|mkv)$/i.test(p);
            var thumb = p.replace(/\.[^.]+$/, '_thumb.jpg');
            var mediaHtml = isVid
                ? '<video src="/media/' + escHtml(thumb) + '" muted></video><span class="v2-photo-badge">▶</span>'
                : '<img src="/media/' + escHtml(thumb) + '" loading="lazy">';
            div.innerHTML = mediaHtml + '<button type="button" class="v2-photo-rm">×</button>';
            div.querySelector('.v2-photo-rm').addEventListener('click', function () {
                _photoRemove.add(p);
                renderWoExistingPhotos();
            });
            photoArea.insertBefore(div, camBtn);
        });
    }

    window.closeV2Modal = function (type) {
        if (!type) type = _currentModal;
        // P0-3: skip zone validation when closing/canceling
        _zoneConfirmed = true;
        var exitOk = _mapMode ? exitMapMode() : true;
        var p = _modalPrefix(type);
        var backdrop = $(p + 'ModalBackdrop');
        var container = $(p + 'ModalContainer');
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
        var invZS = $('invZoneSummary'); if (invZS) invZS.innerHTML = '<h2>库存管理</h2>';
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
        var pfx = _modalPrefix(type);
        var backdrop = $(pfx + 'ModalBackdrop');
        var container = $(pfx + 'ModalContainer');
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
        var pfx2 = _modalPrefix(type);
        var backdrop = $(pfx2 + 'ModalBackdrop');
        var container = $(pfx2 + 'ModalContainer');
        if (backdrop) backdrop.style.display = '';
        if (container) { container.style.display = ''; container.classList.add('open'); }

        // Build form if not yet rendered
        if (_formDataCache[type] && isValidFormData(type, _formDataCache[type])) {
            var bodyId = pfx2 + 'ModalBody';
            var body = $(bodyId);
            if (body && (!body.querySelector('form') || body.querySelector('.loading'))) {
                buildForm(type, _formDataCache[type]);
            }
        }

        // Show selected zones above form
        renderZoneSummary();
        syncSelectionOverlays();   // keep red overlays visible after exiting map mode

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
        var hint = type === 'water_request' ? '请选择或绘制区域' : '请在地图上选择区域';
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
        // Scope tab toggling to this toolbar (#v2DrawToolBar) only — the workorder
        // selection bar (#v2WoSelectBar) reuses .v2-draw-tab and must not be touched.
        document.querySelectorAll('#v2DrawToolBar .v2-draw-tab').forEach(function (t) { t.classList.toggle('active', t.dataset.tab === tab); });
        $('v2TabName').classList.toggle('active', tab === 'name');
        $('v2TabDraw').classList.toggle('active', tab === 'draw');
        if (tab === 'name') { cancelDraw(); getMap().getContainer().style.cursor = ''; buildWrNameChips(); }
    };

    // Flat 通用名称 list for the water-request tool bar: one chip per distinct
    // 通用名称 (across all Lands). Clicking a chip selects ALL zones that share
    // that name (incl. boundary-less ones). No level-2 popup — unlike the
    // workorder's buildWoNameChips which groups by Land first.
    function buildWrNameChips() {
        var container = $('wrNameChips');
        if (!container) return;
        // Land-level list: one chip per Land. Clicking selects ALL zones in that
        // Land (incl. boundary-less ones). Single level only — no Land→名称 popup
        // (unlike the workorder's buildWoNameChips which has a level-2 sheet).
        var lands = getWoLands();
        container.innerHTML = '';
        if (lands.length === 0) {
            container.innerHTML = '<div style="font-size:0.85em;color:#aaa;padding:8px;">无所属Land数据</div>';
            return;
        }
        var hint = document.createElement('div');
        hint.style.cssText = 'font-size:0.78em;color:#999;width:100%;margin-bottom:4px;';
        hint.textContent = '点击Land选中其下全部区域（可多选）';
        container.appendChild(hint);
        lands.forEach(function (land) {
            var chip = document.createElement('div');
            chip.className = 'v2-chip';
            chip.style.cssText = 'font-size:0.85em;padding:5px 10px;';
            chip.dataset.landId = land.id;
            setWoLandChipState(chip, land.id);
            var label = document.createElement('span');
            label.textContent = land.name;
            chip.appendChild(label);
            chip.addEventListener('click', function () {
                // Toggle: if ANY zone in this land is selected, clear all of it;
                // otherwise select all.
                var c = countWoZones(function (z) { return z.land_id === land.id; });
                var select = !(c.selected > 0);
                selectZonesByLand(land.id, select);
                setWoLandChipState(chip, land.id);
                updateInfoBarText();
            });
            container.appendChild(chip);
        });
    }

    function showDrawToolBar() {
        var bar = $('v2DrawToolBar'); if (bar) bar.style.display = '';
        // Default to the flat 通用名称 tab and build its chips.
        switchDrawTab('name');
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

    // Match priority: 0 = exact code, 1 = code segment-prefix,
    //                 3 = name exact, 4 = name starts-with, 5 = name contains.
    // Lower is better (shows first). Codes are hierarchical (1-2 → 1-2-1 …), so
    // code matching is SEGMENT-AWARE prefix: "1-2" matches "1-2" and "1-2-3" but
    // NOT "2-1-2" (substring) or "1-23" (textual prefix). This keeps "全选" scoped
    // to a real subtree instead of unrelated scattered zones.
    function matchRank(z, q) {
        var code = (z.code || '').toLowerCase();
        var name = (z.name || '').toLowerCase();
        if (code === q) return 0;
        if (code.indexOf(q + '-') === 0) return 1;   // segment boundary, not mid-segment
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

        // Toolbar: select / clear all filtered results in one tap. Useful after a
        // filter narrows the list (e.g. "1-1") — saves tapping each row. The button
        // reflects current state: if every filtered match is selected it clears,
        // otherwise it selects the rest.
        var selectedCount = matches.reduce(function (n, z) { return n + (_selectedZoneCodes.has(z.code) ? 1 : 0); }, 0);
        var allSelected = selectedCount === matches.length;
        var bar = document.createElement('div');
        bar.className = 'wo-zone-search-bar';
        bar.innerHTML = '<span class="wo-zsb-count">筛选 ' + matches.length + ' 项' +
            (selectedCount ? (' · 已选 ' + selectedCount) : '') + '</span>';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'wo-zsb-btn' + (allSelected ? ' clear' : '');
        btn.textContent = allSelected ? '清除全部' : '全选';
        btn.addEventListener('click', function () {
            matches.forEach(function (z) { toggleWoZone(z.code, !allSelected); });
            renderWoSearchResults();
            syncWoNameChipsState();
            updateInfoBarText();
        });
        bar.appendChild(btn);
        container.appendChild(bar);

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
        // Target whichever name-chips container is currently in use: the workorder's
        // (#woNameChips, inside v2WoSelectBar) or the water-request's (#wrNameChips,
        // inside v2DrawToolBar). They share the same selection set + popup logic; only
        // one toolbar is visible at a time, so prefer the visible/parent-shown one.
        var container = $('woNameChips');
        if (!container || !container.offsetParent) {
            container = $('wrNameChips') || container;
        }
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
                    // If ANYTHING in this land is selected (partial OR full), clear all of it;
                    // otherwise select all. Using "any selected" (not just "partial") is what
                    // makes the chip toggle off when you tap it again after a full select.
                    var c = countWoZones(function (z) { return z.land_id === land.id; });
                    var select = !(c.selected > 0);
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
        // Keep both the workorder (#woNameChips) and water-request (#wrNameChips)
        // land-chip states in sync after a selection change (popup close, etc.).
        document.querySelectorAll('#woNameChips .v2-chip[data-land-id], #wrNameChips .v2-chip[data-land-id]').forEach(function (chip) {
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
        else if (type === 'inventory') buildInventoryForm(data);
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

    // Build <option> elements for a date dropdown covering today + the previous
    // (days-1) days. Workers sometimes need to file a report for an earlier shift,
    // so the workorder/需求 forms expose the date instead of always using today.
    // Returns an HTML string of <option value="YYYY-MM-DD">weekday MM-DD</option>;
    // the option matching `defValue` (or today when omitted) is preselected.
    function dateOptionsHTML(days, defValue) {
        days = days || 7;
        var pad = function (n) { return String(n).padStart(2, '0'); };
        var wk = ['日', '一', '二', '三', '四', '五', '六'];
        var out = [];
        var base = new Date(); base.setHours(0, 0, 0, 0);
        var def = defValue || (base.getFullYear() + '-' + pad(base.getMonth() + 1) + '-' + pad(base.getDate()));
        for (var i = 0; i < days; i++) {
            var d = new Date(base); d.setDate(d.getDate() - i);
            var v = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
            var label = '周' + wk[d.getDay()] + ' ' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
            out.push('<option value="' + v + '"' + (v === def ? ' selected' : '') + '>' + label + '</option>');
        }
        return out.join('');
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
            '<form id="woModalForm" style="display:contents;"><input type="hidden" name="date" id="woDateHidden" value="' + data.today + '">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;"><span style="font-size:0.85em;color:#888;" id="woHeaderDate">' + data.today + ' ' + data.now_time + '</span><span style="font-size:0.85em;color:#888;">' + data.worker_name + '</span></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">日期</div><select name="wo_date" id="woDate" class="v2-select">' + dateOptionsHTML(7, data.today) + '</select></div><div style="flex:1.2;"><div class="v2-fl">班次</div><div class="v2-chip-group">' + shiftChips + '</div></div></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div style="flex:1.2;"><div class="v2-fl">灌溉组人数</div><input type="number" name="team_size" value="1" min="0" max="99" class="v2-input" style="text-align:center;"></div><div style="flex:1.2;"><div class="v2-fl">第三方人数</div><input type="number" name="third_party_count" value="0" min="0" max="99" class="v2-input" style="text-align:center;"></div></div><div id="woHours" style="margin-top:2px;font-size:0.85em;color:#888;"></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">开始时间</div><select name="work_start_time" id="woStart" class="v2-select"><option value="">--</option></select></div><div><div class="v2-fl">完成时间</div><select name="work_end_time" id="woEnd" class="v2-select"><option value="">--</option></select></div></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">工作类别</div><div id="woCatTrigger" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid #ddd;border-radius:8px;cursor:pointer;background:#fff;font-size:16px;"><span id="woCatDisplay" style="color:#bbb;">选择</span><span style="font-size:0.8em;color:#999;">▶</span></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">工作内容</div><div id="woContentTrigger" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid #ddd;border-radius:8px;cursor:pointer;background:#fff;font-size:16px;"><span id="woContentDisplay" style="color:#bbb;">选择</span><span style="font-size:0.8em;color:#999;">▶</span></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div style="flex:0.8;"><div class="v2-fl">待修</div><div class="v2-chip-group"><div class="v2-chip active" data-val=""><input type="radio" name="is_pending_repair" value="" style="display:none;" checked>否</div><div class="v2-chip" data-val="1"><input type="radio" name="is_pending_repair" value="1" style="display:none;">是</div></div></div><div style="flex:1.2;"><div class="v2-fl">疑难</div><div class="v2-chip-group"><div class="v2-chip active" data-val=""><input type="radio" name="is_difficult" value="" style="display:none;" checked>否</div><div class="v2-chip" data-val="1"><input type="radio" name="is_difficult" value="1" style="display:none;">是</div></div></div><div><div class="v2-fl">已处理</div><div class="v2-chip-group"><div class="v2-chip active" data-val=""><input type="radio" name="is_difficult_resolved" value="" style="display:none;" checked>否</div><div class="v2-chip" data-val="1"><input type="radio" name="is_difficult_resolved" value="1" style="display:none;">是</div></div></div></div></div>' +
            '<div class="v2-fg"><div class="v2-fl">备注</div><textarea name="remark" class="v2-textarea" placeholder="可选备注..." rows="2"></textarea></div>' +
            '<div class="v2-fg"><div class="v2-fl">照片/视频 (最多12个)</div><div class="v2-photo-area" id="woPhotoArea"><div class="v2-photo-add v2-photo-camera" id="woPhotoCamera" title="拍摄">📷</div><div class="v2-photo-add" id="woPhotoAdd" title="从相册选择">+</div></div><input type="file" id="woPhotoInput" accept="image/*,video/*" multiple style="display:none;"><input type="file" id="woPhotoCameraInput" accept="image/*,video/*" capture="environment" style="display:none;"></div>' +
            '<div class="v2-fg"><div class="v2-fl">材料消耗 / 出库 <span style="font-size:0.78em;color:#aaa;font-weight:400;">(可选，提交时扣减库存)</span></div><div id="woMatDestRow" style="display:none;margin-bottom:8px;"><div style="font-size:0.8em;color:#888;margin-bottom:4px;">出库去向 <span id="woMatDestAuto" style="color:#2D6A4F;"></span></div><div class="v2-chip-group" id="woMatDestChips"></div><div id="woMatDestProject" style="display:none;margin-top:6px;"></div><div id="woMatDestCp" style="display:none;margin-top:6px;"><input type="text" id="woMatDestCpInput" placeholder="借用方" class="v2-input" style="font-size:0.88em;"></div><div id="woMatDestOther" style="display:none;margin-top:6px;"><input type="text" id="woMatDestOtherInput" placeholder="请填写去向" class="v2-input" style="font-size:0.88em;"></div></div><div id="woMatCart"></div><button type="button" id="woMatAdd" style="margin-top:4px;width:100%;padding:9px;border:1px dashed #2D6A4F;border-radius:8px;background:#fff;color:#2D6A4F;font-size:0.9em;font-weight:600;cursor:pointer;">+ 添加材料</button><div id="woMatRecommend" style="display:none;margin-top:8px;"></div></div>' +
            '<input type="hidden" name="entries" id="woEntriesInput" value="[]"><input type="hidden" name="pm_resolved" id="woPmResolved" value=""><input type="hidden" name="materials" id="woMaterialsInput" value="[]"></form>' +
            '<div id="woCatModal" class="v2-sheet-overlay"><div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px 10px;border-bottom:1px solid #f0f0f0;flex-shrink:0;"><span style="font-weight:600;">选择工作类别</span><button type="button" onclick="document.getElementById(\'woCatModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div style="padding:16px;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;flex:1;min-height:0;"><div style="font-size:0.85em;color:#999;margin-bottom:6px;">类别</div><div class="v2-chip-group" id="woCatPrimary"></div><div id="woCatSubDivider" style="display:none;border-top:1px solid #e0e0e0;margin:12px 0;"></div><div id="woCatSubLabel" style="display:none;font-size:0.85em;color:#999;margin-bottom:6px;">子类别</div><div class="v2-chip-group" id="woCatSub"></div></div></div></div>' +
            '<div id="woTreeModal" class="v2-sheet-overlay"><div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f0f0f0;flex-shrink:0;"><span style="font-weight:600;">工作内容</span><button type="button" onclick="document.getElementById(\'woTreeModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div id="woBreadcrumb" class="v2-wo-bc"></div><div id="woSheetBody" style="flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;padding:8px 16px;min-height:0;"></div><div style="padding:12px 16px;border-top:1px solid #f0f0f0;flex-shrink:0;"><button type="button" onclick="document.getElementById(\'woTreeModal\').style.display=\'none\'" style="width:100%;padding:12px;border:none;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">完成</button></div></div></div>' +
            '<div id="woLeafModal" class="v2-sheet-overlay" style="z-index:4100;"><div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div><div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f0f0f0;flex-shrink:0;"><span id="woLeafTitle" style="font-weight:600;"></span><button type="button" onclick="document.getElementById(\'woLeafModal\').style.display=\'none\'" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div><div id="woLeafBody" style="padding:16px;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;flex:1;min-height:0;"></div><div style="padding:12px 16px;border-top:1px solid #f0f0f0;display:flex;gap:10px;flex-shrink:0;"><button type="button" onclick="document.getElementById(\'woLeafModal\').style.display=\'none\'" style="flex:1;padding:12px;border:1px solid #2D6A4F;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#fff;color:#2D6A4F;">取消</button><button type="button" id="woLeafConfirmBtn" style="flex:1;padding:12px;border:none;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">确定</button></div></div></div>';

        // Move the bottom-sheet popups to <body> so they escape the modal container's
        // `transform`. On iOS Safari a transformed ancestor turns position:fixed into
        // position:absolute (relative to that ancestor), so sheets nested in the modal
        // got clipped at the top and overlapped by the modal footer (提交/修改区域).
        // Re-opening rebuilds body.innerHTML (creating fresh sheet elements), but the
        // PREVIOUS open's sheets were reparented to <body> and survive — so remove
        // those stale orphans first to avoid duplicate IDs (which made 工作类别 chips
        // accumulate on each reopen).
        ['woCatModal', 'woTreeModal', 'woLeafModal'].forEach(function (id) {
            // Drop any stale sheet left on <body> from a prior open.
            var stale = document.body.querySelector('#' + id);
            if (stale && stale.parentNode === document.body) stale.remove();
            var el = document.getElementById(id);
            if (el) document.body.appendChild(el);
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

        // Back-date support: the visible date <select> drives the hidden `date`
        // input (what the server actually reads) and the header stamp so the
        // form shows the selected record date, not just "today now".
        var dateSel = $('woDate'), dateHidden = $('woDateHidden'), headerDate = $('woHeaderDate');
        function syncWoDate() {
            if (!dateSel) return;
            var v = dateSel.value;
            if (dateHidden) dateHidden.value = v;
            if (headerDate) headerDate.textContent = v + ' ' + (data.now_time || '');
        }
        if (dateSel) dateSel.addEventListener('change', syncWoDate);

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
        // Material consumption widget (材料消耗): catalog tree + cart + recommend.
        initWoMaterialWidget(data.inventory_tree || []);
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
                    _woEntries[only.id] = { count: 0, status: only.name, text_value: '', hasPhoto: false, project: only.is_project_scoped ? _woProject : null };
                    updateWoTrigger();
                }
            }
            var d = $('woCatDisplay');
            if (d) { d.textContent = sub ? (root.name + ' › ' + sub.name) : root.name; d.style.color = '#222'; }
            closeCatModal();
            if (typeof updateWoMatDest === 'function') updateWoMatDest();
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
            if (typeof updateWoMatDest === 'function') updateWoMatDest();
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
            catPrimary.innerHTML = '';   // clear any chips left from a prior open
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
        // Skip for edit mode — applyWoEditPrefill restores the original category
        // from the report's existing entries. Without this, re-saving an edited
        // report would silently flip its category to 日常维护.
        if (!_pendingEdit) {
            (function defaultCategory() {
                var rmRoot = null;
                for (var i = 0; i < _woRoots.length; i++) { if (_woRoots[i].section === 'routine_maint') { rmRoot = _woRoots[i]; break; } }
                var sub = null;
                if (rmRoot && rmRoot.children) {
                    // Match by code '1.2' (routine sub-category) rather than the
                    // Chinese display name, so a rename of 维保定期检查 won't break it.
                    for (var j = 0; j < rmRoot.children.length; j++) { if (rmRoot.children[j].code === '1.2') { sub = rmRoot.children[j]; break; } }
                }
                if (sub) {
                    _woCatNode = sub.id; _woProject = null;
                    var dd = $('woCatDisplay');
                    if (dd) { dd.textContent = rmRoot.name + ' › ' + sub.name; dd.style.color = '#222'; }
                    setContentVisible(true);
                    if (typeof updateWoMatDest === 'function') updateWoMatDest();
                }
            })();
        }
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
            var show = _photoFiles.length < 12;
            var add = $('woPhotoAdd'), cam = $('woPhotoCamera');
            if (add) add.style.display = show ? '' : 'none';
            if (cam) cam.style.display = show ? '' : 'none';
        }
        function addWoPhotoFiles(files) {
            Array.from(files).forEach(function (f) {
                if (_photoFiles.length >= 12) return;
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
            if (_photoFiles.length >= 12) return;
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

    // Set a form field's value by CSS selector (no-op if the element is missing).
    function setVal(sel, v) {
        var el = document.querySelector(sel);
        if (el) el.value = (v == null ? '' : v);
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

    // 计划性维修: two PM-only conveniences shown alongside the full 19-category tree.
    //   (1) "关联已有待修工单" — lists past 待修 workorders in the current zone,
    //       checkable; checked ids are sent as pm_resolved so the server clears them.
    //   (2) "其他（自行填写）" — free-text note folded into the PM entry's text_value.
    // These do NOT replace the category tree anymore — the tree (喷头/铰接/.../流量计
    // with count leaves, status groups and 待修 toggles) renders normally above them.
    // Tapping the PM rows drills into this dedicated resolution sub-view.
    function openWoPlannedSubView(node) {
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
        // Back to the 计划性维修 category tree (breadcrumb also works; this is the
        // obvious on-screen affordance on mobile).
        var html = '<button type="button" class="v2-wo-row" id="woPmBack" style="color:#2D6A4F;font-weight:600;">' +
            '<span class="v2-wo-rowname">‹ 返回计划性维修分类</span></button>';
        html += '<div class="v2-wo-ftitle">待修工单（该区域历史 · 勾选本次已处理）</div>';
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
        var back = $('woPmBack');
        if (back) back.addEventListener('click', function () { renderWoLevel(); });
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
        var isPlannedRoot = !!(cur && cur.name === '计划性维修');
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

        // 计划性维修 root: append two PM-only conveniences below the category tree.
        // These don't replace the 19 categories — they sit underneath them, and tapping
        // either drills into a dedicated resolution sub-view (openWoPlannedSubView) or
        // opens a free-text prompt. State lives in _woPlanned (shared with the sub-view).
        if (isPlannedRoot) {
            var pmChecked = Object.keys(_woPlanned.checked).length;
            html += '<div class="v2-wo-ftitle" style="margin-top:14px;">计划性维修专属</div>';
            html += '<button type="button" class="v2-wo-row" id="woPmLinkRow"><span class="v2-wo-rowname">关联已有待修工单' +
                '<small style="display:block;color:#999;font-size:0.78rem;">勾选本次已处理的历史待修</small></span>' +
                '<span class="v2-wo-rowval' + (pmChecked ? '' : ' empty') + '">' +
                (pmChecked ? ('已关联 ' + pmChecked) : '查看') + '</span></button>';
            html += '<button type="button" class="v2-wo-row" id="woPmOtherRow"><span class="v2-wo-rowname">其他（自行填写）</span>' +
                '<span class="v2-wo-rowval' + (_woPlanned.other ? '' : ' empty') + '">' +
                (_woPlanned.other ? escHtml(_woPlanned.other.slice(0, 8)) : '填写') + '</span></button>';
        }

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
        // 计划性维修 root: wire the two PM-only rows. "关联已有待修工单" drills into the
        // resolution sub-view; "其他" opens a free-text prompt. Both sync the PM entry
        // (a synthesized text marker on the 计划性维修 node) so it shows as filled.
        var pmNode = isPlannedRoot ? cur : null;
        var pmLink = $('woPmLinkRow');
        if (pmLink) pmLink.addEventListener('click', function () { openWoPlannedSubView(pmNode); });
        var pmOther = $('woPmOtherRow');
        if (pmOther) pmOther.addEventListener('click', function () {
            var v = prompt('其他计划性维修内容：', _woPlanned.other || '');
            if (v != null) { _woPlanned.other = v.trim(); syncPlannedEntry(pmNode); renderWoLevel(); }
        });
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
        // Keep the material recommend strip in sync with the work content.
        updateWoMatRecommend();
    }

    function collectWoEntries() {
        return Object.keys(_woEntries).map(function (id) {
            var e = _woEntries[id];
            return { work_item: parseInt(id, 10), project: e.project || null, count: e.count || 0, status: e.status || '', text_value: e.text_value || '' };
        });
    }

    // ── Material consumption widget (材料消耗 / 出库) for the workorder modal ──
    // Independent of the inventory modal's _invCart — kept in its own state so the
    // two modals never share a cart. Picks concrete SKUs from the full inventory
    // catalog (6 levels) via a drill-down sheet; a "recommend" strip surfaces SKUs
    // matching material keywords found in the filled work-content leaves.
    var _woMatCart = [];        // [{id, name, stock, min, quantity, unit}]
    var _woInvTree = [];        // cached inventory catalog
    var _woInvNodeMap = {};     // id -> node
    var _woInvAncestors = {};   // id -> [ancestor names]
    var _woMatKeywords = ['喷头','管','弯头','三通','阀箱','电磁阀','滴灌','接头','过滤器','取水阀','冲洗阀','调压器','控制线','通讯线'];

    function indexWoInvTree(nodes) {
        function walk(node, chain) {
            _woInvNodeMap[node.id] = node;
            _woInvAncestors[node.id] = chain.map(function (n) { return n.name || n.name_zh || ''; });
            var next = chain.concat([node]);
            (node.children || []).forEach(function (c) { walk(c, next); });
        }
        (nodes || []).forEach(function (r) { walk(r, []); });
    }
    function isWoMatLeaf(n) { return n.node_type === 'part' || (!n.children || !n.children.length); }

    function renderWoMatCart() {
        var box = $('woMatCart'); if (!box) return;
        if (!_woMatCart.length) { box.innerHTML = '<div style="font-size:0.82em;color:#aaa;padding:4px 0;">尚未添加材料</div>'; return; }
        box.innerHTML = '';
        _woMatCart.forEach(function (c, i) {
            var low = (c.min && c.stock <= c.min);
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:9px 10px;border:1px solid #e0e0e0;border-radius:8px;margin-bottom:6px;background:#fafafa;flex-wrap:wrap;';
            row.innerHTML =
                '<span style="flex:1 1 120px;min-width:0;font-size:0.86em;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _esc(c.label || c.name) + '</span>' +
                '<span style="font-size:0.72em;color:' + (low ? '#c0392b' : '#999') + ';white-space:nowrap;">库存 ' + c.stock + '</span>' +
                '<input type="number" min="1" step="1" class="wo-mat-qty" value="' + c.quantity + '" style="width:60px;padding:5px;border:1px solid #ddd;border-radius:6px;text-align:center;font-size:0.85em;">' +
                '<button type="button" class="wo-mat-del" style="border:none;background:transparent;color:#c0392b;font-size:1.1em;cursor:pointer;padding:0 4px;">✕</button>';
            var qi = row.querySelector('.wo-mat-qty'), db = row.querySelector('.wo-mat-del');
            qi.addEventListener('input', function () { c.quantity = parseFloat(qi.value) || 0; });
            db.addEventListener('click', function () { _woMatCart.splice(i, 1); renderWoMatCart(); if (typeof updateWoMatDest === 'function') updateWoMatDest(); });
            box.appendChild(row);
        });
    }
    // Build the display label "类别 › 子类 › 名称" from a leaf node (up to 2 ancestors).
    function _woMatLabel(node) {
        var anc = (_woInvAncestors[node.id] || []).slice(-2);
        var parts = anc.map(function (a) { return a; });
        parts.push(node.name || node.name_zh);
        return parts.join(' › ');
    }
    function addToWoMatCart(id) {
        var n = _woInvNodeMap[id];
        if (!n || !isWoMatLeaf(n)) return;
        if (_woMatCart.some(function (c) { return c.id === id; })) return;
        _woMatCart.push({ id: id, name: n.name || n.name_zh, label: _woMatLabel(n),
                          stock: n.current_stock || 0, min: n.min_stock || 0, quantity: 1 });
        renderWoMatCart();
        if (typeof updateWoMatDest === 'function') updateWoMatDest();
    }
    function collectWoMaterials() {
        return _woMatCart.filter(function (c) { return (c.quantity || 0) > 0; })
                         .map(function (c) { return { category: c.id, quantity: c.quantity }; });
    }
    function prefillWoMaterials(items) {
        _woMatCart = (items || []).map(function (m) {
            var n = _woInvNodeMap[m.category] || {};
            return { id: m.category, name: m.name || n.name || n.name_zh || ('#' + m.category),
                     label: m.name || _woMatLabel(n) || ('#' + m.category),
                     stock: n.current_stock || 0, min: n.min_stock || 0,
                     quantity: m.quantity || 1 };
        });
        renderWoMatCart();
        if (typeof updateWoMatDest === 'function') updateWoMatDest();
    }

    // Bottom-sheet drill-down (mirrors _invOpenTreeSheet, namespaced to wo).
    var _woMatPath = [];
    function openWoMatSheet(path) {
        _woMatPath = path || [];
        var level = _woInvTree;
        for (var i = 0; i < _woMatPath.length; i++) {
            var nn = _woInvNodeMap[_woMatPath[i]];
            if (!nn || !nn.children) { _woMatPath = _woMatPath.slice(0, i); break; }
            level = nn.children;
        }
        var sheet = $('woMatSheet');
        if (!sheet) {
            sheet = document.createElement('div');
            sheet.id = 'woMatSheet';
            sheet.className = 'v2-sheet-overlay';
            sheet.innerHTML = '<div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div>' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f0f0f0;flex-shrink:0;">' +
                '<span id="woMatSheetTitle" style="font-weight:600;"></span>' +
                '<button type="button" id="woMatSheetClose" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div>' +
                '<div id="woMatSheetBody" style="flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;touch-action:pan-y;padding:4px 0;min-height:0;"></div></div>';
            document.body.appendChild(sheet);
            sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.style.display = 'none'; });
            $('woMatSheetClose').addEventListener('click', function () { sheet.style.display = 'none'; });
        }
        $('woMatSheetTitle').textContent = _woMatPath.length
            ? _woMatPath.map(function (id) { var n = _woInvNodeMap[id]; return n.name || n.name_zh; }).join(' › ')
            : '选择材料';
        var body = $('woMatSheetBody');
        body.innerHTML = '';
        if (_woMatPath.length) {
            var back = document.createElement('button');
            back.type = 'button';
            back.style.cssText = 'display:flex;width:100%;padding:12px 16px;border:none;background:none;border-bottom:1px solid #f0f0f0;font-size:0.84em;color:#999;cursor:pointer;text-align:left;';
            back.textContent = '‹ 返回';
            back.addEventListener('click', function () { openWoMatSheet(_woMatPath.slice(0, -1)); });
            body.appendChild(back);
        }
        level.forEach(function (n) {
            var leaf = isWoMatLeaf(n);
            var row = document.createElement('button');
            row.type = 'button';
            row.style.cssText = 'display:flex;align-items:center;width:100%;padding:12px 16px;border:none;background:none;border-bottom:1px solid #f0f0f0;font-size:0.9em;color:#222;cursor:pointer;text-align:left;';
            row.innerHTML = '<span style="flex:1;">' + (leaf ? '🔹 ' : '📁 ') + _esc(n.name || n.name_zh) + '</span>' +
                (leaf ? '<span style="font-size:0.74em;color:#999;margin-left:8px;">库存 ' + (n.current_stock || 0) + '</span>' : '<span style="color:#999;font-size:0.8em;">▶</span>');
            row.addEventListener('click', function () {
                if (leaf) { addToWoMatCart(n.id); sheet.style.display = 'none'; }
                else openWoMatSheet(_woMatPath.concat([n.id]));
            });
            body.appendChild(row);
        });
        sheet.style.display = 'flex';
    }

    function updateWoMatRecommend() {
        var strip = $('woMatRecommend'); if (!strip) return;
        // Collect material keywords from the filled work-content leaves (name + ancestor path).
        var kws = {};
        Object.keys(_woEntries).forEach(function (id) {
            var e = _woEntries[id]; if (!e) return;
            var has = (e.count > 0) || !!e.status || !!(e.text_value) || e.hasPhoto;
            if (!has) return;
            var node = _woNodeById[id]; if (!node) return;
            var hay = (node.name || '') + ' ' + (node.section || '');
            // Walk ancestor chain for richer keyword context.
            var p = _woParentById[id];
            while (p) { hay += ' ' + (p.name || ''); p = _woParentById[p.id]; }
            _woMatKeywords.forEach(function (k) { if (hay.indexOf(k) >= 0) kws[k] = (kws[k] || 0) + 1; });
        });
        var kwList = Object.keys(kws);
        if (!kwList.length) { strip.style.display = 'none'; return; }
        var scored = [];
        Object.keys(_woInvNodeMap).forEach(function (id) {
            var n = _woInvNodeMap[id]; if (!isWoMatLeaf(n)) return;
            var hay = (n.name || n.name_zh || '') + ' ' + (_woInvAncestors[id] || []).join(' ');
            var hits = 0;
            kwList.forEach(function (k) { if (hay.indexOf(k) >= 0) hits++; });
            if (hits > 0) scored.push({ n: n, hits: hits });
        });
        if (!scored.length) { strip.style.display = 'none'; return; }
        scored.sort(function (a, b) { return b.hits - a.hits || String(a.n.name || a.n.name_zh).localeCompare(String(b.n.name || b.n.name_zh)); });
        var top = scored.slice(0, 8);
        strip.style.display = '';
        strip.innerHTML = '<div style="font-size:0.76em;color:#999;margin-bottom:5px;">根据工单内容推荐 <span style="font-size:0.9em;">💡</span></div><div style="display:flex;flex-wrap:wrap;gap:6px;">' +
            top.map(function (s) {
                // Inline label: "类别 › 子类 › 名称" (up to 2 ancestor levels) + stock.
                var anc = (_woInvAncestors[s.n.id] || []).slice(-2);
                var parts = anc.map(function (a) { return _esc(a); });
                parts.push(_esc(s.n.name || s.n.name_zh));
                var label = parts.join(' › ');
                return '<span class="wo-mat-rec-chip" data-id="' + s.n.id + '" style="font-size:0.78em;padding:5px 11px;border-radius:16px;background:#e8f5e9;color:#2D6A4F;cursor:pointer;">' + label +
                    '<small style="color:#888;font-size:0.68em;margin-left:4px;">库存' + (s.n.current_stock || 0) + '</small></span>';
            }).join('') + '</div>';
        strip.querySelectorAll('.wo-mat-rec-chip').forEach(function (ch) {
            ch.addEventListener('click', function () { addToWoMatCart(parseInt(ch.dataset.id, 10)); });
        });
    }

    // ── Material destination (出库去向) ──────────────────────────────────
    // Derived from the work category: routine_maint → 日常维护, project sections
    // → 项目 (auto-bound to the selected project), other categories → user picks
    // via chips (日常维护/项目[级联]/借用/其他). Mirrors the standalone inventory
    // form's OUTBOUND_DESTINATIONS so workorder-generated txns are consistent.
    var _woMatDest = { subtype: '', projectId: null, counterparty: '', other: '' };
    var PROJECT_SECTIONS_MAT = { irrigation_project: 1, drainage_project: 1, other_project: 1 };

    function updateWoMatDest() {
        var row = $('woMatDestRow'); if (!row) return;
        var autoEl = $('woMatDestAuto');
        // Only show the destination selector once the user has added at least
        // one material to the cart — there's nothing to assign a 去向 to otherwise.
        var hasMaterials = _woMatCart && _woMatCart.length > 0;
        if (!hasMaterials) { row.style.display = 'none'; return; }

        var node = _woCatNode ? _woNodeById[_woCatNode] : null;
        var section = node ? node.section : '';

        if (section && PROJECT_SECTIONS_MAT[section]) {
            // Project category: auto-bind to the selected project. Show the chips
            // (项目 pre-selected + the project name) so the user sees the binding,
            // but don't force them to pick.
            _woMatDest.subtype = '项目';
            _woMatDest.projectId = _woProject;
            if (autoEl) autoEl.textContent = '(已按工单项目自动绑定)';
        } else if (section === 'routine_maint') {
            // Routine maintenance: auto 日常维护. Show the chip pre-selected.
            _woMatDest.subtype = '日常维护';
            if (autoEl) autoEl.textContent = '(已按常规维护自动绑定)';
        } else {
            // Other categories: user picks. Default to 日常维护 if unset.
            if (!_woMatDest.subtype) {
                _woMatDest.subtype = '日常维护';
                _woMatDest.projectId = null; _woMatDest.counterparty = ''; _woMatDest.other = '';
            }
            if (autoEl) autoEl.textContent = '(请选择去向)';
        }
        row.style.display = '';
        renderWoMatDestChips();
    }

    function renderWoMatDestChips() {
        var box = $('woMatDestChips'); if (!box) return;
        var dests = ['日常维护', '项目', '借用', '其他'];
        box.innerHTML = dests.map(function (d) {
            var on = (_woMatDest.subtype === d) ? ' active' : '';
            return '<div class="v2-chip' + on + '" data-dest="' + d + '">' + d + '</div>';
        }).join('');
        box.querySelectorAll('.v2-chip').forEach(function (c) {
            c.addEventListener('click', function () {
                _woMatDest.subtype = c.dataset.dest;
                if (c.dataset.dest !== '项目') _woMatDest.projectId = null;
                if (c.dataset.dest !== '借用') _woMatDest.counterparty = '';
                if (c.dataset.dest !== '其他') _woMatDest.other = '';
                renderWoMatDestChips();
            });
        });
        // Conditional sub-fields.
        var projBox = $('woMatDestProject'), cpBox = $('woMatDestCp'), otherBox = $('woMatDestOther');
        if (projBox) {
            projBox.style.display = _woMatDest.subtype === '项目' ? '' : 'none';
            if (_woMatDest.subtype === '项目') {
                // Project cascade: category chips → project-name chips (reuse _woProjects).
                var cats = {};
                (_woProjects || []).forEach(function (p) { cats[p.category] = p.category_display || p.category; });
                var catList = Object.keys(cats);
                var curCat = _woMatDest.projectCat || catList[0];
                _woMatDest.projectCat = curCat;
                var projInCat = (_woProjects || []).filter(function (p) { return p.category === curCat; });
                var html = '<div style="font-size:0.78em;color:#999;margin-bottom:3px;">类别</div><div class="v2-chip-group" id="woMatDestProjCats">' +
                    catList.map(function (c) { return '<div class="v2-chip' + (c === curCat ? ' active' : '') + '" data-pcat="' + c + '">' + cats[c] + '</div>'; }).join('') + '</div>';
                html += '<div style="font-size:0.78em;color:#999;margin:6px 0 3px;">项目</div><div class="v2-chip-group" id="woMatDestProjNames" style="flex-wrap:wrap;">' +
                    projInCat.map(function (p) { return '<div class="v2-chip' + (p.id === _woMatDest.projectId ? ' active' : '') + '" data-pid="' + p.id + '">' + _esc(p.name) + '</div>'; }).join('') + '</div>';
                projBox.innerHTML = html;
                projBox.querySelectorAll('#woMatDestProjCats .v2-chip').forEach(function (c) {
                    c.addEventListener('click', function () { _woMatDest.projectCat = c.dataset.pcat; _woMatDest.projectId = null; renderWoMatDestChips(); });
                });
                projBox.querySelectorAll('#woMatDestProjNames .v2-chip').forEach(function (c) {
                    c.addEventListener('click', function () { _woMatDest.projectId = parseInt(c.dataset.pid, 10); renderWoMatDestChips(); });
                });
            }
        }
        if (cpBox) {
            cpBox.style.display = _woMatDest.subtype === '借用' ? '' : 'none';
            if (_woMatDest.subtype === '借用') {
                var cpInput = $('woMatDestCpInput');
                if (cpInput) { cpInput.value = _woMatDest.counterparty; cpInput.oninput = function () { _woMatDest.counterparty = cpInput.value; }; }
            }
        }
        if (otherBox) {
            otherBox.style.display = _woMatDest.subtype === '其他' ? '' : 'none';
            if (_woMatDest.subtype === '其他') {
                var oInput = $('woMatDestOtherInput');
                if (oInput) { oInput.value = _woMatDest.other; oInput.oninput = function () { _woMatDest.other = oInput.value; }; }
            }
        }
    }
    function collectWoMatDest() {
        // Returns the POST fields for the destination. The '其他' subtype sends
        // the typed text as entry_subtype; the server stores it verbatim.
        var d = _woMatDest;
        if (d.subtype === '其他') return { mat_dest: d.other || '其他', mat_project_id: '', mat_counterparty: '' };
        if (d.subtype === '借用') return { mat_dest: '借用', mat_project_id: '', mat_counterparty: d.counterparty };
        if (d.subtype === '项目') return { mat_dest: '项目', mat_project_id: d.projectId || '', mat_counterparty: '' };
        return { mat_dest: '日常维护', mat_project_id: '', mat_counterparty: '' };
    }

    function initWoMaterialWidget(invTree) {
        _woInvTree = invTree || [];
        _woInvNodeMap = {}; _woInvAncestors = {};
        indexWoInvTree(_woInvTree);
        _woMatCart = [];
        renderWoMatCart();
        var addBtn = $('woMatAdd');
        if (addBtn) addBtn.addEventListener('click', function () { openWoMatSheet([]); });
        updateWoMatRecommend();
    }

    function buildWaterRequestForm(data) {
        var body = $('wrModalBody'); if (!body) return;
        var typeChips = data.request_type_choices.map(function (item, i) {
            return '<div class="v2-chip modal-req-chip' + (i === 0 ? ' active' : '') + '" data-val="' + item[0] + '">' + item[1] + '</div>';
        }).join('');
        body.innerHTML = '<form id="wrModalForm" style="display:contents;">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;"><span style="font-size:0.85em;color:#888;">' + data.today + ' ' + data.now_time + '</span><span style="font-size:0.85em;color:#888;">' + data.user_name + '</span></div>' +
            '<div class="v2-fg"><div class="v2-fl">需求类型</div><div class="v2-chip-group">' + typeChips + '</div><input type="hidden" name="request_type" id="wrTypeInput" value="' + data.request_type_choices[0][0] + '"></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">开始日期</div><select name="start_date" id="wrStartDate" class="v2-select">' + dateOptionsHTML(7, data.today) + '</select></div><div><div class="v2-fl">结束日期</div><select name="end_date" id="wrEndDate" class="v2-select">' + dateOptionsHTML(7, data.today) + '</select></div></div></div>' +
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

    // Submit a PM extension request (field worker asks for more time).
    window.submitPmExtension = function () {
        if (!_pmGwoId) { showToast('无法确定工单', 'error'); return; }
        var dateEl = document.getElementById('pmExtDate');
        var reasonEl = document.getElementById('pmExtReason');
        var date = dateEl ? dateEl.value : '';
        var reason = reasonEl ? reasonEl.value.trim() : '';
        if (!date) { showToast('请选择延期日期', 'error'); return; }
        if (!reason) { showToast('请填写延期理由', 'error'); return; }
        var fd = new FormData();
        fd.append('requested_date', date);
        fd.append('reason', reason);
        fetch('/api/pm/' + _pmGwoId + '/extension/request/', {
            method: 'POST', body: fd,
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCSRFToken() }
        }).then(function(r) { return r.json(); }).then(function(d) {
            showToast(d.message, d.success ? 'success' : 'error');
            if (d.success) {
                var sec = document.getElementById('pmExtSection');
                if (sec) sec.innerHTML = '<div style="padding:6px;color:#40916C;font-size:.85rem;">✓ 延期申请已提交，等待经理审批</div>';
            }
        }).catch(function() { showToast('网络错误', 'error'); });
    };

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
            entries.push({ work_item: _woCatNode, project: _woProject || null, count: 0, status: '', text_value: '' });
        }
        var entriesInput = $('woEntriesInput'); if (entriesInput) entriesInput.value = JSON.stringify(entries);
        // Material consumption cart → JSON for the server (creates the outbound txn).
        var matInput = $('woMaterialsInput'); if (matInput) matInput.value = JSON.stringify(collectWoMaterials());
        var fd = new FormData(form); _photoFiles.forEach(function (f) { fd.append('report_photos', f); });
        // Material destination (出库去向) — auto-derived or user-picked.
        var dest = collectWoMatDest();
        fd.set('mat_dest', dest.mat_dest);
        if (dest.mat_project_id) fd.set('mat_project_id', dest.mat_project_id);
        if (dest.mat_counterparty) fd.set('mat_counterparty', dest.mat_counterparty);
        Object.keys(_woEntryPhotos).forEach(function (id) { _woEntryPhotos[id].forEach(function (f) { fd.append('ep_' + id, f); }); });
        // Edit mode: tell the server which report to update and which existing
        // photos the user removed.
        if (_editingReportId) {
            fd.append('report_id', _editingReportId);
            if (_photoRemove.size) fd.append('report_photos_remove', Array.from(_photoRemove).join(','));
        }
        // PMWorkOrder edit mode: send pm_order_id so the server updates the
        // existing PMWorkOrder instead of creating a WorkReport.
        if (_editingPmOrderId) {
            fd.append('pm_order_id', _editingPmOrderId);
            if (_photoRemove.size) fd.append('report_photos_remove', Array.from(_photoRemove).join(','));
        }
        // PM task completion (create mode): send the GWO id so the server builds
        // a PMWorkOrder and links it to this GeneratedWorkOrder.
        if (_pmGwoId) {
            fd.append('gwo_id', _pmGwoId);
        }
        var isSaving = !!(_editingReportId || _editingPmOrderId);
        var btn = $('woSubmitBtn'); btn.disabled = true; btn.textContent = (isSaving ? '保存' : '提交') + '中...';
        fetch('/mobile/workorder/v2/', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); }).then(function (data) {
                if (data.success) {
                    showToast(data.message, 'success');
                    btn.disabled = false; btn.textContent = '提交';
                    // PM task completion (create): after closing, navigate to the
                    // work-reports PM tab so the worker sees the task marked done.
                    if (_pmGwoId) {
                        setTimeout(function () {
                            closeV2Modal('workorder');
                            window.location.href = '/work-reports/?tab=pm';
                        }, 1500);
                    } else {
                        setTimeout(function () { closeV2Modal('workorder'); }, 1500);
                    }
                }
                else { showToast(data.message, 'error'); btn.disabled = false; btn.textContent = '提交'; }
            }).catch(function (err) { showToast('提交失败: ' + err, 'error'); btn.disabled = false; btn.textContent = '提交'; });
    };

    // ── Inventory modal (库存管理) ──
    // Multi-item cart of stock movements under one operation type (入库/出库/借用/归还).
    // Opens the form directly (no zone-first). Zone is optional.
    var _invCart = [];        // [{id, name, stock, quantity, unit}]
    var _invTree = [];        // cached catalog tree from API
    var _invNodeMap = {};     // id -> node (flat lookup over _invTree)
    var _invData = {};        // cached modal-data payload (operations/projects/borrowers)
    // Edit mode state. When set, submitV2Inventory sends txn_id so the server
    // updates the existing transaction instead of creating a new one.
    var _editingTxnId = null;

    function _invIndexTree(nodes) {
        nodes.forEach(function (n) {
            _invNodeMap[n.id] = n;
            if (n.children && n.children.length) _invIndexTree(n.children);
        });
    }

    function buildInventoryForm(data) {
        var body = $('invModalBody'); if (!body) return;
        _invTree = data.inventory_tree || [];
        _invNodeMap = {};
        _invIndexTree(_invTree);
        _invCart = [];
        _invData = data;  // cache for subtype/project/borrower lookups

        var ops = data.operations.map(function (o, i) {
            return '<div class="v2-chip inv-op-chip' + (i === 0 ? ' active' : '') + '" data-val="' + o.op + '">' + o.label + '</div>';
        }).join('');

        body.innerHTML =
            '<form id="invModalForm" style="display:contents;">' +
            '<input type="hidden" name="operation" id="invOpInput" value="' + data.operations[0].op + '">' +
            '<input type="hidden" name="entry_subtype" id="invSubInput" value="">' +
            '<input type="hidden" name="project_id" id="invProjInput" value="">' +
            '<input type="hidden" name="consumption_mode" id="invConsumeModeInput" value="actual">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;"><span style="font-size:0.85em;color:#888;">' + data.today + ' ' + data.now_time + '</span><span style="font-size:0.85em;color:#888;">' + data.worker_name + '</span></div>' +
            '<div class="v2-fg"><div class="v2-fl">操作类型</div><div class="v2-chip-group">' + ops + '</div></div>' +
            '<div class="v2-fg" id="invSubRow"><div class="v2-fl" id="invSubLabel">来源类型</div><div class="v2-chip-group" id="invSubChips"></div></div>' +
            '<div class="v2-fg"><div class="v2-form-row"><div><div class="v2-fl">日期</div><select name="date" id="invDate" class="v2-select">' + dateOptionsHTML(7, data.today) + '</select></div></div></div>' +
            '<div class="v2-fg" id="invOrderRow" style="display:none;"><div class="v2-fl">订单号</div><input type="text" name="order_no" id="invOrderNo" class="v2-input" list="invOrderList" placeholder="选择或输入采购订单号"><datalist id="invOrderList">' + (data.purchase_orders || []).map(function (o) { return '<option value="' + _esc(o) + '">'; }).join('') + '</datalist></div>' +
            '<div class="v2-fg" id="invProjCatRow" style="display:none;"><div class="v2-fl">项目类别</div><div class="v2-chip-group" id="invProjCatChips"></div><div class="v2-fl" style="margin-top:10px;">项目名称</div><div class="v2-chip-group" id="invProjNameChips"><div class="v2-chip" style="opacity:0.5;cursor:default;">先选类别</div></div></div>' +
            '<div class="v2-fg" id="invConsumeModeRow" style="display:none;"><div class="v2-fl">消耗类型</div><div class="v2-chip-group"><div class="v2-chip inv-cmode-chip active" data-val="actual">实际消耗</div><div class="v2-chip inv-cmode-chip" data-val="estimated">预估消耗</div></div><div style="font-size:0.72em;color:#999;margin-top:4px;" id="invCmodeHint">实际消耗提交后立即扣减库存；预估消耗仅作提醒，确认后才扣库存。</div></div>' +
            '<div class="v2-fg" id="invCpRow" style="display:none;"><div class="v2-fl">借用方</div><input type="text" name="counterparty" id="invCounterparty" class="v2-input" list="invBorrowerList" placeholder="选择或输入借用方"><datalist id="invBorrowerList">' + (data.borrowers || []).map(function (b) { return '<option value="' + _esc(b) + '">'; }).join('') + '</datalist></div>' +
            '<div class="v2-fg"><div class="v2-fl">物料清单</div>' +
                '<div id="invCartList"></div>' +
                '<div id="invAddTrigger" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px dashed #bbb;border-radius:8px;cursor:pointer;background:#fff;font-size:16px;margin-top:6px;"><span id="invAddLabel" style="color:#2D6A4F;">+ 添加物料</span><span style="font-size:0.8em;color:#999;">▶</span></div>' +
            '</div>' +
            '<div class="v2-fg"><div class="v2-fl">备注</div><textarea name="remark" class="v2-textarea" placeholder="可选备注..." rows="2"></textarea></div>' +
            '<input type="hidden" name="lines" id="invLinesInput" value="[]"></form>';

        injectCSRF(body.querySelector('form'));
        var sb = $('invSubmitBtn'); if (sb) { sb.disabled = false; sb.textContent = '提交'; }

        // Main operation selection (入库/出库) → rebuild subtype chips.
        document.querySelectorAll('.inv-op-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                document.querySelectorAll('.inv-op-chip').forEach(function (c) { c.classList.remove('active'); });
                chip.classList.add('active');
                $('invOpInput').value = chip.dataset.val;
                _invBuildSubtypes();
                _invSyncCondFields();
            });
        });

        // Build the project-category chips (cascade into project names on click).
        _invBuildProjectCategories();

        _invBuildSubtypes();
        _invSyncCondFields();

        // Consumption-mode toggle (实际/预估) — only relevant for 出库-项目.
        // Mirrors the op/sub chip pattern: single-select, writes to hidden input.
        document.querySelectorAll('.inv-cmode-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                document.querySelectorAll('.inv-cmode-chip').forEach(function (c) { c.classList.remove('active'); });
                chip.classList.add('active');
                $('invConsumeModeInput').value = chip.dataset.val;
            });
        });

        // Catalog tree picker (nested bottom sheet, opened by the add trigger).
        var addTrigger = $('invAddTrigger');
        if (addTrigger) addTrigger.addEventListener('click', function () { _invOpenTreeSheet([]); });

        _invRenderCart();
    }

    // Rebuild the subtype/destination chips based on the selected main operation.
    function _invBuildSubtypes() {
        var op = $('invOpInput') ? $('invOpInput').value : '';
        var opDef = (_invData.operations || []).find(function (o) { return o.op === op; }) || {};
        var subs = opDef.subtypes || [];
        $('invSubLabel').textContent = (op === '入库') ? '来源类型' : '去向';
        $('invSubInput').value = subs[0] || '';
        $('invSubChips').innerHTML = subs.map(function (s, i) {
            return '<div class="v2-chip inv-sub-chip' + (i === 0 ? ' active' : '') + '" data-val="' + s + '">' + s + '</div>';
        }).join('');
        document.querySelectorAll('.inv-sub-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                document.querySelectorAll('.inv-sub-chip').forEach(function (c) { c.classList.remove('active'); });
                chip.classList.add('active');
                $('invSubInput').value = chip.dataset.val;
                _invSyncCondFields();
            });
        });
    }

    // Build the project-category chips. Clicking a category cascades into the
    // project-name chip group below it (mirrors the subtype-chip pattern).
    function _invBuildProjectCategories() {
        var box = $('invProjCatChips');
        if (!box) return;
        box.innerHTML = (_invData.project_categories || []).map(function (c) {
            return '<div class="v2-chip inv-pcat-chip" data-val="' + _esc(c.code) + '">' + _esc(c.label) + '</div>';
        }).join('');
        document.querySelectorAll('.inv-pcat-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                document.querySelectorAll('.inv-pcat-chip').forEach(function (c) { c.classList.remove('active'); });
                chip.classList.add('active');
                _invBuildProjectNames(chip.dataset.val);
            });
        });
        // Reset the name group to its placeholder until a category is chosen.
        _invBuildProjectNames('');
    }

    // Populate the project-name chips for a chosen category.
    function _invBuildProjectNames(catCode) {
        var box = $('invProjNameChips'), inp = $('invProjInput');
        if (!box) return;
        inp.value = '';
        var matches = (_invData.projects || []).filter(function (p) { return p.category === catCode; });
        if (!catCode || !matches.length) {
            box.innerHTML = '<div class="v2-chip" style="opacity:0.5;cursor:default;">' +
                (catCode ? '该类别下无项目' : '先选类别') + '</div>';
            return;
        }
        box.innerHTML = matches.map(function (p) {
            return '<div class="v2-chip inv-pname-chip" data-val="' + p.id + '">' + _esc(p.name) + '</div>';
        }).join('');
        document.querySelectorAll('.inv-pname-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                document.querySelectorAll('.inv-pname-chip').forEach(function (c) { c.classList.remove('active'); });
                chip.classList.add('active');
                inp.value = chip.dataset.val;
            });
        });
    }

    // Show/hide conditional fields based on operation + subtype.
    function _invSyncCondFields() {
        var op = $('invOpInput') ? $('invOpInput').value : '';
        var sub = $('invSubInput') ? $('invSubInput').value : '';
        // 入库-采购 → 订单号; 出库-项目 → 项目级联; 出库-借用 → 借用方.
        if ($('invOrderRow')) $('invOrderRow').style.display = (op === '入库' && sub === '采购') ? '' : 'none';
        if ($('invProjCatRow')) $('invProjCatRow').style.display = (op === '出库' && sub === '项目') ? '' : 'none';
        if ($('invConsumeModeRow')) $('invConsumeModeRow').style.display = (op === '出库' && sub === '项目') ? '' : 'none';
        if ($('invCpRow')) $('invCpRow').style.display = (op === '出库' && sub === '借用') ? '' : 'none';
    }

    function _invRenderCart() {
        var box = $('invCartList'); if (!box) return;
        if (!_invCart.length) {
            box.innerHTML = '<div style="font-size:0.85em;color:#bbb;padding:8px 0;">尚未添加物料</div>';
            return;
        }
        box.innerHTML = _invCart.map(function (it, idx) {
            return '<div class="inv-cart-row" style="display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid #eee;border-radius:8px;margin-bottom:6px;">' +
                '<div style="flex:1;min-width:0;"><div style="font-size:0.9em;font-weight:500;">' + _esc(it.name) +
                '</div><div style="font-size:0.72em;color:#999;">当前库存: <b style="color:#444;">' + it.stock + '</b></div></div>' +
                '<input type="number" step="1" min="1" value="' + it.quantity + '" data-idx="' + idx + '" class="inv-qty-input" style="width:64px;padding:6px;border:1px solid #ddd;border-radius:6px;text-align:center;font-size:0.9em;">' +
                '<span style="width:48px;text-align:center;font-size:0.85em;color:#666;">' + _esc(it.unit || '—') + '</span>' +
                '<button type="button" data-idx="' + idx + '" class="inv-del-btn" style="background:#fee;border:none;border-radius:6px;width:28px;height:28px;color:#c0392b;cursor:pointer;font-size:0.9em;">×</button>' +
                '</div>';
        }).join('');
        box.querySelectorAll('.inv-qty-input').forEach(function (inp) {
            inp.addEventListener('input', function () { _invCart[this.dataset.idx].quantity = parseFloat(this.value) || 0; });
        });
        box.querySelectorAll('.inv-del-btn').forEach(function (btn) {
            btn.addEventListener('click', function () { _invCart.splice(this.dataset.idx, 1); _invRenderCart(); });
        });
    }

    function _esc(s) {
        var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML;
    }

    // Catalog drill-down sheet. `path` is the array of node ids walked so far.
    function _invOpenTreeSheet(path) {
        // Find the node at this depth.
        var nodes = _invTree;
        for (var i = 0; i < path.length; i++) {
            var parent = _invNodeMap[path[i]];
            nodes = (parent && parent.children) ? parent.children : [];
        }
        // Build (or reuse) a bottom sheet.
        var sheet = $('invTreeSheet');
        if (!sheet) {
            sheet = document.createElement('div');
            sheet.id = 'invTreeSheet';
            sheet.className = 'v2-sheet-overlay';
            sheet.innerHTML = '<div class="v2-sheet"><div style="width:36px;height:4px;background:#ccc;border-radius:2px;margin:10px auto 0;"></div>' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #f0f0f0;"><span id="invTreeTitle" style="font-weight:600;">选择物料</span><button type="button" id="invTreeClose" style="width:32px;height:32px;border:none;background:#f0f0f0;border-radius:50%;font-size:1.1em;cursor:pointer;">×</button></div>' +
                '<div id="invTreeBody" style="flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:8px 16px;min-height:0;"></div>' +
                '<div style="padding:8px 16px 12px;border-top:1px solid #f0f0f0;"><button type="button" id="invTreeDone" style="width:100%;padding:12px;border:none;border-radius:10px;font-size:0.95em;font-weight:600;cursor:pointer;background:#2D6A4F;color:#fff;">完成</button></div></div>';
            document.body.appendChild(sheet);
            $('invTreeClose').addEventListener('click', function () { sheet.style.display = 'none'; });
            $('invTreeDone').addEventListener('click', function () { sheet.style.display = 'none'; });
        }
        var title = $('invTreeTitle'), tbody = $('invTreeBody');
        // Title = breadcrumb of names.
        var names = path.map(function (id) { return _invNodeMap[id] ? _invNodeMap[id].name : ''; });
        title.textContent = names.length ? names.join(' › ') : '选择物料';

        tbody.innerHTML = '';
        if (!nodes.length) {
            tbody.innerHTML = '<div style="text-align:center;color:#999;padding:20px;">无子分类</div>';
        }
        nodes.forEach(function (n) {
            var isLeaf = n.node_type === 'part' || (!n.children || !n.children.length);
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:12px 10px;border-bottom:1px solid #f5f5f5;cursor:pointer;';
            row.innerHTML = '<span style="font-size:0.95em;">' + (isLeaf ? '🔹 ' : '📁 ') + _esc(n.name) +
                (isLeaf ? ' <span style="font-size:0.72em;color:#999;">库存 ' + (n.current_stock || 0) + '</span>' : '') + '</span>' +
                (isLeaf ? '<span style="font-size:0.8em;color:#2D6A4F;font-weight:600;">+ 选择</span>' : '<span style="color:#bbb;">▶</span>');
            row.addEventListener('click', function () {
                if (isLeaf) {
                    // Add to cart (skip if already present).
                    if (_invCart.some(function (c) { return c.id === n.id; })) {
                        showToast('该物料已在清单中', 'error');
                    } else {
                        _invCart.push({ id: n.id, name: n.name, stock: n.current_stock || 0, quantity: 1, unit: n.unit || '' });
                        _invRenderCart();
                    }
                    sheet.style.display = 'none';
                } else {
                    _invOpenTreeSheet(path.concat([n.id]));   // drill deeper
                }
            });
            tbody.appendChild(row);
        });

        // Back button if not at root.
        if (path.length) {
            var back = document.createElement('div');
            back.style.cssText = 'padding:8px 10px;color:#2D6A4F;font-size:0.85em;cursor:pointer;';
            back.textContent = '‹ 返回';
            back.addEventListener('click', function () { _invOpenTreeSheet(path.slice(0, -1)); });
            tbody.insertBefore(back, tbody.firstChild);
        }

        sheet.style.display = 'flex';
    }

    window.submitV2Inventory = function () {
        if (!_invCart.length) { showToast('请至少添加一个物料', 'error'); return; }
        var form = $('invModalForm'); if (!form) return;
        var lines = _invCart.filter(function (c) { return (c.quantity || 0) > 0; })
            .map(function (c) { return { category: c.id, quantity: c.quantity, unit: c.unit || '' }; });
        if (!lines.length) { showToast('请填写有效数量', 'error'); return; }
        $('invLinesInput').value = JSON.stringify(lines);
        var fd = new FormData(form);
        // Optional zone (only if the user associated one via 关联区域).
        if (_selectedZoneCodes.size) {
            fd.set('zone_id', Array.from(_selectedZoneCodes)[0]);  // inventory uses a single optional zone
        }
        // Edit mode: tell the server which transaction to update.
        var isEdit = !!_editingTxnId;
        if (isEdit) fd.append('txn_id', _editingTxnId);
        var btn = $('invSubmitBtn'); btn.disabled = true; btn.textContent = (isEdit ? '保存' : '提交') + '中...';
        fetch('/mobile/inventory/v2/', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); }).then(function (data) {
                if (data.success) {
                    showToast(data.message, 'success');
                    btn.disabled = false; btn.textContent = '提交';
                    _invCart = []; _editingTxnId = null;
                    setTimeout(function () { closeV2Modal('inventory'); }, 1500);
                } else {
                    showToast(data.message, 'error'); btn.disabled = false; btn.textContent = isEdit ? '保存' : '提交';
                }
            }).catch(function (err) { showToast('提交失败: ' + err, 'error'); btn.disabled = false; btn.textContent = isEdit ? '保存' : '提交'; });
    };

    window.submitV2WaterRequest = function () {
        var codes = Array.from(_selectedZoneCodes);
        if (codes.length === 0) { showToast('请在地图上绘制选择至少一个区域', 'error'); return; }
        var startTime = $('wrStart') ? $('wrStart').value : '', endTime = $('wrEnd') ? $('wrEnd').value : '';
        if (!startTime || !endTime) { showToast('请填写需求时间段', 'error'); return; }
        var form = $('wrModalForm'), fd = form ? new FormData(form) : new FormData();
        fd.set('zone_codes', JSON.stringify(codes));
        // Combine the separate start/end date selects with their times into full
        // datetimes for the server. Back-dating lets a user file a 需求 for a
        // span that already started; spans may cross midnight (start_date < end_date).
        var todayStr = new Date().toISOString().split('T')[0];
        var startDate = fd.get('start_date') || todayStr;
        var endDate = fd.get('end_date') || startDate;
        fd.set('start_datetime', startDate + 'T' + startTime);
        fd.set('end_datetime', endDate + 'T' + endTime);
        fd.delete('start_date'); fd.delete('end_date'); fd.delete('start_time'); fd.delete('end_time');
        var btn = $('wrSubmitBtn'); btn.disabled = true; btn.textContent = '提交中...';
        fetch('/mobile/water-request/v2/', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); }).then(function (data) {
                if (data.success) { showToast(data.message, 'success'); setTimeout(function () { closeV2Modal('water_request'); }, 1500); }
                else { showToast(data.message, 'error'); btn.disabled = false; btn.textContent = '提交'; }
            }).catch(function (err) { showToast('提交失败: ' + err, 'error'); btn.disabled = false; btn.textContent = '提交'; });
    };

    // Auto-open a modal in edit mode when the dashboard is reached via a
    // ?edit_workorder=<id> or ?edit_inventory=<id> link (from the work-reports
    // list / inventory ledger 编辑 buttons). Handles both "DOM still loading"
    // and "DOM already ready" cases.
    function runEditTrigger() {
        try {
            var params = new URLSearchParams(window.location.search);
            var woId = params.get('edit_workorder');
            if (woId && /^\d+$/.test(woId)) {
                // Small delay lets the map finish initializing so the zone summary
                // highlights correctly.
                setTimeout(function () { window.openV2ModalForEdit(woId); }, 600);
                return;
            }
            // PM task completion (create mode): ?pm_gwo_id=<id> opens the form
            // seeded to complete that GeneratedWorkOrder.
            var pmGwoId = params.get('pm_gwo_id');
            if (pmGwoId && /^\d+$/.test(pmGwoId)) {
                setTimeout(function () { window.openV2ModalForPm(pmGwoId); }, 600);
                return;
            }
            // PM task view/edit: ?pm_order_id=<id> opens the existing PMWorkOrder.
            var pmOrderId = params.get('pm_order_id');
            if (pmOrderId && /^\d+$/.test(pmOrderId)) {
                setTimeout(function () { window.openV2ModalForPmEdit(pmOrderId); }, 600);
                return;
            }
            var invId = params.get('edit_inventory');
            if (invId && /^\d+$/.test(invId)) {
                setTimeout(function () { window.openV2ModalForEditInv(invId); }, 600);
            }
        } catch (e) { /* URLSearchParams unsupported — no-op */ }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', runEditTrigger);
    } else {
        runEditTrigger();
    }

    // ── PM task list panel (dashboard FAB "PM安排") ───────────────────────
    // Reads the server-rendered #pm-tasks-data JSON (the logged-in worker's
    // crew dispatched/overdue PM tasks) and shows a lightweight overlay list.
    // Each row links to 去完成 (openV2ModalForPm) or 查看 (openV2ModalForPmEdit).
    window.openPmTaskPanel = function () {
        // Remove any existing panel first.
        var existing = document.getElementById('pmTaskPanel');
        if (existing) { existing.remove(); return; }
        var tasks = [];
        var el = document.getElementById('pm-tasks-data');
        if (el) { try { tasks = JSON.parse(el.textContent); } catch (e) {} }

        var overlay = document.createElement('div');
        overlay.id = 'pmTaskPanel';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:3100;background:rgba(0,0,0,0.4);display:flex;align-items:flex-end;justify-content:center;';
        overlay.addEventListener('click', function (e) { if (e.target === overlay) overlay.remove(); });

        var sheet = document.createElement('div');
        sheet.style.cssText = 'background:#fff;width:100%;max-width:560px;max-height:75vh;overflow-y:auto;border-radius:14px 14px 0 0;padding:14px 16px;';

        var header = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
            + '<h2 style="margin:0;font-size:1.05rem;color:#2D6A4F;">PM安排 <span id="pmPanelCount" style="color:#aaa;font-size:.8em;">(' + tasks.length + ')</span></h2>'
            + '<button onclick="document.getElementById(\'pmTaskPanel\').remove()" style="border:none;background:none;font-size:1.4rem;cursor:pointer;color:#999;">&times;</button>'
            + '</div>';

        // Frequency filter chips (derived from the task set).
        var freqs = [];
        tasks.forEach(function (t) {
            var f = t.freq_label || '其它';
            if (freqs.indexOf(f) === -1) freqs.push(f);
        });
        freqs.sort();
        var filterHtml = '';
        if (freqs.length > 1) {
            filterHtml = '<div id="pmFreqChips" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">'
                + '<button class="pmFreqChip" data-freq="" style="padding:3px 10px;border:1px solid #2D6A4F;border-radius:12px;background:#2D6A4F;color:#fff;font-size:.78rem;cursor:pointer;">全部</button>';
            freqs.forEach(function (f) {
                filterHtml += '<button class="pmFreqChip" data-freq="' + _esc(f) + '" style="padding:3px 10px;border:1px solid #cbd5e1;border-radius:12px;background:#fff;color:#475569;font-size:.78rem;cursor:pointer;">' + _esc(f) + '</button>';
            });
            filterHtml += '</div><div id="pmTableWrap"></div>';
        } else {
            filterHtml = '<div id="pmTableWrap"></div>';
        }

        function renderTable(freqFilter) {
            var filtered = tasks.filter(function (t) {
                return !freqFilter || (t.freq_label || '其它') === freqFilter;
            });
            var cnt = document.getElementById('pmPanelCount');
            if (cnt) cnt.textContent = '(' + filtered.length + ')';
            var html = '';
            if (!filtered.length) {
                html = '<p style="text-align:center;color:#aaa;padding:24px 0;">该频率下暂无工单</p>';
            } else {
                html = '<table style="width:100%;border-collapse:collapse;font-size:.88rem;"><thead><tr style="text-align:left;border-bottom:2px solid #e2e8f0;">'
                    + '<th style="padding:6px 4px;">作业计划</th><th style="padding:6px 4px;">到期日</th><th style="padding:6px 4px;">区域</th><th style="padding:6px 4px;"></th>'
                    + '</tr></thead><tbody>';
                filtered.forEach(function (t) {
                    var statusHtml = t.status === 'completed' ? '<span style="color:#40916C;">✓</span>'
                        : t.overdue ? '<span style="color:#dc2626;font-weight:600;">逾期</span>'
                        : '<span style="color:#d97706;">待办</span>';
                    var area = t.area_desc || (t.zone_count ? t.zone_count + ' zones' : '—');
                    var action;
                    if (t.pm_order_id) {
                        action = '<a href="javascript:void(0)" onclick="document.getElementById(\'pmTaskPanel\').remove();openV2ModalForPmEdit(' + t.pm_order_id + ')" style="color:#475569;text-decoration:none;font-size:.82rem;">查看</a>';
                    } else {
                        action = '<a href="javascript:void(0)" onclick="document.getElementById(\'pmTaskPanel\').remove();openV2ModalForPm(' + t.gwo_id + ')" style="color:#2D6A4F;font-weight:600;text-decoration:none;font-size:.82rem;">去完成</a>';
                    }
                    html += '<tr style="border-bottom:1px solid #f1f59;">'
                        + '<td style="padding:7px 4px;"><strong>' + _esc(t.job_plan_name) + '</strong><br><span style="font-size:.72em;color:#aaa;">' + _esc(t.ticket) + '</span></td>'
                        + '<td style="padding:7px 4px;">' + _esc(t.scheduled_date) + '<br>' + statusHtml + '</td>'
                        + '<td style="padding:7px 4px;font-size:.8rem;color:#555;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _esc(area) + '</td>'
                        + '<td style="padding:7px 4px;">' + action + '</td>'
                        + '</tr>';
                });
                html += '</tbody></table>';
            }
            var wrap = document.getElementById('pmTableWrap');
            if (wrap) wrap.innerHTML = html;
        }

        sheet.innerHTML = header + filterHtml;
        overlay.appendChild(sheet);
        document.body.appendChild(overlay);

        // Wire up chip clicks (toggle active + re-filter).
        var chips = sheet.querySelectorAll('.pmFreqChip');
        if (chips.length) {
            chips.forEach(function (chip) {
                chip.addEventListener('click', function () {
                    chips.forEach(function (c) {
                        c.style.background = '#fff'; c.style.color = '#475569'; c.style.borderColor = '#cbd5e1';
                    });
                    chip.style.background = '#2D6A4F'; chip.style.color = '#fff'; chip.style.borderColor = '#2D6A4F';
                    renderTable(chip.getAttribute('data-freq'));
                });
            });
        }
        // Initial render (all tasks).
        renderTable('');
    };

    function _esc(s) {
        var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML;
    }

})();
