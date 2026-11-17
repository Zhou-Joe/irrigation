(function () {
    'use strict';
    const root = document.getElementById('greenMap');
    if (!root || !window.L) return;
    const runtime = window.IrrigationMapRuntime, park = runtime.parkView();
    const map = L.map(root, {preferCanvas:true, maxBounds:park.bounds, maxBoundsViscosity:park.maxBoundsViscosity,
        minZoom:park.minZoom, maxZoom:park.maxZoom}).setView(runtime.withinPark(window.FOSMapInitialView?.center) ? window.FOSMapInitialView.center : park.center,
            Math.max(park.minZoom, Math.min(park.maxZoom, window.FOSMapInitialView?.zoom || 16)));
    window._map = map;
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {maxZoom:22, maxNativeZoom:19, attribution:'Esri'}).addTo(map);
    const places = L.layerGroup().addTo(map), assets = L.layerGroup().addTo(map), labels = L.layerGroup().addTo(map);
    let regionLabels = [], generation = 0;
    function drawLabels() {
        labels.clearLayers();
        const size = Math.min(22, 14 + (map.getZoom() - park.minZoom) * 2), occupied = [];
        for (const item of regionLabels) {
            if (!runtime.withinPark(item.center)) continue;
            const position = map.latLngToContainerPoint(item.center), width = item.name.length * size;
            const box = {left:position.x - width / 2 - 8, right:position.x + width / 2 + 8,
                top:position.y - size / 2 - 5, bottom:position.y + size / 2 + 5};
            if (occupied.some(other => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)) continue;
            occupied.push(box);
            const text = document.createElement('span');
            text.textContent = item.name;
            text.style.cssText = 'display:block;transform:translate(-50%,-50%);width:max-content;font-size:' + size + 'px;color:rgba(255,255,255,.48);font-weight:600;text-shadow:0 1px 3px rgba(0,0,0,.55);pointer-events:none';
            L.marker(item.center, {interactive:false, icon:L.divIcon({className:'zone-watermark', html:text.outerHTML, iconSize:[0,0]})}).addTo(labels);
        }
    }
    function popup(item, url) {
        const box = document.createElement('div'), title = document.createElement('strong');
        title.textContent = item.code ? item.code + ' · ' + item.name : item.name;
        box.append(title);
        if (item.kind_label) {const line = document.createElement('div'); line.textContent = item.kind_label; box.append(line);}
        if (url) {const link = document.createElement('a'); link.href = url; link.textContent = '查看档案 ›'; box.append(link);}
        return box;
    }
    async function refresh() {
        const current = ++generation, status = document.getElementById('greenMapStatus');
        status.textContent = '正在加载区域和植物档案…';
        try {
            const query = new URLSearchParams(new FormData(document.getElementById('greenMapFilters')));
            const data = await runtime.fetchJSON(root.dataset.endpoint + '?' + query, {cache:'no-store'});
            if (current !== generation) return;
            places.clearLayers(); assets.clearLayers(); regionLabels = data.region_labels || []; drawLabels();
            for (const item of data.locations) {
                const rings = runtime.boundaryRings(item.boundary).filter(ring => ring.every(runtime.withinPark));
                if (rings.length) L.polygon(rings, {color:'#adc8b2', weight:1, fillOpacity:.06}).bindPopup(popup(item)).addTo(places);
            }
            let positioned = 0, missing = 0, outside = 0;
            for (const item of data.assets) {
                if (!runtime.point(item.center)) {missing++; continue;}
                if (!runtime.withinPark(item.center)) {outside++; continue;}
                positioned++;
                const color = item.risk === 'high' ? '#b1483e' : item.kind === 'tree' ? '#37865c' : '#b48a48';
                L.circleMarker(item.center, {radius:item.kind === 'tree' ? 5 : 7, color:'#fff', weight:1, fillColor:color, fillOpacity:.95})
                    .bindPopup(popup(item, item.url)).addTo(assets);
            }
            status.textContent = '已显示 ' + positioned + ' 个档案 · ' + missing + ' 个待补充坐标' + (outside ? ' · ' + outside + ' 个坐标在当前地图范围外' : '');
        } catch (error) {if (current === generation) status.textContent = '地图数据加载失败，请重新筛选重试。';}
    }
    map.on('zoomend moveend resize', drawLabels);
    const form = document.getElementById('greenMapFilters');
    const submit = event => {event.preventDefault(); refresh();};
    form.addEventListener('submit', submit);
    let stopped = false;
    function destroy() {
        if (stopped) return;
        stopped = true; generation++; form.removeEventListener('submit', submit);
        window.removeEventListener('pagehide', leave); map.remove();
    }
    function leave(event) {if (!event.persisted) destroy();}
    window.addEventListener('pagehide', leave);
    window.FOSLandscapingMap = {refresh, destroy};
    refresh();
})();
