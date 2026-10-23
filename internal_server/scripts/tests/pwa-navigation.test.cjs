const {test}=require('node:test');
const assert=require('node:assert/strict');
const {create}=require('../../static/js/pwa-navigation.js');
const runtime=require('../../static/js/map-runtime.js');
function browser() {
    const items=new Map();const entries=[{url:'https://example.test/',state:null}];let index=0,goCalls=[],reloads=0;
    const win={sessionStorage:{getItem:k=>items.get(k)||null,setItem:(k,v)=>items.set(k,v),removeItem:k=>items.delete(k)},
        history:{get state(){return entries[index].state;},get length(){return entries.length;},replaceState(s){entries[index].state=s;},go(n){goCalls.push(n);index+=n;}},
        location:{get href(){return entries[index].url;},reload(){reloads++;}}};
    return {win,goCalls,entries,get reloads(){return reloads;},
        load(path){const ref=win.location.href;entries.splice(index+1);entries.push({url:new URL(path,ref).href,state:null});index++;return ref;}};
}
test('Map to Work to Stock to Map reuses the original map history entry',()=>{
    const h=browser();const map=create(h.win,'1','');
    assert.equal(map.navigate('/work-reports/'),false);
    const work=create(h.win,'1',h.load('/work-reports/'));
    assert.equal(work.navigate('/inventory/manage/'),false);
    const stock=create(h.win,'1',h.load('/inventory/manage/'));
    assert.equal(stock.navigate('/'),true);assert.deepEqual(h.goCalls,[-2]);
    map.resume();assert.equal(h.win.location.href,'https://example.test/');
    assert.equal(map.navigate('/'),true);assert.deepEqual(h.goCalls,[-2]);
});
test('unrelated navigation starts a new chain and never jumps to an unrelated history page',()=>{
    const h=browser();create(h.win,'1','');const work=create(h.win,'1',h.load('/work-reports/'));
    assert.equal(work.navigate('/'),false);assert.deepEqual(h.goCalls,[]);
    assert.equal(work.navigate('https://outside.test/'),false);
});
test('action URLs and account changes cannot reuse an old map form or another users page',()=>{
    const h=browser();const map=create(h.win,'1','');map.navigate('/?pm_gwo_id=3');
    const form=create(h.win,'1',h.load('/?pm_gwo_id=3'));
    assert.equal(form.navigate('/?action=workorder'),false);assert.deepEqual(h.goCalls,[]);
    create(h.win,'2',h.load('/app/'));map.resume();assert.equal(h.reloads,1);
});
test('blocked session storage falls back to ordinary links',()=>{
    const h=browser();h.win.sessionStorage.setItem=()=>{throw Error('blocked');};
    assert.equal(create(h.win,'1',''),null);
});
test('map view fallback accepts exact coordinates and rejects broken or out-of-range state',()=>{
    const storage={getItem:()=>JSON.stringify({center:[31.123456789,121.987654321],zoom:19})};
    assert.deepEqual(runtime.readView(storage,'map'),{center:[31.123456789,121.987654321],zoom:19});
    for (const raw of ['bad','null','{"center":[999,121],"zoom":19}','{"center":[31,121],"zoom":40}'])assert.equal(runtime.readView({getItem:()=>raw},'map'),null);
    assert.equal(runtime.readView({getItem(){throw Error('blocked');}},'map'),null);
});
