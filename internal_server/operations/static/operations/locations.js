(function () {
    'use strict';
    const el = document.querySelector('[data-location-map]');
    if (!el) return;
    const status = document.getElementById('opMapStatus');
    const map = L.map(el).setView([31.143, 121.658], 17);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Esri', maxZoom: 22, maxNativeZoom: 19
    }).addTo(map);
    const runtime = window.IrrigationMapRuntime;
    async function load() {
        status.textContent = '正在加载授权地点…';
        try {
            const data = await runtime.fetchJSON(el.dataset.endpoint, {cache: 'no-store'});
            const points = [];
            let count = 0;
            for (const location of data.locations) {
                if (el.dataset.location && el.dataset.location !== location.id) continue;
                const popup = document.createElement('a');
                popup.href = '/ops/locations/' + location.id + '/';
                popup.textContent = location.name + (location.code ? ' · ' + location.code : '');
                const rings = runtime.boundaryRings(location.boundary);
                if (rings.length) {
                    for (const ring of rings) {
                        L.polygon(ring, {color:'#2d6a4f', weight:2, fillOpacity:0.14}).bindPopup(popup.cloneNode(true)).addTo(map);
                        points.push(...ring);
                    }
                    count++;
                } else if (location.latitude !== null && location.longitude !== null) {
                    const p = runtime.point([location.latitude, location.longitude]);
                    if (p) {L.marker(p).bindPopup(popup).addTo(map); points.push(p); count++;}
                }
            }
            if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.15), {maxZoom:19});
            status.textContent = count ? '已显示 ' + count + ' 个地点的边界或定位点。' : '这些地点尚无边界或定位点，仍可从列表进入详情。';
        } catch (_) {
            status.textContent = '地图数据加载失败，请检查连接后刷新页面。';
        }
    }
    load();
})();
