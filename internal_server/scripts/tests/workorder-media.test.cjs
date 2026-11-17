const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../../operations/static/operations/workorder-media.js'),'utf8'),context);
const validate = context.window.FOSWorkorderMedia.validate;
const image = {name:'field.png',size:1024}, video = {name:'clip.mp4',size:2048};
test('pest media accepts supported photos and videos and rejects disguised extensions', () => {
    assert.equal(validate([image,video]),'');
    assert.match(validate([{name:'file.svg',size:12}]),/格式/);
    assert.match(validate([{name:'clip.mp4',size:0}]),/不能为空/);
});
test('pest media limits include retained attachments and total request bytes', () => {
    assert.match(validate([image,video],9),/10/);
    assert.equal(validate([image],9),'');
    assert.match(validate([{name:'clip.mp4',size:51*1024*1024}]),/50 MB/);
    assert.match(validate(Array.from({length:3},()=>({name:'clip.mp4',size:40*1024*1024}))),/100 MB/);
});
