(function () {
    'use strict';
    const byId = id => document.getElementById(id);
    const root = byId('greenMap');
    if (!root || !window.L) return;
    const runtime = window.IrrigationMapRuntime, park = runtime.parkView();
    const saved = window.FOSMapInitialView;
    const map = L.map(root, {preferCanvas:true, zoomControl:false, maxBounds:park.bounds,
        maxBoundsViscosity:park.maxBoundsViscosity, minZoom:park.minZoom, maxZoom:park.maxZoom})
        .setView(runtime.withinPark(saved?.center) ? saved.center : park.center,
            Math.max(park.minZoom, Math.min(park.maxZoom, saved?.zoom || 16)));
    window._map = map;
    L.control.zoom({position:'topright', zoomInTitle:'放大地图', zoomOutTitle:'缩小地图'}).addTo(map);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {maxZoom:22, maxNativeZoom:19, attribution:'Esri'}).addTo(map);
    const places = L.layerGroup().addTo(map), assets = L.layerGroup().addTo(map);
    const updateWatermarks = window.FOSMapGeography.watermarks(map);
    const phone = matchMedia('(max-width:768px)'), sidebar = byId('greenSidebar'), drawer = byId('greenDrawer');
    const trigger = byId('greenSidebarOpen'), close = byId('greenSidebarClose'), panel = byId('greenPanel');
    const form = byId('greenMapFilters'), list = byId('greenAssetList'), more = byId('greenMoreAssets');
    const status = byId('greenMapStatus'), pins = new Map();
    let generation = 0, stopped = false, filtered = [], shown = 0, desktopOpen = true;

    function syncSidebar() {
        sidebar.hidden = phone.matches || !desktopOpen;
        const expanded = phone.matches ? drawer.open : desktopOpen;
        trigger.hidden = expanded;
        trigger.setAttribute('aria-expanded', String(expanded));
        trigger.setAttribute('aria-controls', phone.matches ? drawer.id : sidebar.id);
    }
    function layout() {
        if (!phone.matches && drawer.open) drawer.close();
        (phone.matches ? drawer : sidebar).append(panel);
        syncSidebar();
    }
    function openSidebar() {
        if (phone.matches) drawer.showModal();
        else desktopOpen = true;
        syncSidebar();
        close.focus({preventScroll:true});
    }
    function closeSidebar() {
        if (phone.matches) drawer.close();
        else desktopOpen = false;
        syncSidebar();
        trigger.focus({preventScroll:true});
    }
    const imagery = window.FOSMapOverlays?.({map, prepareMap() {
        if (drawer.open) closeSidebar();
    }});
    trigger.onclick = openSidebar;
    close.onclick = closeSidebar;
    drawer.onclose = () => {
        syncSidebar();
        if (!stopped && phone.matches && !drawer.open) trigger.focus({preventScroll:true});
    };
    drawer.onclick = event => {
        if (event.target !== drawer) return;
        const rect = drawer.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right ||
            event.clientY < rect.top || event.clientY > rect.bottom) closeSidebar();
    };
    phone.addEventListener('change', layout);
    layout();
    const resize = new ResizeObserver(() => map.invalidateSize({animate:false}));
    resize.observe(root);

    function popup(item, url) {
        const box = document.createElement('div'), title = document.createElement('strong');
        title.textContent = item.code ? item.code + ' · ' + item.name : item.name;
        box.append(title);
        if (item.kind_label) {
            const line = document.createElement('div');
            line.textContent = item.kind_label;
            box.append(line);
        }
        if (url) {
            const link = document.createElement('a');
            link.href = url;
            link.textContent = '查看档案 ›';
            box.append(link);
        }
        return box;
    }
    function appendResults() {
        const end = Math.min(filtered.length, shown + 30);
        for (; shown < end; shown++) {
            const item = filtered[shown], pin = pins.get(item.id);
            const li = document.createElement('li'), row = document.createElement(pin ? 'button' : 'a');
            const title = document.createElement('strong'), detail = document.createElement('small');
            title.textContent = item.name;
            detail.textContent = [item.code, item.kind_label, pin ? '地图定位' :
                (runtime.point(item.center) ? '地图范围外 · 查看档案' : '待补充坐标 · 查看档案')].filter(Boolean).join(' · ');
            row.append(title, detail);
            if (pin) {
                row.type = 'button';
                row.onclick = () => {
                    if (phone.matches && drawer.open) closeSidebar();
                    window.FOSMapGeography.afterZoom(map, () => {
                        if (stopped || !assets.hasLayer(pin)) return;
                        map.setView(pin.getLatLng(), Math.max(map.getZoom(), 19), {animate:false});
                        pin.openPopup();
                    });
                };
            } else row.href = item.url;
            li.append(row);
            list.append(li);
        }
        if (!filtered.length) {
            const empty = document.createElement('li');
            empty.textContent = '暂无符合条件的档案';
            list.append(empty);
        }
        more.hidden = shown >= filtered.length;
    }
    more.onclick = appendResults;
    async function refresh() {
        const current = ++generation;
        status.textContent = '正在加载区域和植物档案…';
        try {
            const query = new URLSearchParams(new FormData(form));
            const data = await runtime.fetchJSON(root.dataset.endpoint + '?' + query, {cache:'no-store'});
            if (current !== generation) return;
            places.clearLayers();
            assets.clearLayers();
            pins.clear();
            updateWatermarks(data);
            for (const item of data.locations) {
                const rings = runtime.boundaryRings(item.boundary).filter(ring => ring.every(runtime.withinPark));
                if (item.map_display !== 'pin' && rings.length) {
                    for (const ring of rings) L.polygon(ring, {color:'#adc8b2', weight:1, fillOpacity:.08})
                        .bindPopup(popup(item)).addTo(places);
                } else if (runtime.withinPark(item.center)) {
                    L.circleMarker(item.center, {radius:5, color:'#557168', weight:2, fillColor:'#fff', fillOpacity:1})
                        .bindPopup(popup(item)).addTo(places);
                }
            }
            let missing = 0, outside = 0;
            filtered = data.assets;
            for (const item of filtered) {
                if (!runtime.point(item.center)) {missing++; continue;}
                if (!runtime.withinPark(item.center)) {outside++; continue;}
                const color = item.risk === 'high' ? '#b1483e' : item.kind === 'tree' ? '#37865c' : '#b48a48';
                const pin = L.circleMarker(item.center, {radius:item.kind === 'tree' ? 5 : 7, color:'#fff',
                    weight:1, fillColor:color, fillOpacity:.95}).bindPopup(popup(item, item.url)).addTo(assets);
                pins.set(item.id, pin);
            }
            shown = 0;
            list.replaceChildren();
            appendResults();
            status.textContent = '已显示 ' + pins.size + ' 个档案 · ' + missing + ' 个待补充坐标' +
                (outside ? ' · ' + outside + ' 个坐标在当前地图范围外' : '');
        } catch (error) {
            if (current === generation) status.textContent = '地图数据加载失败，请重新筛选重试。';
        }
    }
    const submit = event => {event.preventDefault(); refresh();};
    form.addEventListener('submit', submit);
    function destroy() {
        if (stopped) return;
        stopped = true;
        generation++;
        if (drawer.open) drawer.close();
        resize.disconnect();
        phone.removeEventListener('change', layout);
        form.removeEventListener('submit', submit);
        window.removeEventListener('pagehide', leave);
        imagery?.destroy();
        map.remove();
    }
    function leave(event) {if (!event.persisted) destroy();}
    window.addEventListener('pagehide', leave);
    window.FOSLandscapingMap = {refresh, destroy};
    refresh();
})();
