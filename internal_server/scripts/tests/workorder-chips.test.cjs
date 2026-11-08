const test = require('node:test');
const assert = require('node:assert/strict');
const {createState} = require('../../operations/static/operations/workorder-chips.js');

const tree = [
    {id:1, name:'病媒昆虫', children:[{id:2, name:'监测', children:[{id:3, name:'检查'}]}]},
    {id:4, name:'传粉昆虫', children:[{id:5, name:'监测', children:[
        {id:6, name:'检查'}, {id:7, name:'人工处理', children:[{id:8, name:'报封堵工单', kind:'note'}]},
    ]}]},
];

test('chips navigate variable depth without selecting a category as work content', () => {
    const state = createState(tree);
    state.choose(4); state.choose(5); state.choose(7);
    assert.deepEqual(state.branches().map(n => n.id), ['4','5','7']);
    assert.deepEqual(state.selected(), []);
    state.choose(8);
    assert.deepEqual(state.selected().map(n => n.id), ['8']);
    assert.deepEqual(state.path(8).map(n => n.name), ['传粉昆虫','监测','人工处理','报封堵工单']);
    assert.equal(state.selected()[0].kind, 'note');
});

test('switching branches preserves separate selections even when labels match', () => {
    const state = createState(tree);
    state.choose('3'); state.choose(4); state.choose(6);
    assert.deepEqual(state.selected().map(n => n.id), ['3','6']);
    assert.equal(state.hasSelection(1), true);
    assert.equal(state.hasSelection(4), true);
    assert.equal(state.isSelected(2), false);
    state.choose(3);
    assert.deepEqual(state.selected().map(n => n.id), ['6']);
    assert.equal(state.hasSelection(1), false);
    assert.equal(state.remove('6'), true);
    assert.deepEqual(state.selected(), []);
});

test('invalid identifiers cannot change selections or the current branch', () => {
    const state = createState(tree);
    state.choose(2); state.choose(3);
    assert.equal(state.choose('unknown'), false);
    assert.equal(state.remove('unknown'), false);
    assert.deepEqual(state.path('unknown'), []);
    assert.deepEqual(state.branches().map(n => n.id), ['1','2']);
    assert.deepEqual(state.selected().map(n => n.id), ['3']);
    assert.throws(() => createState([{id:1,name:'A',children:[{id:'1',name:'B'}]}]), /Duplicate/);
    assert.deepEqual(tree[0].children[0].children[0], {id:3,name:'检查'});
});
