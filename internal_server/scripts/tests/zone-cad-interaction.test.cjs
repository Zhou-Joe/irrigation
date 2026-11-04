const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../core/templates/core/zone_dxf_import.html'),'utf8');
const script=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(x=>x[1]).find(x=>x.includes('(function()'));
function fixture(){
    const elements=new Map(),groups=[],polygons=[],events=new Map(),requests=[];
    function element(id){
        if(!elements.has(id))elements.set(id,{style:{},textContent:'[]',innerHTML:'',value:'',checked:false,disabled:false,handlers:{},
            classList:{add(){},remove(){}},addEventListener(name,fn){this.handlers[name]=fn;},setAttribute(k,v){this[k]=v;}});
        return elements.get(id);
    }
    element('all-drawn-zones-data').textContent=JSON.stringify([{code:'old-zone',name:'Old manual boundary',boundary_points:[{lat:31,lng:121},{lat:31.01,lng:121},{lat:31,lng:121.01}]}]);
    const map={layers:new Set(),handlers:{},on(name,fn){this.handlers[name]=fn;},getZoom(){return 20;},
        hasLayer(x){return this.layers.has(x);},addLayer(x){this.layers.add(x);},removeLayer(x){this.layers.delete(x);},fitBounds(){},
        mouseEventToLatLng(e){return {lat:31+e.clientY/100000,lng:121+e.clientX/100000};}};
    const L={map(){return map;},latLng(a,b){return [a,b];},latLngBounds(){return {extend(){}};},
        tileLayer(){return {addTo(){}};},divIcon(x){return x;},DomEvent:{stopPropagation(){}},
        layerGroup(){const group={layers:[],addTo(m){m.addLayer(this);return this;},clearLayers(){this.layers=[];}};groups.push(group);return group;},
        marker(){return {addTo(g){g.layers.push(this);return this;}};},
        polygon(rings,style){
            const poly={rings,style,events:{},el:element('polygon-'+polygons.length),
                addTo(g){g.layers.push(this);return this;},getElement(){return this.el;},on(n,fn){this.events[n]=fn;return this;},setStyle(){},
                getLatLngs(){return this.rings.map(r=>r.map(p=>({lat:p[0],lng:p[1]})));},setLatLngs(r){this.rings=r;}};
            polygons.push(poly);return poly;
        }};
    const shapes=[0,1].map(i=>({id:'shape_'+i,vertices_latlng:[{lat:31+i*.01,lng:121},{lat:31.001+i*.01,lng:121},{lat:31+i*.01,lng:121.001}]}));
    const upload={success:true,message:'Synthetic CAD',shapes,groups:shapes.map((s,i)=>({id:'group_'+i,outer:{id:s.id},holes:[]})),transformed:shapes,coord_info:{need_anchors:false,info:'Test'}};
    const document={cookie:'',getElementById:element,querySelectorAll(){return [];},
        addEventListener(n,fn){events.set(n,fn);},removeEventListener(n){events.delete(n);}};
    const ctx={console,document,L,setTimeout,FormData:class {constructor(){this.fields={};}append(k,v){this.fields[k]=v;}},
        fetch(_url,options){requests.push(options.body.fields);return Promise.resolve({json:async()=>options.body.fields.action==='upload_dxf'?structuredClone(upload):{success:true,zone_code:'demo',zone_name:'Demo',boundary_source:'dxf'}});}};
    ctx.window=ctx;vm.runInNewContext(script,ctx);
    const tick=()=>new Promise(resolve=>setImmediate(resolve));
    async function load(){element('dxfFileInput').files=[{}];element('dxfFileInput').handlers.change();await tick();}
    function down(poly){poly.el.handlers.mousedown({button:0,clientX:0,clientY:0,stopPropagation(){}});}
    function move(){events.get('mousemove')?.({clientX:20,clientY:30});}
    return {ctx,element,groups,events,map,requests,load,tick,down,move};
}
test('old boundaries and labels stay hidden until explicitly enabled, including after zoom',()=>{
    const f=fixture();assert.equal(f.groups[1].layers.length,0);assert.equal(f.map.hasLayer(f.groups[3]),false);
    f.element('showRefZones').checked=true;f.ctx.toggleReferenceZones();
    assert.equal(f.groups[1].layers.length,1);assert.equal(f.groups[1].layers[0].style.interactive,false);
    f.element('showRefZones').checked=false;f.ctx.toggleReferenceZones();f.map.handlers.zoomend();
    assert.equal(f.groups[1].layers.length,0);assert.equal(f.map.hasLayer(f.groups[3]),false);
});
test('CAD defaults to binding mode; movement requires explicit unlock and cancellation restores geometry',async()=>{
    const f=fixture();await f.load();const poly=f.groups[0].layers[0];
    const original=JSON.stringify(poly.rings);f.down(poly);f.move();assert.equal(JSON.stringify(poly.rings),original);
    f.ctx.setDxfMoveMode(true);f.down(poly);f.move();assert.notEqual(JSON.stringify(poly.rings),original);
    f.ctx.setDxfMoveMode(false);assert.equal(JSON.stringify(poly.rings),original);assert.equal(f.events.size,0);
    f.ctx.setDxfMoveMode(true);f.down(poly);f.move();f.events.get('mouseup')();
    const shifted=JSON.stringify(poly.rings);assert.notEqual(shifted,original);
    f.ctx.setDxfMoveMode(false);f.down(poly);f.move();assert.equal(JSON.stringify(poly.rings),shifted);
});
test('after assigning one zone the remaining batch cannot move or reset out of alignment',async()=>{
    const f=fixture();await f.load();f.ctx.selectGroup('group_0');f.element('zoneCodeInput').value='demo';
    f.ctx.assignSelectedShape();f.ctx.setDxfMoveMode(true);assert.equal(f.element('cadMoveMode').disabled,true);await f.tick();
    assert.equal(f.groups[0].layers.length,1);const poly=f.groups[0].layers[0],before=JSON.stringify(poly.rings);
    f.ctx.setDxfMoveMode(true);assert.equal(f.element('cadMoveMode').disabled,true);
    f.down(poly);f.move();f.ctx.resetDxfOffset();assert.equal(JSON.stringify(poly.rings),before);
    assert.equal(f.requests.at(-1).action,'assign_shape');
});
