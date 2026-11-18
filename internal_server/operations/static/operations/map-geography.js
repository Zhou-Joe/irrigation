/* Public park geography shared by the pest and landscaping maps. */
(function () {
    'use strict';
    const runtime = window.IrrigationMapRuntime;

    function afterZoom(map, action) {
        if (map.getPane('mapPane').classList.contains('leaflet-zoom-anim')) map.once('zoomend', action);
        else action();
    }

    function watermarks(map, baseSize = 25) {
        const pane = map.createPane('parkWatermarks');
        pane.style.zIndex = 410;
        pane.style.pointerEvents = 'none';
        const layer = L.layerGroup().addTo(map);
        let lands = [], areas = [];
        function draw() {
            layer.clearLayers();
            const zoom = map.getZoom(), detailed = zoom >= 19;
            const viewport = map.getBounds().pad(.15);
            const large = Math.min(48, Math.round(runtime.landLabelSize(zoom, baseSize) / 2));
            function drawLevel(items, level, size) {
                const occupied = [];
                for (const item of items) {
                    if (!runtime.withinPark(item.center) || !viewport.contains(item.center)) continue;
                    const p = map.latLngToContainerPoint(item.center);
                    const width = Array.from(item.name).length * size;
                    const box = {x: p.x - width / 2, y: p.y, w: width};
                    if (occupied.some(b => Math.abs(b.y - box.y) < size + 4 &&
                        box.x < b.x + b.w + 4 && b.x < box.x + width + 4)) continue;
                    occupied.push(box);
                    const label = document.createElement('span');
                    label.textContent = item.name;
                    label.style.fontSize = size + 'px';
                    label.style.transform = !detailed ? 'translate(-50%,-50%)'
                        : level === 'land' ? 'translate(-50%,-100%)' : 'translateX(-50%)';
                    L.marker(item.center, {
                        pane: 'parkWatermarks', interactive: false, keyboard: false,
                        icon: L.divIcon({className: 'park-watermark park-watermark-' + level,
                            html: label, iconSize: [0, 0], iconAnchor: [0, 0]})
                    }).addTo(layer);
                }
            }
            drawLevel(lands, 'land', large);
            if (detailed) drawLevel(areas, 'area', Math.round(large * .49));
        }
        // Leaflet emits moveend after zooming, panning and changes to map size.
        map.on('moveend', draw);
        return data => {
            lands = data.region_labels || [];
            areas = data.area_labels || [];
            draw();
        };
    }

    function pestViews(locations, geography) {
        const places = new Map(locations.map(p => [p.id, p]));
        const shapes = new Map(), direct = new Map(), children = new Map();
        const references = [...(geography.region_labels || []), ...(geography.area_labels || [])]
            .filter(label => runtime.withinPark(label.center));
        const named = new Map();
        for (const label of references) {
            const key = label.name.normalize('NFKC').trim().toLowerCase();
            if (!named.has(key)) named.set(key, []);
            named.get(key).push(label);
        }
        function reference(place) {
            const parent = places.get(place.parent_id);
            const name = place.name.normalize('NFKC').trim();
            const code = place.code || '';
            const names = [name];
            if (code && name.endsWith('(' + code + ')')) names.push(name.slice(0, -code.length - 2).trim());
            // The imported hotel directory uses H1, H2, … under HOTELS.
            if (parent?.code === 'HOTELS' && /^H[1-9]\d*$/.test(code)) names.push('酒店' + code.slice(1));
            for (const candidate of names) {
                const matches = named.get(candidate.toLowerCase()) || [];
                const match = matches.find(label => !Object.hasOwn(label, 'land')) ||
                    (matches.length === 1 ? matches[0] : matches.find(label => label.land === parent?.name));
                if (match) return {points: match.bounds?.every(runtime.withinPark) ? match.bounds : [match.center],
                    maxZoom: 17, reference: match.name};
            }
            return null;
        }
        for (const place of locations) {
            const rings = runtime.boundaryRings(place.boundary).filter(ring => ring.every(runtime.withinPark));
            const shape = window.FOSMapMarkers.presentation(place, rings);
            shapes.set(place.id, {rings, ...shape});
            if (shape.mode === 'boundary' || runtime.withinPark(shape.center)) {
                direct.set(place.id, {points: shape.mode === 'boundary' ? rings : [shape.center], maxZoom: 19});
            } else if (place.kind === 'zone' || place.kind === 'building') {
                const view = reference(place);
                if (view) direct.set(place.id, view);
            }
            if (!children.has(place.parent_id)) children.set(place.parent_id, []);
            children.get(place.parent_id).push(place);
        }
        function descendants(id, seen = new Set()) {
            if (seen.has(id)) return [];
            seen.add(id);
            return (children.get(id) || []).flatMap(child =>
                direct.get(child.id)?.points || descendants(child.id, seen));
        }
        function target(place) {
            const seen = new Set();
            for (let p = place; p && !seen.has(p.id); p = places.get(p.parent_id)) {
                seen.add(p.id);
                const view = direct.get(p.id);
                if (view) return p === place ? view : {...view, reference: view.reference || p.name, maxZoom: view.reference || p.kind === 'zone' ? 17 : view.maxZoom};
                const points = descendants(p.id);
                if (points.length) return {points, reference: p.name + '的已定位子地点', maxZoom: 17};
                if (p.code?.toLowerCase() === 'park' && p.name === '乐园') {
                    return {points: [runtime.parkView().center], reference: '园区总览', maxZoom: 16};
                }
            }
            return null;
        }
        return {shapes, target};
    }
    window.FOSMapGeography = {afterZoom, watermarks, pestViews};
})();
