/* Pure map helpers shared by the dashboard and its regression tests. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.IrrigationMapRuntime = api;
})(typeof window !== 'undefined' ? window : this, function () {
    'use strict';
    function parkView() {
        return {center:[31.145663,121.655407],bounds:[[31.118663,121.623407],[31.172663,121.687407]],minZoom:15,maxZoom:22,maxBoundsViscosity:1};
    }
    function withinPark(value) {
        const p=point(value),b=parkView().bounds;
        return !!p&&p[0]>=b[0][0]&&p[0]<=b[1][0]&&p[1]>=b[0][1]&&p[1]<=b[1][1];
    }
    function landLabelSize(zoom,base=25) {
        const size=zoom<=16?base*5:zoom===17?base*3:Math.max(5,Math.round(base*Math.pow(.7,19-zoom)));
        return zoom<17?Math.round(size*.7):Math.max(Math.round(size*1.2),Math.round(base*3*1.2));
    }
    function point(value) {
        const lat = Array.isArray(value) ? value[0] : value?.lat;
        const lng = Array.isArray(value) ? value[1] : value?.lng;
        if (lat == null || lng == null || lat === '' || lng === '') return null;
        if (![lat,lng].every(v => (typeof v === 'number') || (typeof v === 'string' && v.trim() !== ''))) return null;
        const a = Number(lat), b = Number(lng);
        return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180 ? [a, b] : null;
    }
    function boundaryRings(boundary) {
        if (!Array.isArray(boundary)) return [];
        // Legacy ring, multiple rings, or nested CAD groups; empty leading
        // groups and malformed vertices must not discard other valid rings.
        if (boundary.some(value => point(value))) {
            const ring = boundary.map(point).filter(Boolean);
            return ring.length >= 3 ? [ring] : [];
        }
        return boundary.flatMap(boundaryRings);
    }
    function renderBatches(items, render, options = {}) {
        const frame = options.frame || (cb => requestAnimationFrame(cb));
        const now = options.now || (() => performance.now());
        const budget = options.budget ?? 8;
        const batchSize = options.batchSize ?? 40;
        let index = 0;
        return new Promise((resolve, reject) => {
            function next() {
                try {
                    const started = now();
                    let count = 0;
                    while (index < items.length && count < batchSize && (count === 0 || now() - started < budget)) {
                        render(items[index++]); count++;
                    }
                    options.progress?.(index, items.length);
                    if (index < items.length) frame(next);
                    else resolve();
                } catch (error) { reject(error); }
            }
            frame(next);
        });
    }
    function boundaryObjects(boundary) {
        // Drawing tools and their label centroids consume {lat,lng}, while
        // imported multi-ring CAD boundaries may contain numeric pairs.
        return boundaryRings(boundary).map(ring => ring.map(([lat,lng]) => ({lat,lng})));
    }
    function matchesPatch(zone, touched, selected) {
        if (!touched) return true;
        const id = zone.patchId ?? zone.patch_id;
        return id != null && selected.has(String(id));
    }
    async function fetchJSON(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), options.timeout ?? 30000);
        try {
            const response = await (options.fetcher || fetch)(url, { credentials:'same-origin', signal:controller.signal, cache:options.cache || 'default' });
            if (!response.ok) throw new Error('HTTP ' + response.status);
            options.onResponse?.(response);
            return await response.json();
        } finally { clearTimeout(timer); }
    }
    function requestLocation(geolocation) {
        function attempt(options) {
            return new Promise((resolve, reject) => geolocation.getCurrentPosition(resolve, reject, options));
        }
        return attempt({enableHighAccuracy:true, timeout:15000, maximumAge:30000}).catch(error => {
            // A fresh GPS fix can be unavailable indoors; permit the device's
            // normal location provider on retry, while respecting a denial.
            if (error.code !== 2 && error.code !== 3) throw error;
            return attempt({enableHighAccuracy:false, timeout:12000, maximumAge:60000});
        });
    }
    function readView(storage, key) {
        try {
            const value = JSON.parse(storage.getItem(key));
            const center = point(value?.center);
            return center && Number.isInteger(value.zoom) && value.zoom >= 15 && value.zoom <= 22 ? {center, zoom:value.zoom} : null;
        } catch (_) { return null; }
    }
    return { parkView, withinPark, landLabelSize, point, boundaryRings, boundaryObjects, renderBatches, matchesPatch, fetchJSON, requestLocation, readView };
});
