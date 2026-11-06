const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const runtime=require('../../static/js/map-runtime.js');
test('map requests can bypass cached JSON and retain the response revision',async()=>{
    let request,revision;
    await runtime.fetchJSON('/api/zones-payload/',{cache:'no-store',
        fetcher:async(url,options)=>{request=options;return {ok:true,headers:{get:()=> 'new'},json:async()=>[]};},
        onResponse:r=>{revision=r.headers.get('X-Zone-Revision');}});
    assert.equal(request.cache,'no-store');assert.equal(revision,'new');
});
test('revision checks update changed geometry while leaving unchanged or hidden maps alone',async()=>{
    const code=fs.readFileSync(path.join(__dirname,'../../static/js/map.js'),'utf8');
    const part=code.slice(code.indexOf('async function checkZoneRevision()'),code.indexOf("window.addEventListener?.('pageshow'"));
    let loads=0,value='old';
    const ctx={map:{},zonesLoading:false,zoneRevisionChecking:false,zoneRevision:'old',document:{visibilityState:'visible'},
        runtime:{fetchJSON:async()=>({revision:value})},loadZones:()=>loads++,console};
    vm.runInNewContext(part,ctx);
    await ctx.checkZoneRevision();assert.equal(loads,0);
    value='new';await ctx.checkZoneRevision();assert.equal(loads,1);
    ctx.document.visibilityState='hidden';await ctx.checkZoneRevision();assert.equal(loads,1);
    ctx.document.visibilityState='visible';ctx.zonesLoading=true;await ctx.checkZoneRevision();assert.equal(loads,1);
});
