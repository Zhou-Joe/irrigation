/**
 * Dashboard UI Logic — sidebar filters, FAB menu, sync agent, plant filter
 * Extracted from core/templates/core/dashboard.html
 */
(function () {
    'use strict';
    var effects=window.FOSScopedEffects();

    // ── Zone Data ──
    // Kept as var at IIFE top level; also exposed on window for map.js
    var zonesData = window.zonesData || [];

    // ── Filter State (on window so map.js can read) ──
    // Empty set + touched=false -> show all. Click chip -> add to set + touched=true -> show only selected.
    window.activePriorities = new Set();
    window.activeLandmarks = new Set();
    window.activePatches = new Set();
    window.priorityFilterTouched = false;
    window.landmarkFilterTouched = false;
    window.patchFilterTouched = false;

    // Plant filter state (on window for map.js)
    window.activePlants = new Set();
    window.plantFilterTouched = false;

    // ── Landmark Map Cache ──
    var zoneLandmarkMapCache = null;

    function getZoneLandmarkMap() {
        if (!zoneLandmarkMapCache) {
            zoneLandmarkMapCache = JSON.parse(document.getElementById('zone-landmark-map').textContent);
            window._zoneLandmarkMap = zoneLandmarkMapCache;
        }
        return zoneLandmarkMapCache;
    }

    // ── Init Functions ──

    function initZoneData() {
        // Reuse the zones blob map.js already parsed (avoids a second ~5MB JSON.parse).
        if (window.zonesData) {
            zonesData = window.zonesData;
        } else {
            var dataEl = document.getElementById('zones-data');
            if (dataEl && dataEl.textContent.trim()) {
                zonesData = JSON.parse(dataEl.textContent);
                window.zonesData = zonesData;
            }
        }
        initZoneSidebarSearch();
        getZoneLandmarkMap();
    }

    function initPlantFilter() {
        var totalPlants = 0;
        document.querySelectorAll('.plant-check').forEach(function (cb) {
            window.activePlants.add(cb.dataset.plant);
            totalPlants++;
        });
        // Store for onPlantCheckChange
        window._totalPlants = totalPlants;
    }

    function initSyncAgent() {
        fetchAgentStatus();
        window._syncRefreshTimer = effects.interval(fetchAgentStatus, 5 * 60 * 1000);
    }

    function initMobileLayout() {
        // Mobile: start with sidebar collapsed
        if (window.innerWidth <= 768) {
            document.getElementById('sidebar').classList.add('collapsed');
            document.getElementById('sidebarExpandBtn').classList.add('visible');
        }
    }

    // ── Zone Sidebar Search ──

    function initZoneSidebarSearch() {
        var searchInput = document.getElementById('zoneSidebarSearch');
        var zoneList = document.getElementById('zoneSidebarList');

        if (!searchInput || !zoneList) return;

        searchInput.addEventListener('input', applySidebarFilters);
    }

    // ── Shared Zone-Item Filter Helper (deduplicated) ──

    function filterZoneItems(zoneItems, opts) {
        var query = opts.query;
        var patchName = opts.patchName || '';
        var regionName = opts.regionName || '';
        var pgPatchId = opts.pgPatchId || '';
        var ap = window.activePriorities || new Set();
        var apl = window.activePlants || new Set();
        var pt = window.plantFilterTouched || false;
        var al = window.activeLandmarks || new Set();
        var lt = window.landmarkFilterTouched || false;
        var apa = window.activePatches || new Set();
        var pat = window.patchFilterTouched || false;
        var prt = window.priorityFilterTouched || false;
        var zoneLmMap = opts.zoneLmMap;
        var visibleCount = 0;

        zoneItems.forEach(function (item) {
            var code = (item.dataset.zoneCode || '').toLowerCase();
            var name = (item.querySelector('.zone-name') ? item.querySelector('.zone-name').textContent : '').toLowerCase();
            var priority = item.dataset.priority || '';
            var plants = (item.dataset.plants || '').split(',').filter(Boolean);
            var patchId = item.dataset.patchId || pgPatchId;

            var matchText = !query || code.includes(query) || name.includes(query) || patchName.includes(query) || regionName.includes(query);
            var matchPriority = !prt || ap.has(priority);
            var matchPlant = !pt || plants.some(function (p) { return apl.has(p); });
            var matchLandmark = !lt || (function () {
                var lmNames = (zoneLmMap[item.dataset.zoneId] || []).map(function (l) { return l.name; });
                return lmNames.some(function (n) { return al.has(n); });
            })();
            var matchPatch = !pat || apa.has(patchId);

            var visible = matchText && matchPriority && matchPlant && matchLandmark && matchPatch;
            item.style.display = visible ? '' : 'none';
            if (visible) visibleCount++;
        });
        return visibleCount;
    }

    // ── Apply Sidebar Filters ──

    function applySidebarFilters() {
        var searchInput = document.getElementById('zoneSidebarSearch');
        var zoneList = document.getElementById('zoneSidebarList');
        var countEl = document.getElementById('zoneCount');
        if (!searchInput || !zoneList) return;

        var query = searchInput.value.toLowerCase().trim();
        var visibleCount = 0;

        var ap = window.activePriorities || new Set();
        var apl = window.activePlants || new Set();
        var pt = window.plantFilterTouched || false;
        var al = window.activeLandmarks || new Set();
        var lt = window.landmarkFilterTouched || false;
        var apa = window.activePatches || new Set();
        var pat = window.patchFilterTouched || false;
        var prt = window.priorityFilterTouched || false;

        var hasFilter = query || prt || pt || lt || pat;

        // Cache landmark map once
        var zoneLmMap = getZoneLandmarkMap();

        // Handle region groups
        zoneList.querySelectorAll('.region-group').forEach(function (regionGroup) {
            var regionNameEl = regionGroup.querySelector('.region-name');
            var regionName = regionNameEl ? regionNameEl.textContent.toLowerCase() : '';
            var regionVisible = false;

            regionGroup.querySelectorAll('.patch-group').forEach(function (patchGroup) {
                var patchNameEl = patchGroup.querySelector('.patch-name');
                var patchName = patchNameEl ? patchNameEl.textContent.toLowerCase() : '';
                var pgPatchId = patchGroup.dataset.patchId || '';
                var zoneItems = patchGroup.querySelectorAll('.zone-item');
                var patchVisible = false;

                var count = filterZoneItems(zoneItems, {
                    query: query,
                    patchName: patchName,
                    regionName: regionName,
                    pgPatchId: pgPatchId,
                    zoneLmMap: zoneLmMap
                });
                if (count > 0) {
                    patchVisible = true;
                    visibleCount += count;
                }

                patchGroup.style.display = patchVisible ? '' : 'none';
                if (hasFilter && patchVisible) {
                    patchGroup.classList.remove('collapsed');
                }
                if (patchVisible) regionVisible = true;
            });

            regionGroup.style.display = regionVisible ? '' : 'none';
            if (hasFilter && regionVisible) {
                regionGroup.classList.remove('collapsed');
            }
        });

        // Handle standalone patch groups (orphans outside region)
        zoneList.querySelectorAll(':scope > .patch-group').forEach(function (patchGroup) {
            var patchNameEl = patchGroup.querySelector('.patch-name');
            var patchName = patchNameEl ? patchNameEl.textContent.toLowerCase() : '';
            var pgPatchId = patchGroup.dataset.patchId || '';
            var zoneItems = patchGroup.querySelectorAll('.zone-item');
            var patchVisible = false;

            var count = filterZoneItems(zoneItems, {
                query: query,
                patchName: patchName,
                regionName: '',
                pgPatchId: pgPatchId,
                zoneLmMap: zoneLmMap
            });
            if (count > 0) {
                patchVisible = true;
                visibleCount += count;
            }

            patchGroup.style.display = patchVisible ? '' : 'none';
            if (hasFilter && patchVisible) {
                patchGroup.classList.remove('collapsed');
            }
        });

        if (hasFilter) {
            countEl.textContent = '找到 ' + visibleCount + ' 个区域';
        } else {
            countEl.textContent = zoneList.querySelectorAll('.zone-item').length + ' 个区域';
        }
    }

    // ── Map Filter Plugin Logic ──

    var PRIORITY_CHIPS = [
        { value: 'critical', label: '超级', cls: 'priority-critical' },
        { value: 'high', label: '重点', cls: 'priority-high' },
        { value: 'medium', label: '一般', cls: 'priority-medium' },
        { value: 'low', label: '次要', cls: 'priority-low' },
        { value: 'abolished', label: '废除', cls: 'priority-abolished' },
    ];

    var filterPanelOpen = false;

    function toggleFilterPanel() {
        var panel = document.getElementById('filterPanel');
        var btn = document.getElementById('filterToggleBtn');
        filterPanelOpen = !filterPanelOpen;
        if (filterPanelOpen) {
            renderFilterChips();
            panel.classList.add('open');
            btn.classList.add('active');
        } else {
            panel.classList.remove('open');
            btn.classList.remove('active');
        }
    }

    function renderFilterChips() {
        // Landmarks
        var lmChips = document.getElementById('landmarkChips');
        var dataEl = document.getElementById('landmarks-data');
        lmChips.innerHTML = '';
        if (dataEl && dataEl.textContent) {
            try {
                var landmarks = JSON.parse(dataEl.textContent);
                landmarks.forEach(function (lm) {
                    var active = window.activeLandmarks.has(lm.name);
                    var chip = document.createElement('span');
                    chip.className = 'filter-chip landmark-chip' + (active ? ' active' : '');
                    chip.textContent = lm.name;
                    chip.style.setProperty('--chip-color', lm.boundary_color || '#E8590C');
                    if (active) chip.style.background = lm.boundary_color || '#E8590C';
                    chip.onclick = function () { toggleFilterChip('landmark', lm.name, chip, lm.boundary_color); };
                    lmChips.appendChild(chip);
                });
            } catch (e) { /* ignore parse errors */ }
        }

        // Priority
        var prChips = document.getElementById('priorityChips');
        prChips.innerHTML = '';
        PRIORITY_CHIPS.forEach(function (pc) {
            var active = window.activePriorities.has(pc.value);
            var chip = document.createElement('span');
            chip.className = 'filter-chip ' + pc.cls + (active ? ' active' : '');
            chip.textContent = pc.label;
            chip.onclick = function () { toggleFilterChip('priority', pc.value, chip); };
            prChips.appendChild(chip);
        });

        // Patches
        var paChips = document.getElementById('patchChips');
        var patchEl = document.getElementById('patches-data');
        paChips.innerHTML = '';
        if (patchEl && patchEl.textContent) {
            try {
                var patches = JSON.parse(patchEl.textContent);
                patches.forEach(function (p) {
                    var pid = String(p.id);
                    var active = window.activePatches.has(pid);
                    var chip = document.createElement('span');
                    chip.className = 'filter-chip patch-chip' + (active ? ' active' : '');
                    chip.textContent = p.name || p.code;
                    chip.onclick = function () { toggleFilterChip('patch', pid, chip); };
                    paChips.appendChild(chip);
                });
            } catch (e) { /* ignore parse errors */ }
        }

        updateFilterBadge();

        // Staggered chip entrance animation
        requestAnimationFrame(function () {
            document.querySelectorAll('#filterPanel .filter-chip').forEach(function (chip, i) {
                chip.style.opacity = '0';
                chip.style.transform = 'translateY(6px) scale(0.85)';
                effects.timeout(function () {
                    chip.style.transition = 'opacity 0.35s cubic-bezier(0.22,1,0.36,1), transform 0.35s cubic-bezier(0.22,1,0.36,1)';
                    chip.style.opacity = '1';
                    chip.style.transform = '';
                }, 50 + i * 20);
            });
        });
    }

    function toggleFilterChip(layer, value, btn, chipColor) {
        var set, touchedKey;
        if (layer === 'landmark') {
            set = window.activeLandmarks;
            touchedKey = 'landmarkFilterTouched';
        } else if (layer === 'priority') {
            set = window.activePriorities;
            touchedKey = 'priorityFilterTouched';
        } else if (layer === 'patch') {
            set = window.activePatches;
            touchedKey = 'patchFilterTouched';
        }

        if (set.has(value)) {
            set.delete(value);
            btn.classList.remove('active');
            if (chipColor) btn.style.background = '';
        } else {
            set.add(value);
            btn.classList.add('active');
            if (chipColor) btn.style.background = chipColor;
        }

        // Empty set = no filter = show all
        window[touchedKey] = set.size > 0;

        updateFilterBadge();
        applyAllFilters();
    }

    function applyAllFilters() {
        applySidebarFilters();
        if (typeof window.applyMapFilters === 'function') {
            window.applyMapFilters();
        }
    }

    function clearAllFilters() {
        window.activePriorities = new Set();
        window.activeLandmarks = new Set();
        window.activePatches = new Set();
        window.priorityFilterTouched = false;
        window.landmarkFilterTouched = false;
        window.patchFilterTouched = false;

        renderFilterChips();
        updateFilterBadge();
        applyAllFilters();
    }

    function updateFilterBadge() {
        var btn = document.getElementById('filterToggleBtn');
        var qc = document.getElementById('filterQuickClear');
        var clearBtn = document.getElementById('filterClearBtn');
        var count = 0;
        if (window.landmarkFilterTouched) count++;
        if (window.priorityFilterTouched) count++;
        if (window.patchFilterTouched) count++;
        if (window.plantFilterTouched) count++;

        if (count > 0) {
            btn.classList.add('active');
            if (qc) qc.classList.add('visible');
            if (clearBtn) clearBtn.classList.add('visible');
        } else {
            btn.classList.remove('active');
            if (qc) qc.classList.remove('visible');
            if (clearBtn) clearBtn.classList.remove('visible');
        }
    }

    // Click outside to close filter panel
    effects.listen(document,'click', function (e) {
        var widget = document.getElementById('mapFilterWidget');
        if (filterPanelOpen && widget && !widget.contains(e.target)) {
            toggleFilterPanel();
        }
    });

    // Escape to close filter panel
    effects.listen(document,'keydown', function (e) {
        if (e.key === 'Escape' && filterPanelOpen) {
            toggleFilterPanel();
        }
    });

    // ── Map Layer Visibility Control ──

    function toggleLayerPanel() {
        var body = document.getElementById('mapLayerBody');
        var btn = document.getElementById('mapLayerToggleBtn');
        var isOpen = body.style.display !== 'none';
        body.style.display = isOpen ? 'none' : '';
        btn.classList.toggle('active', !isOpen);
    }

    function toggleLayer(layer, visible) {
        if (typeof window.setLayerVisibility === 'function') {
            window.setLayerVisibility(layer, visible);
        }
    }

    // ── Plant Filter ──

    function togglePlantDropdown() {
        var panel = document.getElementById('plantDropdownPanel');
        panel.classList.toggle('open');
    }

    function toggleAllPlants(checked) {
        document.querySelectorAll('.plant-check').forEach(function (cb) {
            cb.checked = checked;
            if (checked) window.activePlants.add(cb.dataset.plant);
            else window.activePlants.delete(cb.dataset.plant);
        });
        window.plantFilterTouched = !checked;
        updatePlantCount();
        applySidebarFilters();
        if (typeof window.applyMapFilters === 'function') {
            window.applyMapFilters();
        }
    }

    function onPlantCheckChange() {
        window.plantFilterTouched = true;
        window.activePlants.clear();
        document.querySelectorAll('.plant-check').forEach(function (cb) {
            if (cb.checked) window.activePlants.add(cb.dataset.plant);
        });
        var allChecked = window.activePlants.size === (window._totalPlants || 0);
        document.getElementById('plantSelectAll').checked = allChecked;
        if (allChecked) window.plantFilterTouched = false;
        updatePlantCount();
        applySidebarFilters();
        if (typeof window.applyMapFilters === 'function') {
            window.applyMapFilters();
        }
    }

    function updatePlantCount() {
        var el = document.getElementById('plantFilterCount');
        if (!el) return;
        var totalPlants = window._totalPlants || 0;
        if (!window.plantFilterTouched) el.textContent = '全部';
        else if (window.activePlants.size === 0) el.textContent = '无';
        else el.textContent = window.activePlants.size + '/' + totalPlants;
    }

    // Click outside to close plant dropdown
    effects.listen(document,'click', function (e) {
        var wrap = document.getElementById('plantDropdownBtn');
        wrap = wrap ? wrap.parentElement : null;
        if (wrap && !wrap.contains(e.target)) {
            var panel = document.getElementById('plantDropdownPanel');
            if (panel) panel.classList.remove('open');
        }
    });

    // ── Patch / Region Group Toggles ──

    function togglePatchGroup(header) {
        var patchGroup = header.closest('.patch-group');
        if (patchGroup) {
            patchGroup.classList.toggle('collapsed');
        }
    }

    function toggleRegionGroup(header) {
        var regionGroup = header.closest('.region-group');
        if (regionGroup) {
            regionGroup.classList.toggle('collapsed');
        }
    }

    // ── Sidebar Toggle ──

    function toggleSidebar() {
        var sidebar = document.getElementById('sidebar');
        var expandBtn = document.getElementById('sidebarExpandBtn');
        var overlay = document.getElementById('mobileOverlay');
        var isMobile = window.innerWidth <= 768;

        sidebar.classList.toggle('collapsed');
        if (sidebar.classList.contains('collapsed')) {
            expandBtn.classList.add('visible');
            if (overlay) overlay.classList.remove('visible');
        } else {
            expandBtn.classList.remove('visible');
            if (isMobile && overlay) overlay.classList.add('visible');
        }
        effects.timeout(function () { if (window._map) window._map.invalidateSize(); }, 300);
    }

    // ── Sync Agent Status ──

    var syncPanelOpen = false;

    function toggleSyncPanel() {
        syncPanelOpen = !syncPanelOpen;
        var panel = document.getElementById('syncStatusPanel');
        if (syncPanelOpen) {
            panel.classList.add('show');
            updateSyncPanel();
        } else {
            panel.classList.remove('show');
        }
    }

    function formatSyncTime(isoStr) {
        if (!isoStr) return '-';
        try {
            var d = new Date(isoStr);
            return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        } catch (e) { return isoStr; }
    }

    function formatElapsed(seconds) {
        if (seconds == null) return '-';
        if (seconds < 60) return seconds + ' 秒前';
        if (seconds < 3600) return Math.floor(seconds / 60) + ' 分钟前';
        return Math.floor(seconds / 3600) + ' 小时前';
    }

    function fetchAgentStatus() {
        var dot = document.getElementById('syncDot');
        var label = document.getElementById('syncLabel');
        var detail = document.getElementById('syncDetail');
        var refresh = document.getElementById('syncRefresh');

        fetch('/api/sync/agent-status')
            .then(function (resp) {
                if (!resp.ok) throw new Error('Failed');
                return resp.json();
            })
            .then(function (data) {
                // Update indicator
                dot.className = 'status-dot ' + (data.status === 'online' ? 'online' : data.status === 'offline' ? 'offline' : 'never_connected');

                if (data.status === 'online') {
                    label.textContent = '数据同步 · 已更新';
                    detail.textContent = '最近同步: ' + formatElapsed(data.seconds_since_heartbeat);
                } else if (data.status === 'offline') {
                    label.textContent = '数据同步 · 待检查';
                    detail.textContent = data.message || '最近导入: ' + formatElapsed(data.seconds_since_heartbeat);
                } else {
                    label.textContent = '数据同步 · 暂无记录';
                    detail.textContent = data.message || '等待下次备份导入';
                }

                refresh.textContent = new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit' });

                // Update panel if open
                if (syncPanelOpen) {
                    updateSyncPanelContent(data);
                }

                // Store data for panel
                window._syncAgentData = data;
            })
            .catch(function () {
                dot.className = 'status-dot offline';
                label.textContent = '数据同步 · 获取失败';
                detail.textContent = '无法获取状态';
                refresh.textContent = '!';
            });
    }

    function updateSyncPanel() {
        if (window._syncAgentData) {
            updateSyncPanelContent(window._syncAgentData);
        }
    }

    function updateSyncPanelContent(data) {
        if (data.mode === 'backup-import') {
            var box = document.getElementById('syncPanelContent'); box.replaceChildren();
            [['同步状态',data.message],['备份文件',data.source || '—'],['最近成功',data.last_heartbeat ? formatSyncTime(data.last_heartbeat) : '—']].forEach(function(pair){var row=document.createElement('p');row.textContent=pair[0]+'：'+pair[1];box.appendChild(row);});
            return;
        }
        var content = document.getElementById('syncPanelContent');
        var counts = data.last_sync_counts || {};
        var totalInserted = Object.values(counts).reduce(function (sum, v) {
            return sum + (v.inserted || 0) + (v.created || 0);
        }, 0);
        var totalUpdated = Object.values(counts).reduce(function (sum, v) {
            return sum + (v.updated || 0);
        }, 0);

        content.innerHTML =
            '<div class="sync-detail-row"><span class="label">连接状态</span><span class="value" style="color: ' + (data.status === 'online' ? '#40916C' : data.status === 'offline' ? '#9B2226' : '#888') + '">' + (data.status === 'online' ? '在线' : data.status === 'offline' ? '离线' : '未连接') + '</span></div>' +
            '<div class="sync-detail-row"><span class="label">最后心跳</span><span class="value">' + (data.last_heartbeat ? formatSyncTime(data.last_heartbeat) : '-') + '</span></div>' +
            '<div class="sync-detail-row"><span class="label">距上次同步</span><span class="value">' + formatElapsed(data.seconds_since_heartbeat) + '</span></div>' +
            (data.agent_version ? '<div class="sync-detail-row"><span class="label">代理版本</span><span class="value">' + data.agent_version + '</span></div>' : '') +
            '<div style="border-top: 1px solid var(--color-surface-dark); margin: 8px 0;"></div>' +
            '<div class="sync-detail-row"><span class="label">上次同步新增</span><span class="value">' + totalInserted + ' 条</span></div>' +
            '<div class="sync-detail-row"><span class="label">上次同步更新</span><span class="value">' + totalUpdated + ' 条</span></div>' +
            '<div style="border-top: 1px solid var(--color-surface-dark); margin: 8px 0;"></div>' +
            '<div class="sync-detail-row"><span class="label">自动刷新</span><span class="value">每 5 分钟</span></div>';
    }

    // ── Mobile FAB Menu ──

    function initFabMenu() {
        window.FOSMapActions.mount([
            {icon:'clipboard',label:'工单提交',action:()=>window.openV2Modal?.('workorder')},
            {icon:'calendar',label:'PM安排',action:()=>window.openPmTaskPanel?.()},
            {icon:'drop',label:'浇水需求',action:()=>window.openV2Modal?.('water_request')},
            {icon:'box',label:'库存管理',action:()=>window.openV2Modal?.('inventory')},
            {icon:'folder',label:'历史记录',url:window.HISTORY_URL||'#'}
        ]);
    }

    // ── Single DOMContentLoaded Listener ──

    function initializeDashboard() {
        initZoneData();
        initPlantFilter();
        initSyncAgent();
        initMobileLayout();
        initFabMenu();
    }
    if(document.readyState==='loading') effects.listen(document,'DOMContentLoaded',initializeDashboard,{once:true});else initializeDashboard();
    window.FOSDashboardLifecycle={destroy(){effects.destroy();window.FOSMapActions.destroy();}};

    // ── Expose Public API on window ──

    window.zonesData = zonesData;
    window.applyAllFilters = applyAllFilters;
    window.toggleFilterPanel = toggleFilterPanel;
    window.clearAllFilters = clearAllFilters;
    window.toggleLayerPanel = toggleLayerPanel;
    window.toggleLayer = toggleLayer;
    window.toggleSidebar = toggleSidebar;
    window.toggleSyncPanel = toggleSyncPanel;
    window.togglePlantDropdown = togglePlantDropdown;
    window.toggleAllPlants = toggleAllPlants;
    window.onPlantCheckChange = onPlantCheckChange;
    window.togglePatchGroup = togglePatchGroup;
    window.toggleRegionGroup = toggleRegionGroup;
    window.applySidebarFilters = applySidebarFilters;

})();
