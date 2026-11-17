const test=require('node:test'),assert=require('node:assert/strict');
const {createSelection}=require('../../operations/static/operations/bulk-ui.js');

test('map selections toggle independently and survive a list page change',()=>{
    const selection=createSelection();selection.use('pest:catalog:all');
    selection.set('page-one',true);selection.set('page-two',true);
    selection.use('pest:catalog:all');
    assert.deepEqual(selection.snapshot().ids,['page-one','page-two']);
    selection.set('page-one',false);
    assert.deepEqual(selection.snapshot().ids,['page-two']);
});
test('selecting or clearing the visible page preserves selected locations on other pages',()=>{
    const selection=createSelection();selection.use('catalog');selection.set('off-page',true);
    selection.page(['a','b'],true);assert.equal(selection.count(100),3);
    selection.page(['a','b'],false);assert.deepEqual(selection.snapshot().ids,['off-page']);
});
test('deselecting after select-all records exclusions without trusting old map geometry',()=>{
    const selection=createSelection();selection.use('catalog');selection.all(true);
    assert.equal(selection.count(3),3);selection.set('b',false);
    assert.equal(selection.snapshot().allMatching,true);
    assert.equal(selection.has('off-page'),true);
    assert.equal(selection.has('b'),false);
    assert.deepEqual(selection.snapshot().excludedIds,['b']);
    assert.equal(selection.count(3),2);
    selection.page(['a','off-page'],false);
    assert.equal(selection.count(3),0);
    selection.set('b',true);assert.equal(selection.count(3),1);
    selection.use('catalog:new-filter');assert.deepEqual(selection.snapshot().excludedIds,[]);
});
test('team, scope and filter changes reset selection rather than applying a stale group',()=>{
    const selection=createSelection();selection.use('team-a:catalog:buildings');selection.set('a',true);
    selection.use('team-a:catalog:rooms');assert.equal(selection.count(0),0);
    selection.all(true);selection.use('team-b:catalog:rooms');assert.equal(selection.snapshot().allMatching,false);
    selection.set('b',true);selection.use('team-b:team:rooms');assert.deepEqual(selection.snapshot().ids,[]);
});
test('clear removes explicit and select-all selections',()=>{
    const selection=createSelection();selection.use('catalog');selection.set('a',true);selection.clear();
    assert.equal(selection.count(100),0);selection.all(true);selection.clear();
    assert.deepEqual(selection.snapshot(),{ids:[],excludedIds:[],allMatching:false});
});
