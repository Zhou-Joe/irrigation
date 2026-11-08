/* Shared typed map pins for new-team maps and location editors. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.FOSMapMarkers = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const types = {
        zone: {label:'室外区域', color:'#2d6a4f', path:'M4 20c0-10 4-16 16-16 0 12-6 16-16 16Zm0 0L15 9'},
        building: {label:'建筑', color:'#346fa0', path:'M4 21V3h12v18m0-10h4v10M2 21h20M8 7h4m-4 4h4m-4 4h4m-3 6v-3h2v3'},
        floor: {label:'楼层', color:'#5268a8', path:'m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5'},
        room: {label:'房间', color:'#8060a3', path:'M4 21h16M6 21V3h12v18M10 21V7h5v14m-2-7h.01'},
        monitoring: {label:'监测点', color:'#a76815', path:'M12 2v3m0 14v3M2 12h3m14 0h3', circle:true},
        other: {label:'其他地点', color:'#61736b', path:'M12 8v4m0 4h.01', outline:true},
    };
    const descriptor = kind => Object.prototype.hasOwnProperty.call(types, kind) ? types[kind] : types.other;
    function point(value) {
        const lat = Array.isArray(value) ? value[0] : value?.lat;
        const lng = Array.isArray(value) ? value[1] : value?.lng;
        if (lat == null || lng == null || lat === '' || lng === '') return null;
        if (![lat,lng].every(value=>typeof value === 'number' || (typeof value === 'string' && value.trim() !== ''))) return null;
        const a = Number(lat), b = Number(lng);
        return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180 ? [a,b] : null;
    }
    function presentation(location, rings) {
        const anchor = point([location.latitude,location.longitude]);
        let center = location.map_display === 'pin' ? anchor || point(location.center) : point(location.center) || anchor;
        if (!center && rings.length) {
            const points = rings.flat();
            center = [points.reduce((sum,p)=>sum+p[0],0)/points.length,points.reduce((sum,p)=>sum+p[1],0)/points.length];
        }
        return {mode:location.map_display !== 'pin' && rings.length ? 'boundary' : center ? 'pin' : 'none', center};
    }
    function glyph(kind, doc = document) {
        const type = descriptor(kind);
        const svg = doc.createElementNS('http://www.w3.org/2000/svg','svg');
        svg.setAttribute('viewBox','0 0 24 24'); svg.setAttribute('aria-hidden','true');
        svg.setAttribute('fill','none'); svg.setAttribute('stroke','currentColor');
        svg.setAttribute('stroke-width','1.8'); svg.setAttribute('stroke-linecap','round'); svg.setAttribute('stroke-linejoin','round');
        // Only predefined vector paths enter markup; names always use textContent.
        svg.innerHTML = '<path d="'+type.path+'"/>' + (type.circle ? '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/>' : '') +
            (type.outline ? '<circle cx="12" cy="12" r="9"/>' : '');
        return svg;
    }
    function marker(leaflet, location, center, doc = document) {
        const type = descriptor(location.kind);
        const body = doc.createElement('div'); body.className = 'op-pin-body'; body.style.color = type.color;
        const outline = doc.createElementNS('http://www.w3.org/2000/svg','svg');
        outline.setAttribute('viewBox','0 0 42 46'); outline.classList.add('op-pin-outline'); outline.setAttribute('aria-hidden','true');
        outline.innerHTML = '<path d="M21 44S4 29 4 19a17 17 0 1 1 34 0c0 10-17 25-17 25Z" fill="white" stroke="currentColor" stroke-width="2"/>';
        const symbol = glyph(location.kind,doc); symbol.classList.add('op-pin-symbol'); body.append(outline,symbol);
        const icon = leaflet.divIcon({className:'op-location-pin',html:body,iconSize:[42,46],iconAnchor:[21,44],popupAnchor:[0,-39],tooltipAnchor:[14,-25]});
        const name = location.name || type.label;
        const pin = leaflet.marker(center,{icon,title:type.label+' · '+name,alt:type.label+' · '+name,riseOnHover:true});
        const label = doc.createElement('span'); label.textContent = name;
        return pin.bindTooltip(label,{permanent:true,direction:'right',className:'op-location-label',opacity:1});
    }
    function enableLabels(map) {
        const update = () => map.getContainer().classList.toggle('op-labels-hidden',map.getZoom()<18);
        map.on('zoomend',update); update();
    }
    return {descriptor,presentation,glyph,marker,enableLabels};
});
