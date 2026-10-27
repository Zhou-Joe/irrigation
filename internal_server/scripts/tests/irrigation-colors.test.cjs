const {test}=require('node:test');
const assert=require('node:assert/strict');
const {scale}=require('../../static/js/irrigation-colors.js');
test('one or two extreme observations do not compress ordinary zone colors',()=>{
    const ordinary=[5,10,15,20,25,30,40,50,60,70];
    const a=scale([...ordinary,10000,20000]),b=scale([...ordinary,1e9,1e12]);
    assert.equal(a.position(30),b.position(30));
    assert.ok(a.position(30)>.45);
    assert.ok(a.position(70)>.8);
    assert.equal(a.max,20000);
    assert.equal(b.max,1e12);
});
test('zeros, missing intensity and invalid values do not skew nonzero ranks',()=>{
    const a=scale([10,20,30]),b=scale([...Array(100).fill(0),null,undefined,NaN,Infinity,-1,10,20,30]);
    assert.equal(a.position(20),b.position(20));
    assert.equal(b.position(0),0);
    assert.equal(b.position(NaN),0);
});
test('ties have one color; uniform, single and empty maps remain well-defined',()=>{
    const a=scale([10,10,10,20,1000]);
    assert.equal(a.position(10),a.position(10));
    assert.ok(a.position(10)<a.position(20));
    assert.equal(scale([30,30]).position(30),.5);
    assert.equal(scale([30]).position(30),.5);
    assert.equal(scale([]).position(30),0);
});
test('manual upper limits preserve linear colors and never change real values',()=>{
    const a=scale([10,50,1000],100);
    assert.equal(a.kind,'manual');assert.equal(a.position(50),.5);assert.equal(a.position(1000),1);
    assert.equal(a.max,1000);assert.equal(scale([1,2],0).kind,'quantile');
});
