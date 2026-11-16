const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/inventory-quotes.js'), 'utf8');
function harness() {
    const window = {};
    // Supply reviewed-card states without a DOM; the production dispatcher and
    // intent parser run unchanged. Actual card submission is covered in browser QA.
    vm.runInNewContext(source.replace('window.EnGenieQuotes = {', 'window.__sessions = sessions; window.EnGenieQuotes = {'), {window, document:{}});
    let calls = 0;
    function card({threadId='current', key='quote-1', phase='review', result=null, confirmResult={success:true}, status='请先补全日期。'}={}) {
        const session = {threadId, key, phase, result, status, setEnabled(){}, confirm:async()=>{ calls++; return confirmResult; }};
        window.__sessions.add(session); return session;
    }
    return {api:window.EnGenieQuotes, card, get calls(){return calls;}};
}
test('only explicit confirmation phrases start a quote save', () => {
    const h = harness();
    for (const text of ['确认', '确认写入', '确认保存报价', '请更新价格记录。', '确定导入当前报价', 'confirm quotation', 'Please save this quote!']) assert.equal(h.api.isConfirmation(text), true, text);
    for (const text of ['不要确认写入', '还没有确认', '确认写入吗？', '请先分析报价', '如果我说确认写入会怎样', 'confirm?', 'do not save this quote', 'save this quote after changing it', '好的']) assert.equal(h.api.isConfirmation(text), false, text);
});
test('chat approval delegates to the current conversation reviewed card', async () => {
    const h = harness(); h.card();
    const result = await h.api.confirmFromChat('确认保存报价', 'current');
    assert.equal(h.calls, 1); assert.equal(result.success, true); assert.equal(result.submission_key, 'quote-1');
});
test('foreign conversations, cancelled cards and analysis questions never save', async () => {
    const h = harness(); h.card({threadId:'other'}); h.card({phase:'cancelled'});
    assert.equal(await h.api.confirmFromChat('确认写入','current'), null);
    assert.equal(await h.api.confirmFromChat('确认写入吗？','other'), null);
    assert.equal(h.calls, 0);
});
test('several pending vendor quotations require an explicit card choice', async () => {
    const h = harness(); h.card(); h.card({key:'quote-2'});
    const result = await h.api.confirmFromChat('确认写入','current');
    assert.equal(result.handled, true); assert.equal(result.success, false); assert.match(result.message,/多份/); assert.equal(h.calls,0);
});
test('missing fields and uncertain saves cannot be reported as success', async () => {
    for (const confirmResult of [null, {success:false,uncertain:true,message:'结果待确认'}]) {
        const h = harness(); h.card({confirmResult});
        const result = await h.api.confirmFromChat('确认写入','current');
        assert.equal(result.success,false); assert.equal(result.submission_key,null); assert.ok(result.message);
    }
});
test('saved results are reused and disabled business contexts never submit', async () => {
    const h = harness(); h.card({phase:'success', result:{success:true, prices_added:2}});
    const result = await h.api.confirmFromChat('确认写入','current');
    assert.equal(result.prices_added,2); assert.equal(h.calls,0);
    const blocked = harness(); blocked.card(); blocked.api.setEnabled(false);
    assert.equal(await blocked.api.confirmFromChat('确认写入','current'),null); assert.equal(blocked.calls,0);
});
