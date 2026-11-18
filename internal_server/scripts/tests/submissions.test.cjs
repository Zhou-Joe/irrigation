const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname,'../../static/js/submissions.js'),'utf8');

function storage() {
    const data={};
    return {data,getItem:key=>data[key]??null,setItem:(key,value)=>data[key]=value,removeItem:key=>delete data[key]};
}
function harness({uid='7',responses=[],blockedStorage=false}={}) {
    const elements={},listeners={},calls=[],session=storage(),local=storage();
    function element() {return {setAttribute(){},style:{},dataset:{},children:[],append(){},after(){},prepend(){},
        replaceChildren(...children){this.children=children;},contains(child){return this.children.includes(child);},remove(){if(this.id)delete elements[this.id];}};}
    const document={querySelector:()=>({dataset:{userId:uid}}),getElementById:id=>elements[id]||null,
        createElement:element,createTextNode:text=>({textContent:text}),addEventListener:(name,fn)=>listeners[name]=fn,
        body:{append(el){elements[el.id]=el;}}};
    const window={fetch:async(input,init)=>{
        calls.push({input,init});const next=responses.shift();
        if(next instanceof Error)throw next;
        if(next instanceof Response)return next;
        return new Response(JSON.stringify(next||{success:true}),{headers:{'Content-Type':'application/json'}});
    }};
    if(blockedStorage)Object.defineProperty(window,'sessionStorage',{get(){throw new Error('blocked');}});
    else window.sessionStorage=session;
    const context={window,document,localStorage:local,location:{href:'https://field.invalid/',origin:'https://field.invalid'},
        URL,FormData,File,Response,Headers,crypto:webcrypto,Map,setTimeout,clearTimeout,Event};
    vm.runInNewContext(source,context);
    const submit=value=>{const body=new FormData();body.append('remark',value);
        return window.fetch('/mobile/inventory/v2/',{method:'POST',body});};
    return {window,calls,submit,session,local,listeners,elements};
}

test('lost response retry keeps its key; changed content waits for confirmation',async()=>{
    const h=harness({responses:[new Error('connection lost'),{success:true}]});
    await assert.rejects(h.submit('five items'));
    const conflict=await h.submit('nine items');
    assert.equal(conflict.status,409);assert.equal(h.calls.length,1);
    await h.submit('five items');
    assert.equal(h.calls[0].init.headers.get('X-Submission-Key'),h.calls[1].init.headers.get('X-Submission-Key'));
    assert.equal(JSON.parse(h.session.getItem('irrigation-submission-7-inventory')).state,'saved');
});
test('opening a new form after success creates a fresh operation',async()=>{
    const h=harness();await h.submit('same');const key=h.calls[0].init.headers.get('X-Submission-Key');
    h.window.IrrigationSubmissions.begin('inventory');await h.submit('same');
    assert.notEqual(h.calls[1].init.headers.get('X-Submission-Key'),key);
});
test('validation rejection allows a corrected submission',async()=>{
    const h=harness({responses:[{success:false,message:'invalid'},{success:true}]});
    await h.submit('fraction');await h.submit('integer');
    assert.equal(h.calls.length,2);
    assert.notEqual(h.calls[0].init.headers.get('X-Submission-Key'),h.calls[1].init.headers.get('X-Submission-Key'));
});
test('other origins and unrelated actions are not wrapped',async()=>{
    const h=harness();const body=new FormData();body.append('remark','fixture');
    await h.window.fetch('https://other.invalid/mobile/inventory/v2/',{method:'POST',body});
    assert.equal(h.calls[0].init.headers,undefined);assert.equal(Object.keys(h.session.data).length,0);
});
test('logout clears local text and submission receipts',async()=>{
    const h=harness();await h.submit('fixture');
    h.local.setItem('irrigation-text-draft-7-inventory','fixture');
    h.listeners.click({target:{closest:()=>({href:'https://field.invalid/logout/'})}});
    assert.equal(h.local.getItem('irrigation-text-draft-7-inventory'),null);
    assert.equal(h.session.getItem('irrigation-submission-7-inventory'),null);
});
test('blocked browser storage still permits same-page safe retry',async()=>{
    const h=harness({blockedStorage:true,responses:[new Error('lost'),{success:true}]});
    await assert.rejects(h.submit('fixture'));await h.submit('fixture');
    assert.equal(h.calls[0].init.headers.get('X-Submission-Key'),h.calls[1].init.headers.get('X-Submission-Key'));
});

function pestBody(team, token, remark='巡检') {
    const body=new FormData();
    for(const [key,value] of Object.entries({team,catalog:'8',submission_key:token,remark}))body.append(key,value);
    return {method:'POST',body};
}
test('two independent pest forms with identical values receive different durable keys', async()=>{
    const h=harness(),first=webcrypto.randomUUID(),second=webcrypto.randomUUID();
    for(const token of [first,second])await h.window.fetch('/mobile/workorder/v2/',pestBody('1',token));
    assert.deepEqual(h.calls.map(c=>c.init.headers.get('X-Submission-Key')),[first,second]);
});
test('a failed receipt lookup retains the block; a confirmed miss allows correction under the original key',async()=>{
    const h=harness({responses:[new Error('lost'),new Response('{}',{status:403}),{found:false},{success:true}]});
    await assert.rejects(h.submit('原内容'));
    const key=h.calls[0].init.headers.get('X-Submission-Key');
    const banner=h.elements.submissionUncertain;
    await banner.children[1].onclick();
    assert.match(banner.children[0].textContent,/核对失败/);
    assert.equal((await h.submit('已修改')).status,409);
    assert.equal(h.calls.length,2);
    await banner.children[1].onclick();
    assert.equal((await h.submit('已修改')).status,200);
    assert.equal(h.calls[3].init.headers.get('X-Submission-Key'),key);
});
test('an older unresolved pest submission follows its team and does not block other businesses', async()=>{
    const h=harness(),key=webcrypto.randomUUID();
    const old=pestBody('12',key);
    const signature=JSON.stringify([...old.body].filter(([name])=>name!=='submission_key'));
    h.session.setItem('irrigation-submission-7-workorder',JSON.stringify({key,signature,state:'uncertain'}));
    const endpoint='/mobile/workorder/v2/';
    await h.window.fetch(endpoint,pestBody('13',webcrypto.randomUUID(),'另一个团队'));
    const irrigation=new FormData();irrigation.append('remark','灌溉');
    await h.window.fetch(endpoint,{method:'POST',body:irrigation});
    assert.equal((await h.window.fetch(endpoint,pestBody('12',webcrypto.randomUUID(),'变更'))).status,409);
    await h.window.fetch(endpoint,old);
    assert.equal(h.calls.length,3);assert.equal(h.calls[2].init.headers.get('X-Submission-Key'),key);
});
