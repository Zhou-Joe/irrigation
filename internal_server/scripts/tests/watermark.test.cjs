const {test}=require('node:test');
const assert=require('node:assert/strict');
const {wrapText,layout,pixelRatio}=require('../../static/js/watermark.js');
const measure=(text,size=12)=>Array.from(text).reduce((n,c)=>n+(/[\u2e80-\u9fff]/.test(c) ? size : size*.55),0);

test('long CJK identities wrap without losing names, phone numbers or departments',()=>{
    const identity='张三 · 13800138000 · 园艺维护与室外灌溉管理部门';
    const rows=wrapText(identity,110,text=>measure(text));
    assert.ok(rows.length>1);assert.equal(rows.join(''),identity);
    rows.forEach(row=>assert.ok(measure(row)<=110));
});
test('Unicode code points and HTML-looking text remain literal content',()=>{
    const text='Zoë & 张😀 <script>alert("x")</script>';
    const rows=wrapText(text,75,value=>measure(value));
    assert.equal(rows.join(''),text);
    assert.ok(rows.every(row=>!/[\uD800-\uDBFF]$/.test(row)));
});
test('rotated multiline text fits inside every mobile and desktop tile',()=>{
    for(const mobile of [false,true]) for(const identity of ['李四', '姓名 · 13800138000 · '+ '园艺部门'.repeat(35)]) {
        const geometry=layout(identity,'仅限内部沟通，严禁外传',measure,mobile);
        assert.ok(Number.isFinite(geometry.width)&&Number.isFinite(geometry.tileHeight));
        assert.ok(geometry.width>=geometry.rotatedWidth+64);
        assert.ok(geometry.tileHeight>=geometry.rotatedHeight+80);
        assert.equal(geometry.rows.map(row=>row.text).join(''),identity+'仅限内部沟通，严禁外传');
    }
});
test('retina scale is bounded and invalid device ratios cannot create invalid canvas sizes',()=>{
    for(const value of [undefined,NaN,0,-2])assert.equal(pixelRatio(value),1);
    assert.equal(pixelRatio(1.5),1.5);assert.equal(pixelRatio(2),2);
    assert.equal(pixelRatio(4),3);assert.equal(pixelRatio(Infinity),3);
});
test('empty or single-line content still produces finite reusable geometry',()=>{
    for(const mobile of [false,true]){
        const geometry=layout('','',measure,mobile);
        assert.equal(geometry.rows.length,0);
        assert.ok(geometry.width>0&&geometry.tileHeight>0);
        assert.deepEqual(wrapText('',50,measure),[]);
    }
});
