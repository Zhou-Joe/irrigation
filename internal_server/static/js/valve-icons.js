/* Valve type is encoded by silhouette and a fixed glyph, independent of watering status. */
window.IrrigationValveIcons = (() => {
    const types = {
        solenoid:['电磁阀','S','#346190','50%'], qcv:['取水阀','Q','#007c72','2px'],
        gate:['闸阀','G','#974e1b','2px'], angle:['角阀','A','#67568e','3px'],
        washdown:['冲洗阀','W','#266b82','35%'], pullbox:['拉线箱','P','#575e67','0']
    };
    function options(type, {pending=false, watered=false, size=18}={}) {
        const [label,glyph,color,radius] = types[type] || ['未分类设备','?','#636363','3px'];
        const diamond = type === 'gate';
        const icon = L.divIcon({className:pending ? 'cad-pending-valve' : 'pipe-valve-marker',
            iconSize:[size,size], iconAnchor:[size/2,size/2],
            html:'<span aria-hidden="true" style="box-sizing:border-box;display:grid;place-items:center;width:100%;height:100%;font:bold 10px/1 sans-serif;border:2px '+(pending?'dashed':'solid')+' '+color+';border-radius:'+radius+';color:'+(watered?'white':color)+';background:'+(watered?'#216145':pending?'#ffedbd':'white')+';box-shadow:0 0 0 1px white;transform:rotate('+(diamond?45:0)+'deg)"><span style="transform:rotate('+(diamond?-45:0)+'deg)">'+glyph+'</span></span>'});
        return {icon,title:(pending?'待挂接 · ':'')+label,alt:label};
    }
    return {options,label:type=>types[type]?.[0] || '未分类设备'};
})();
