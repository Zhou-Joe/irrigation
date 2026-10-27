const {test}=require('node:test');
const assert=require('node:assert/strict');
const scope=require('../../static/js/irrigation-scope.js');
const water={sites:[{key:'5',number:3,name:'Tomorrowland'},
    {key:'3',number:5,name:'Fantasyland'},{key:'1',number:1},{key:'10',number:10},
    {key:'26',number:99},{key:'unknown',number:null}]};
test('native time inputs omitting zero seconds keep the same exact end in chart and map',()=>{
    assert.equal(scope.compactInput('2026-10-27T07:01',true),'20261027070100');
    assert.equal(scope.compactInput('2026-10-27T07:01:59',true),'20261027070159');
    assert.equal(scope.compactInput('',true),'');
});
test('CCU selects the Site display number, never its internal key',()=>{
    assert.deepEqual(scope.sites(water,'CCU3').map(s=>s.key),['5']);
    assert.deepEqual(scope.sites(water,'CCU5').map(s=>s.key),['3']);
    assert.equal(scope.label(water.sites[0]),'CCU3 · Tomorrowland');
});
test('matching is exact and an empty CCU stays empty instead of displaying all water',()=>{
    assert.deepEqual(scope.sites(water,'CCU1').map(s=>s.key),['1']);
    assert.deepEqual(scope.sites(water,'CCU7'),[]);
    assert.deepEqual(scope.sites(water,'bad'),[]);
    assert.equal(scope.sites(water,null),water.sites);
});
test('source Sites without a configured runtime CCU remain available in the common pager',()=>{
    const tables=[1,3,5,10].map(n=>({ccu_code:'CCU'+n}));
    const result=scope.pages(tables,[water]);
    assert.equal(result.at(-1).ccu_code,'other');
    assert.deepEqual(scope.sites(water,'other',tables.map(t=>t.ccu_code)).map(s=>s.key),['26','unknown']);
    assert.equal(tables.length,4);
    assert.deepEqual(scope.pages(tables,[{sites:water.sites.slice(0,4)}]),tables);
});
