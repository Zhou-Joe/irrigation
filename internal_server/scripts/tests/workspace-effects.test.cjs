const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
test('replacing a map component removes its global listeners and timers',()=>{
    const timers=new Map();let next=0,count=0;
    const ctx={window:{},setInterval:fn=>{timers.set(++next,fn);return next;},clearInterval:id=>timers.delete(id),setTimeout:fn=>{timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id)};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../operations/static/operations/map-actions.js'),'utf8'),ctx);
    const first=ctx.window.FOSScopedEffects(),target=new EventTarget();first.listen(target,'refresh',()=>count++);first.interval(()=>count++,1);
    target.dispatchEvent(new Event('refresh'));assert.equal(count,1);const stale=[...timers.values()][0];first.destroy();target.dispatchEvent(new Event('refresh'));stale();assert.equal(count,1);assert.equal(timers.size,0);
    const second=ctx.window.FOSScopedEffects();second.listen(target,'refresh',()=>count++);target.dispatchEvent(new Event('refresh'));assert.equal(count,2);second.destroy();
});
function requestsWith(fetch){
    const ctx={window:{fetch},AbortController};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../operations/static/operations/map-actions.js'),'utf8'),ctx);
    return ctx.window.FOSScopedRequests();
}
test('late form metadata is discarded after role change, while new requests still work',async()=>{
    let deliver;
    const requests=requestsWith(async()=>({json:()=>new Promise(resolve=>{deliver=resolve;})}));
    const old=await requests.fetch('/metadata');const pending=old.json();
    requests.reset();deliver({role:'manager'});await assert.rejects(pending,{name:'AbortError'});
    const current=await requests.fetch('/metadata');const fresh=current.json();deliver({role:'field'});assert.deepEqual(await fresh,{role:'field'});
});
test('submissions remain busy through response parsing and failures release the guard',async()=>{
    let deliver;
    const requests=requestsWith(async()=>({json:()=>new Promise(resolve=>{deliver=resolve;})}));
    const response=await requests.fetch('/submit',{method:'POST'});assert.equal(requests.busy(),true);
    const result=response.json();assert.equal(requests.busy(),true);deliver({success:true});await result;assert.equal(requests.busy(),false);
    const failing=requestsWith(async()=>{throw Error('offline');});
    await assert.rejects(failing.fetch('/submit',{method:'POST'}));assert.equal(failing.busy(),false);
});
test('disposed forms cancel reads and reject any new request',async()=>{
    let signal;
    const requests=requestsWith(async(url,options)=>{signal=options.signal;return {json:async()=>({})};});
    const response=await requests.fetch('/metadata');requests.destroy();assert.equal(signal.aborted,true);
    await assert.rejects(response.json(),{name:'AbortError'});await assert.rejects(requests.fetch('/metadata'),{name:'AbortError'});
});
