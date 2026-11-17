const {test}=require('node:test');
const assert=require('node:assert/strict');
const {validate,sizeLabel}=require('../../static/js/feedback.js');
const MB=1024*1024;
test('feedback supports arbitrary private attachment types alongside photos',()=>{
    assert.equal(validate([{name:'image.png',size:1024}],[{name:'drawing.dxf',size:2048},{name:'document.pdf',size:1024}]),null);
    assert.equal(validate([],[{name:'large.zip',size:50*MB},{name:'table.xlsx',size:50*MB}]),null);
});
test('feedback enforces per-file, combined-size, and combined-count limits',()=>{
    assert.equal(validate(Array.from({length:6},()=>({size:1})),[]).field,'photos');
    assert.match(validate([{size:10*MB+1}],[]).message,/10 MB/);
    assert.match(validate([],[{size:50*MB+1}]).message,/50 MB/);
    assert.match(validate([],[{size:50*MB},{size:50*MB},{size:1}]).message,/100 MB/);
    assert.match(validate(Array.from({length:5},()=>({size:1})),Array.from({length:6},()=>({size:1}))).message,/10 个/);
    for(const size of [0,-1,NaN,Infinity])assert.match(validate([],[{size}]).message,/无效|为空/);
});
test('attachment labels show useful sizes without reading file contents',()=>{
    assert.equal(sizeLabel(100),'100 B');assert.equal(sizeLabel(2048),'2 KB');assert.equal(sizeLabel(2*MB),'2.0 MB');
});
