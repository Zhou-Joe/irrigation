const test=require('node:test');const assert=require('node:assert/strict');
const {createState}=require('../../operations/static/operations/location-picker.js');
const options=Array.from({length:1100},(_,i)=>({id:String(i),name:'Building '+i,code:'B-'+i,kind:i%2?'building':'room'}));
test('large location sets retain selections across search and type changes',()=>{
    const state=createState(options,['1099','unknown']);assert.deepEqual(state.selected(),['1099']);
    assert.equal(state.matches('', 'building').length,550);
    state.selectMatches('B-10','room');assert.ok(state.has('1099'));assert.ok(state.has('10'));
    state.selectMatches('B-10','room',false);assert.ok(state.has('1099'));assert.equal(state.has('10'),false);
    assert.equal(state.toggle('unknown'),false);
});
test('duplicate names are distinct by id and clearing does not mutate source data',()=>{
    const state=createState([{id:1,name:'Room',code:'A'},{id:2,name:'Room',code:'B'}]);state.toggle(1);state.toggle(2);
    assert.deepEqual(state.selected(),['1','2']);state.toggle(1);assert.deepEqual(state.selected(),['2']);state.clear();assert.deepEqual(state.selected(),[]);
    assert.equal(options.length,1100);
});
