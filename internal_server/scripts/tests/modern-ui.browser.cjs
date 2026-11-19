/* Real browser regressions. Run with Playwright on NODE_PATH:
 * node --test internal_server/scripts/tests/modern-ui.browser.cjs
 * Loads isolated HTML fixtures directly into the browser. */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');
const assets = path.resolve(__dirname, '../../static');
let browser;
test.before(async () => {
    browser = await chromium.launch({channel: process.env.UI_TEST_BROWSER || 'chrome', headless: true});
});
test.after(async () => { await browser?.close(); });
async function fixture(t, html, options = {}) {
    const context = await browser.newContext({viewport: {width: 1100, height: 800}, ...options});
    t.after(() => context.close());
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    t.after(() => assert.deepEqual(errors, []));
    const htmlDocument = `<!doctype html><html lang="zh-CN"><head><style>
        body{font:16px system-ui}main{max-width:600px;margin:20px auto}input,select,textarea{box-sizing:border-box}
        .app-mask,.ann-popup{display:none;position:fixed;inset:0;align-items:center;justify-content:center;background:#0005}
        .app-mask.open{display:flex}.app-dialog,.ann-card{background:white;padding:20px;width:400px}
        .wr-detail{display:none}.wr-card.open .wr-detail{display:block}
        .v2-modal-container{position:fixed;top:100px;left:100px;background:white;padding:20px}
    </style></head><body class="ui-system"><main>${html}</main></body></html>`;
    await page.goto('data:text/html;charset=utf-8,' + encodeURIComponent(htmlDocument), {waitUntil:'commit', timeout:30000});
    const loaded = await page.evaluate(async () => {
        if (document.readyState === 'loading') {
            await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, {once:true}));
        }
        return Boolean(document.querySelector('main'));
    });
    assert.ok(loaded, 'The browser did not load the fixture document');
    await page.addStyleTag({path: path.join(assets, 'css/modern-ui.css')});
    return {page, context, async start() { await page.addScriptTag({path: path.join(assets, 'js/modern-ui.js')}); }};
}
test('validation waits for interaction, preserves hints and clears corrected errors', async t => {
    const {page, start} = await fixture(t, `<form onsubmit="event.preventDefault();window.saved=true">
      <div class="form-group"><label>邮箱</label><span id="hint">用于接收通知</span><input id="email" name="email" type="email" required aria-describedby="hint"></div>
      <input id="server" aria-label="服务端校验结果" aria-invalid="true"><button type="submit">保存</button></form>`);
    await start();
    const email = page.locator('#email');
    assert.equal(await email.getAttribute('aria-invalid'), 'false');
    assert.equal(await page.locator('.ui-field-error').count(), 0);
    await email.fill('bad');
    assert.equal(await page.locator('.ui-field-error').count(), 0);
    await email.press('Tab');
    await page.waitForFunction(() => document.getElementById('email').getAttribute('aria-invalid') === 'true');
    assert.match(await page.locator('.ui-field-error').textContent(), /有效的邮箱/);
    assert.match(await email.getAttribute('aria-describedby'), /^hint ui-error-/);
    await email.fill('worker@example.com');
    assert.equal(await email.getAttribute('aria-invalid'), 'false');
    assert.equal(await email.getAttribute('aria-describedby'), 'hint');
    assert.equal(await page.locator('.ui-field-error:visible').count(), 0);
    await page.getByRole('button', {name: '保存', exact: true}).click();
    assert.equal(await page.evaluate(() => window.saved), true);
    await page.locator('form').evaluate(form => form.reset());
    await page.getByRole('button', {name: '保存', exact: true}).click();
    assert.equal(await page.evaluate(() => document.activeElement.id), 'email');
    assert.equal(await page.locator('#server').getAttribute('aria-invalid'), 'true');
    await page.locator('form').evaluate(form => form.reset());
    await page.waitForFunction(() => document.querySelectorAll('.ui-field-error:not([hidden])').length === 0);
});
test('invalid required fields in closed details are revealed before native focus', async t => {
    const {page, start} = await fixture(t, '<form><details><summary>更多信息</summary><label>名称<input id="name" required></label></details><button type="submit">保存</button></form>');
    await start();
    await page.getByRole('button', {name: '保存', exact: true}).click();
    assert.equal(await page.locator('details').getAttribute('open'), '');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'name');
    assert.equal(await page.locator('#name').getAttribute('aria-invalid'), 'true');
});
test('dynamic fields gain real labels and preserve form values and server validation', async t => {
    const {page, start} = await fixture(t, '<div id="dynamic"></div>');
    await start();
    await page.locator('#dynamic').evaluate(node => { node.innerHTML = `<form><div class="form-group"><label>所属区域</label><input type="hidden" name="present" value="1"><select name="zone"><option value="a">区域 A</option><option value="b">区域 B</option></select></div><div class="ctrl-row"><span class="ctrl-label">线条粗细</span><input type="range" value="3"></div></form>`; });
    await page.waitForFunction(() => document.querySelector('select.ui-select'));
    assert.equal(await page.getByLabel('所属区域').inputValue(), 'a');
    await page.getByLabel('所属区域').selectOption('b');
    assert.deepEqual(await page.locator('form').evaluate(form => [...new FormData(form)]), [['present', '1'], ['zone', 'b']]);
    assert.equal(await page.getByLabel('线条粗细').getAttribute('type'), 'range');
    assert.equal(await page.locator('select').evaluate(field => getComputedStyle(field).appearance), 'base-select');
});
test('legacy modals retain nodes and close routines while native focus and Escape work', async t => {
    const {page, start} = await fixture(t, `<button id="open" onclick="document.getElementById('overlay').classList.add('open')">新建</button><input id="outside" aria-label="背景字段">
      <div class="app-mask" id="overlay"><div class="app-dialog"><h2>编辑记录</h2><button type="button" class="modal-close" onclick="window.closes=(window.closes||0)+1;document.getElementById('overlay').classList.remove('open')">关闭</button><form><label>备注<input id="note" name="note" value="保留内容"></label></form></div></div>`);
    await page.evaluate(() => { window.originalField = document.getElementById('note'); });
    await start();
    await page.locator('#open').click();
    await page.waitForFunction(() => document.querySelector('dialog:modal'));
    assert.equal(await page.locator('dialog:modal').getAttribute('role'), null);
    assert.equal(await page.locator('dialog:modal').getAttribute('aria-modal'), null);
    await page.locator('#outside').evaluate(field => field.focus());
    assert.equal(await page.evaluate(() => !!document.activeElement.closest('dialog:modal')), true);
    await page.keyboard.press('Shift+Tab');
    // Native dialogs permit focus in browser chrome; background page controls
    // must remain unreachable, without installing a JavaScript focus trap.
    assert.notEqual(await page.evaluate(() => document.activeElement.id), 'outside');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('dialog:modal') && window.closes === 1);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'open');
    await page.locator('#open').click();
    await page.waitForFunction(() => document.querySelector('dialog:modal'));
    assert.equal(await page.evaluate(() => window.originalField === document.getElementById('note')), true);
    assert.equal(await page.locator('#note').inputValue(), '保留内容');
    await page.getByRole('button', {name: '关闭', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('dialog:modal'));
    assert.equal(await page.evaluate(() => window.closes), 2);
    assert.equal(await page.locator('body').evaluate(body => getComputedStyle(body).overflow), 'visible');
});
test('map modal outside clicks invoke the original backdrop close path once', async t => {
    const {page, start} = await fixture(t, `<button id="open" onclick="document.getElementById('woModalContainer').style.display='block';document.getElementById('woModalBackdrop').style.display='block'">填写工单</button>
      <div id="woModalBackdrop" style="display:none" onclick="window.closedCount=(window.closedCount||0)+1;this.style.display='none';document.getElementById('woModalContainer').style.display='none'"></div>
      <section id="woModalContainer" class="v2-modal-container" role="dialog" aria-modal="true" style="display:none"><h2>工单</h2><label>备注<input name="note"></label></section>`);
    await start();
    await page.locator('#open').click();
    await page.waitForFunction(() => document.querySelector('dialog:modal'));
    await page.mouse.click(10, 10);
    await page.waitForFunction(() => !document.querySelector('dialog:modal'));
    assert.equal(await page.evaluate(() => window.closedCount), 1);
    await page.locator('#open').click();
    await page.waitForFunction(() => document.querySelector('dialog:modal'));
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('dialog:modal') && window.closedCount === 2);
    assert.equal(await page.evaluate(() => window.closedCount), 2);
});
test('required announcements remain open until acknowledged', async t => {
    const {page, start} = await fixture(t, '<div class="ann-popup" style="display:flex"><div class="ann-card"><h2>现场通知</h2><button onclick="window.acknowledged=true;this.closest(\'.ann-popup\').style.display=\'none\'">我已知晓</button></div></div>');
    await start();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog:modal').count(), 1);
    assert.equal(await page.evaluate(() => !!window.acknowledged), false);
    await page.getByRole('button', {name: '我已知晓'}).click();
    await page.waitForFunction(() => !document.querySelector('dialog:modal'));
    assert.equal(await page.evaluate(() => window.acknowledged), true);
});
test('a dynamically appended picker remains usable above its parent dialog and removes cleanly', async t => {
    const {page, start} = await fixture(t, `<button id="open" onclick="document.getElementById('overlay').classList.add('open')">编辑订单</button>
      <div class="app-mask" id="overlay"><div class="app-dialog"><h2>采购订单</h2><button id="pick" type="button">添加物料</button><button class="modal-close" onclick="document.getElementById('overlay').classList.remove('open')">关闭订单</button></div></div>`);
    await start();
    await page.locator('#pick').evaluate(button => button.addEventListener('click', () => {
        const picker = document.createElement('div');
        picker.id = 'picker';
        picker.className = 'v2-sheet-overlay';
        picker.style.cssText = 'display:flex;position:fixed;inset:0;background:white';
        picker.innerHTML = '<h2>选择物料</h2><button type="button">取消选择</button>';
        picker.querySelector('button').addEventListener('click', () => picker.remove());
        document.body.append(picker);
    }));
    await page.locator('#open').click();
    await page.locator('#pick').click();
    await page.waitForFunction(() => document.querySelectorAll('dialog:modal').length === 2);
    await page.getByRole('button', {name: '取消选择', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('dialog:modal').length === 1 && !document.querySelector('dialog[data-ui-overlay="picker"]'));
    await page.locator('#pick').click();
    await page.waitForFunction(() => document.querySelectorAll('dialog:modal').length === 2);
    assert.equal(await page.locator('#picker').count(), 1);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelectorAll('dialog:modal').length === 1);
    await page.getByRole('button', {name: '关闭订单', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('dialog:modal'));
});
test('disclosures expose state and remain keyboard operable beside separate actions', async t => {
    const {page, start} = await fixture(t, `<div class="settings-card-header" onclick="let panel=this.nextElementSibling;panel.style.display=panel.style.display==='none'?'block':'none'"><h2>区域管理</h2><div class="header-actions" onclick="event.stopPropagation()"><button id="export" onclick="window.exported=true">导出</button></div></div><div style="display:none">区域列表</div>
      <div class="wr-card"><div class="wr-summary" onclick="this.parentElement.classList.toggle('open')">维修记录</div><div class="wr-expand-hint">点击查看详情</div><div class="wr-detail">详细记录</div></div>`);
    await start();
    const button = page.getByRole('button', {name: '区域管理', exact: true});
    assert.equal(await button.getAttribute('aria-expanded'), 'false');
    await button.press('Space');
    assert.equal(await button.getAttribute('aria-expanded'), 'true');
    await page.locator('#export').click();
    assert.equal(await page.evaluate(() => window.exported), true);
    assert.equal(await button.getAttribute('aria-expanded'), 'true');
    await page.getByRole('button', {name: '展开详情', exact: true}).press('Enter');
    assert.equal(await page.getByRole('button', {name: '收起详情', exact: true}).getAttribute('aria-expanded'), 'true');
    await page.getByRole('button', {name: '收起详情', exact: true}).press('Space');
    assert.equal(await page.getByRole('button', {name: '展开详情', exact: true}).getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('.settings-card-header .ui-section-toggle').count(), 1);
});
test('existing project switches support keyboard input and announce disabled and checked state', async t => {
    const {page, start} = await fixture(t, '<span id="switch" class="zd-switch" onclick="if(!this.classList.contains(\'disabled\'))this.querySelector(\'.zd-switch-track\').classList.toggle(\'on\')"><span>工时</span><span class="zd-switch-track"></span></span><div class="zd-photo-thumb" onclick="window.photoOpened=true"><img alt="现场照片"></div>');
    await start();
    await page.getByRole('switch', {name: '工时'}).press('Enter');
    await page.waitForFunction(() => document.getElementById('switch').getAttribute('aria-checked') === 'true');
    await page.locator('#switch').evaluate(control => control.classList.add('disabled'));
    await page.waitForFunction(() => document.getElementById('switch').getAttribute('aria-disabled') === 'true');
    assert.equal(await page.locator('#switch').getAttribute('tabindex'), '-1');
    await page.getByRole('button', {name: '查看现场照片'}).press('Space');
    assert.equal(await page.evaluate(() => window.photoOpened), true);
});
test('touch layouts retain OS select pickers, large controls and bounded growing textareas', async t => {
    const {page, start} = await fixture(t, '<div class="form-group"><label>区域</label><select><option>区域 A</option><option>区域 B</option></select></div><select multiple size="4" aria-label="多个区域"><option>A</option></select><textarea aria-label="备注" rows="3"></textarea>', {viewport:{width:390,height:844}, hasTouch:true, reducedMotion:'reduce'});
    await start();
    assert.notEqual(await page.locator('select').first().evaluate(field => getComputedStyle(field).appearance), 'base-select');
    assert.equal(await page.locator('select[multiple]').evaluate(field => field.classList.contains('ui-select')), false);
    assert.ok(await page.locator('select').first().evaluate(field => field.getBoundingClientRect().height >= 48));
    const note = page.locator('textarea');
    await note.fill('短备注');
    const first = await note.boundingBox();
    await note.fill('需要补充的现场记录\n'.repeat(50));
    const last = await note.boundingBox();
    assert.ok(last.height > first.height);
    assert.ok(last.height <= 322);
    assert.equal(last.width, first.width);
    assert.equal(await note.evaluate(field => getComputedStyle(field).fontSize), '16px');
    assert.equal(await note.evaluate(field => getComputedStyle(field).transitionDuration), '1e-05s');
});

test('a form can veto Escape while saving and close normally on the next attempt',async t=>{
    const {page,start}=await fixture(t,`<button id="open" onclick="document.getElementById('overlay').classList.add('open')">填写</button>
    <div class="app-mask" id="overlay"><div class="app-dialog"><h2>工单</h2><label>备注<input value="原内容"></label>
    <button type="button" data-ui-close onclick="if(!window.busy)this.closest('.app-mask').classList.remove('open')">关闭</button></div></div>`);
    await start();
    await page.locator('#open').click();
    await page.evaluate(()=>window.busy=true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog:modal input').inputValue(),'原内容');
    await page.evaluate(()=>window.busy=false);
    await page.keyboard.press('Escape');
    await page.waitForFunction(()=>!document.querySelector('dialog:modal'));
    await page.locator('#open').click();
    assert.equal(await page.locator('dialog:modal input').inputValue(),'原内容');
});

test('checkbox filter uses an anchored nonmodal popover and restores focus on Escape', async t=>{
    const {page,start}=await fixture(t,`<button type="button" id="plantDropdownBtn" data-filter-popover aria-expanded="false" aria-controls="plantDropdownPanel">植物筛选</button>
        <div id="plantDropdownPanel" hidden><label><input type="checkbox">草坪</label></div>`);
    await start();
    const trigger=page.getByRole('button',{name:'植物筛选'});
    const option=page.getByRole('checkbox',{name:'草坪'});
    await trigger.focus();
    await trigger.press('Enter');
    await option.waitFor();
    assert.equal(await trigger.getAttribute('aria-expanded'),'true');
    const rects=await trigger.evaluate(button=>[button.getBoundingClientRect().bottom,document.getElementById('plantDropdownPanel').getBoundingClientRect().top]);
    assert.ok(Math.abs(rects[1]-rects[0])<10);
    await page.keyboard.press('Tab');await page.keyboard.press('Space');
    assert.ok(await option.isChecked());
    await page.keyboard.press('Escape');await option.waitFor({state:'hidden'});
    assert.equal(await trigger.getAttribute('aria-expanded'),'false');
    assert.ok(await trigger.evaluate(button=>document.activeElement===button));
});

test('the final EnGenie order button confirms the named supplier and reports validation and save failures', async t => {
    const {page, start} = await fixture(t, '<div id="aiChatPanel"><div id="card"></div></div>');
    await start();
    await page.addScriptTag({path:path.join(assets, 'js/inventory-quotes.js')});
    await page.evaluate(() => {
        window.posts = [];
        window.fetch = async (url, {body}) => {
            if (url !== '/inventory/quotes/confirm/') throw Error('Unexpected URL');
            window.posts.push(Object.fromEntries(body));
            if (window.posts.length === 1) return Response.json({success:false, message:'订单编号已存在'}, {status:409});
            return Response.json({success:true, order_id:23, order_number:'PO-2', message:'采购订单 PO-2 已创建'});
        };
        const catalog = [1,2].map(id => ({id, name:'部件'+id, node_type:'part'}));
        window.EnGenieQuotes.mount({host:document.getElementById('card'), threadId:'test', draft:{
            token:'draft', submission_key:'key', destination:'choose', order_number:'PO-1', supplier:'测试供应商',
            catalog, items:catalog.map(item => ({row_id:String(item.id), name:item.name, category_id:item.id, quantity:'2'}))
        }});
    });
    const form=page.locator('.ivq-review'), button=form.getByRole('button',{name:'确认使用「测试供应商」并写入 2 项'});
    const chat=await page.evaluate(() => window.EnGenieQuotes.confirmFromChat('确认', 'test'));
    assert.equal(chat.success, false);
    await button.click();
    const target=form.getByLabel('写入目标');
    assert.equal(await target.inputValue(),'');
    assert.ok(await target.evaluate(field => document.activeElement === field));
    assert.equal(await page.evaluate(() => window.posts.length), 0);
    await target.selectOption('order');
    await button.click();
    const date=form.getByLabel('采购日期');
    assert.ok(await date.evaluate(field => document.activeElement === field));
    assert.match(await form.locator('.ivq-status').textContent(), /采购日期/);
    assert.equal(await page.evaluate(() => window.posts.length), 0);
    await date.fill('2026-11-19');
    await button.click();
    await form.getByText('订单编号已存在', {exact:true}).waitFor();
    assert.ok(await button.evaluate(b => b.previousElementSibling.classList.contains('ivq-status')));
    await form.getByLabel('灌溉订单编号').fill('PO-2');
    await button.click();
    await page.getByRole('link',{name:'查看采购订单：PO-2'}).waitFor();
    const posts=await page.evaluate(() => window.posts);
    assert.equal(posts.length,2);
    assert.equal(posts[1].supplier,'测试供应商');
    assert.equal(JSON.parse(posts[1].items).length,2);
    assert.equal(posts[1].submission_key,posts[0].submission_key);
});

test('HD imagery loads inside the viewport and drafts require a loaded image and an alignment', async t => {
    const {page} = await fixture(t, '<div data-hd-controls><input data-hd-visible type="checkbox" checked><button data-hd-manage>管理</button></div><div style="position:relative"><div id="map" style="height:300px;width:400px"></div></div>');
    const ops = path.resolve(assets, '../operations/static');
    await page.addStyleTag({path:path.join(assets, 'vendor/leaflet/leaflet.css')});
    await page.addScriptTag({path:path.join(assets, 'vendor/leaflet/leaflet.js')});
    await page.addScriptTag({path:path.join(ops, 'vendor/leaflet/imageoverlay-rotated.js')});
    await page.addScriptTag({path:path.join(ops, 'operations/map-overlays.js')});
    const downloads = [];
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    await page.route('https://imagery.invalid/*', async route => {
        const name = new URL(route.request().url()).pathname;
        downloads.push(name);
        if (name === '/draft') await pending;
        await route.fulfill({contentType:'image/png', body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGn8AAAAASUVORK5CYII=', 'base64')});
    });
    await page.evaluate(async () => {
        const map = window.map = L.map('map', {zoomAnimation:false}).setView([31,121], 19);
        const ll = (x,y) => {const p = map.containerPointToLatLng([x,y]);return [p.lat,p.lng];};
        const image = (id, name, anchors) => ({id, name, anchors, calibrated:!!anchors, active:true,
            opacity:1,width:300,height:200,calibration_version:'original',image_url:'https://imagery.invalid/'+name});
        const items = [image(1,'near',{tl:ll(50,50),tr:ll(90,50),bl:ll(50,90)}),
            image(2,'far',{tl:ll(850,50),tr:ll(890,50),bl:ll(850,90)}),
            image(3,'diagonal',{tl:ll(-100,35),tr:ll(35,-100),bl:ll(-96,39)}),
            image(4,'draft',null)];
        window.farCenter = ll(870,70);
        window.fetch = async () => Response.json({success:true,overlays:items});
        window.imagery = FOSMapOverlays({map});
        await window.imagery.refresh();
    });
    await page.waitForFunction(() => document.querySelector('.leaflet-hdImagery-pane img')?.naturalWidth);
    assert.deepEqual(downloads, ['/near']);
    await page.locator('[data-hd-visible]').uncheck();
    await page.evaluate(() => map.setView(farCenter,19,{animate:false}));
    assert.equal(await page.locator('.leaflet-hdImagery-pane img').count(), 0);
    await page.locator('[data-hd-visible]').check();
    await page.waitForFunction(() => document.querySelector('img[src$="/far"]')?.naturalWidth);
    assert.deepEqual(downloads, ['/near','/far']);
    await page.evaluate(() => imagery.startCalibration(4));
    const save = page.locator('[data-save]');
    assert.equal(await save.isDisabled(), true);
    release();
    await page.waitForFunction(() => !document.querySelector('[data-pairs]').disabled);
    assert.equal(await save.isDisabled(), true);
    const handle = await page.locator('.overlay-anchor').first().boundingBox();
    await page.mouse.move(handle.x+15,handle.y+15);
    await page.mouse.down();await page.mouse.move(handle.x+36,handle.y+30,{steps:5});await page.mouse.up();
    assert.equal(await save.isEnabled(), true);
    await page.locator('[data-cancel]').click();
    await page.evaluate(() => imagery.destroy());
});
