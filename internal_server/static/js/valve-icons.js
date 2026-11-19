/* Shared rendering for the map, editor handles and symbol previews. */
window.IrrigationValveIcons = (() => {
    const types = {
        solenoid:['电磁阀','S','#346190','50%'], qcv:['取水阀','Q','#007c72','2px'],
        gate:['闸阀','G','#974e1b','2px'], angle:['角阀','A','#67568e','3px'],
        washdown:['冲洗阀','W','#266b82','35%'], pullbox:['拉线箱','P','#575e67','0']
    };
    let library = {};
    const label = type => types[type]?.[0] || '未分类设备';
    function configure(shapes) { library = shapes || {}; }
    function markup(type, {pending=false, watered=false, orientation, shape=library[type]}={}) {
        const [,glyph,color,radius] = types[type] || ['未分类设备','?','#636363','3px'];
        if (shape?.paths?.length) {
            const angle = Number.isFinite(orientation?.angle) ? orientation.angle : 0;
            const offset = Number.isFinite(shape.offset) ? shape.offset : 0;
            const flip = orientation?.mirrored ? -1 : 1;
            const d = shape.paths.map(path => path.map(([x,y],i) =>
                (i ? 'L' : 'M') + Number(x) + ' ' + Number(y)).join(' ')).join(' ');
            const ring = pending || watered ? '<circle cx="32" cy="32" r="44" fill="'+(watered?'#216145':'#fff5d8')+'" stroke="'+color+'" stroke-width="4" '+(pending?'stroke-dasharray="8 6"':'')+'/>' : '';
            return '<svg aria-hidden="true" viewBox="-16 -16 96 96" width="100%" height="100%">'+ring+
                '<g transform="translate(32 32) rotate('+angle+') scale(1 '+flip+') rotate('+offset+') translate(-32 -32)" fill="none" stroke-linejoin="round" stroke-linecap="round">'+
                '<path d="'+d+'" stroke="'+(watered?color:'#fff')+'" stroke-width="11"/><path d="'+d+'" stroke="'+(watered?'#fff':color)+'" stroke-width="6"/></g></svg>';
        }
        const diamond = type === 'gate';
        return '<span aria-hidden="true" style="box-sizing:border-box;display:grid;place-items:center;width:100%;height:100%;font:bold 10px/1 sans-serif;border:2px '+(pending?'dashed':'solid')+' '+color+';border-radius:'+radius+';color:'+(watered?'white':color)+';background:'+(watered?'#216145':pending?'#ffedbd':'white')+';box-shadow:0 0 0 1px white;transform:rotate('+(diamond?45:0)+'deg)"><span style="transform:rotate('+(diamond?-45:0)+'deg)">'+glyph+'</span></span>';
    }
    function options(type, settings={}) {
        const pending = !!settings.pending, size = settings.size || 18;
        const icon = L.divIcon({className:pending ? 'cad-pending-valve' : 'pipe-valve-marker',
            iconSize:[size,size], iconAnchor:[size/2,size/2], html:markup(type,settings)});
        return {icon,title:(pending?'待挂接 · ':'')+label(type),alt:label(type)};
    }
    function legend(host) {
        if (!host) return;
        host.replaceChildren();
        for (const type of Object.keys(types)) {
            const icon = document.createElement('span');
            icon.style.cssText = 'display:inline-block;width:18px;height:18px;vertical-align:middle';
            icon.innerHTML = markup(type);
            host.append(icon,document.createTextNode(' '+label(type)+'　'));
        }
    }
    const detailZoom = 18;
    function syncLayer(map, layer, parent = map, enabled = true) {
        const visible = enabled && map.getZoom() >= detailZoom;
        if (visible && !parent.hasLayer(layer)) parent.addLayer(layer);
        if (!visible && parent.hasLayer(layer)) parent.removeLayer(layer);
    }
    return {detailZoom,syncLayer,options,label,configure,markup,legend};
})();
