const test=require('node:test'),assert=require('node:assert/strict');
const {draft,createSession}=require('../../operations/static/operations/map-location-create.js');
test('map point supplies coordinates; the worker only needs a name and optional type',()=>{
    const value=draft({name:' Visitor Centre '},[31.123456789,121.23456789]);
    assert.deepEqual(value,{name:'Visitor Centre',code:'',kind:'building',latitude:'31.1234568',longitude:'121.2345679'});
    for(const point of [null,[91,121],[31,NaN],['31',121]])assert.throws(()=>draft({name:'A'},point));
    assert.throws(()=>draft({name:''},[31,121]));
});
test('repeated placement creates separate drafts; failed identical submissions reuse their receipt',async()=>{
    let sequence=0,offline=true;const sent=[];
    const session=createSession({team:7,csrf:'test',uuid:()=>String(++sequence),send:async data=>{
        sent.push(Object.fromEntries(data));if(offline){offline=false;throw Error('offline');}
        return {ok:true,json:async()=>({success:true,ids:['location-'+sequence]})};
    }});
    const item={name:'A, "west"',kind:'building'};
    await assert.rejects(session.save(item,[31,121]));assert.equal(session.busy(),false);
    await session.save(item,[31,121]);assert.equal(sent[0].submission_key,sent[1].submission_key);
    assert.ok(sent[1].rows.includes('"A, ""west"""'));
    await session.save({name:'B',kind:'monitoring'},[32,122]);
    assert.notEqual(sent[1].submission_key,sent[2].submission_key);assert.equal(session.count(),2);
});
test('a save in progress cannot issue another location request',async()=>{
    let finish,calls=0;
    const session=createSession({team:7,csrf:'test',uuid:()=> 'receipt',send:async()=>{calls++;return new Promise(resolve=>{finish=()=>resolve({ok:true,json:async()=>({success:true,ids:['one']})});});}});
    const first=session.save({name:'A'},[31,121]);assert.equal(session.busy(),true);
    await assert.rejects(session.save({name:'B'},[32,122]));assert.equal(calls,1);
    finish();await first;assert.equal(session.busy(),false);
});
