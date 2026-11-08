const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
test('replacing a map component removes its global listeners and timers',()=>{
    const timers=new Map();let next=0,count=0;
    const ctx={window:{},setInterval:fn=>{timers.set(++next,fn);return next;},clearInterval:id=>timers.delete(id),setTimeout:fn=>{timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id)};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../operations/static/operations/map-actions.js'),'utf8'),ctx);
    const first=ctx.window.FOSScopedEffects(),target=new EventTarget();first.listen(target,'refresh',()=>count++);first.interval(()=>count++,1);
    target.dispatchEvent(new Event('refresh'));assert.equal(count,1);const stale=[...timers.values()][0];first.destroy();target.dispatchEvent(new Event('refresh'));stale();assert.equal(count,1);assert.equal(timers.size,0);
    const second=ctx.window.FOSScopedEffects();second.listen(target,'refresh',()=>count++);target.dispatchEvent(new Event('refresh'));assert.equal(count,2);second.destroy();
});
