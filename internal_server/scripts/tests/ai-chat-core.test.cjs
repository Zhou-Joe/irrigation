const {test}=require('node:test');
const assert=require('node:assert/strict');
const core=require('../../static/js/ai-chat-core.js');
test('history reset follows Shanghai midnight using server timestamps, not device timezone',()=>{
    assert.equal(core.retentionDelay({server_now:'2026-10-26T15:59:59Z',expires_at:'2026-10-27T00:00:00+08:00'}),1000);
    assert.equal(core.retentionDelay({server_now:'2026-10-26T16:00:00Z',expires_at:'2026-10-27T00:00:00+08:00'}),0);
    assert.equal(core.retentionDelay({}),null);
});
test('SSE supports split CRLF frames, comments, multiple data lines and final tails',()=>{
    const events=[],p=core.createParser(e=>events.push(e));
    p.push(': heartbeat\r\ndata: {"event":"token",\r');p.push('\ndata: "text":"你好"}\r\n\r');p.push('\ndata: {"event":"done"}');p.finish();
    assert.deepEqual(events,[{event:'token',text:'你好'},{event:'done'}]);
});
test('broken SSE fails explicitly instead of silently leaving a spinner',()=>{
    assert.throws(()=>core.createParser(()=>{}).push('data: broken\n\n'),/回复数据不完整/);
});
test('parallel same-name tool results match IDs, including reversed completion order',()=>{
    const t=core.createTurn(0);core.applyEvent(t,{event:'tool_start',id:'a',name:'query_zones'},10);core.applyEvent(t,{event:'tool_start',id:'b',name:'query_zones'},20);
    core.applyEvent(t,{event:'tool_end',id:'b',name:'query_zones'},30);
    assert.equal(t.tools[0].status,'running');assert.equal(t.tools[1].status,'done');
    core.applyEvent(t,{event:'tool_end',id:'a',name:'query_zones'},40);assert.equal(t.tools[0].ended,40);
});
test('old name-only events complete one pending invocation at a time',()=>{
    const t=core.createTurn();for(let i=0;i<2;i++)core.applyEvent(t,{event:'tool_start',name:'same'});
    core.applyEvent(t,{event:'tool_end',name:'same'});assert.equal(t.tools.filter(x=>x.status==='running').length,1);
});
test('a finished, stopped or failed response ignores late output',()=>{
    for(const phase of ['stopped','error','done']) {
        const t=core.createTurn(0);core.applyEvent(t,{event:'token',text:'partial'},1);core.applyEvent(t,{event:'tool_start',name:'pending'},2);
        core.finishTurn(t,phase,'',3);core.applyEvent(t,{event:'token',text:'late'},4);
        assert.equal(t.text,'partial');assert.equal(t.tools[0].status,'interrupted');assert.equal(t.phase,phase);
    }
});
test('empty responses and tool errors have honest terminal states',()=>{
    const t=core.createTurn();core.applyEvent(t,{event:'tool_end',name:'python',output:'{"exit_code":1}'});assert.equal(t.tools[0].status,'error');
    core.applyEvent(t,{event:'done'});assert.equal(t.phase,'error');assert.match(t.error,/未返回内容/);
});
test('artifact URLs accept generated files only, and do not preview executable images',()=>{
    const origin='https://example.test';const good='/media/ai_workspaces/u4-abcd1234/chart.png';
    assert.equal(core.artifactInfo({url:good,size:2048},origin).kind,'image');
    for(const url of ['javascript:alert(1)','https://other.test'+good,'/media/other.png','/media/ai_workspaces/u4-abcd1234/%2e%2e/secret.png','/media/ai_workspaces/u4-abcd1234/a%2fb.png'])assert.equal(core.artifactInfo({url},origin),null);
    assert.equal(core.artifactInfo({url:good.replace('.png','.svg')},origin).kind,'file');
    assert.equal(core.safeLink('javascript:alert(1)',origin),null);assert.equal(core.safeLink(null,origin),null);
});
test('duplicate file events do not duplicate download cards; zero sizes remain valid',()=>{
    const t=core.createTurn();const file={event:'file',url:'/same',name:'a.csv'};core.applyEvent(t,file);core.applyEvent(t,file);
    assert.equal(t.files.length,1);assert.equal(core.formatBytes(0),'0 B');assert.equal(core.formatBytes(1024),'1.0 KB');
});
