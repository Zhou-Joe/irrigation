const test=require('node:test');
const assert=require('node:assert/strict');
const {activeFields}=require('../../operations/static/operations/work-parameters.js');

const schema={nodes:[
    {id:'bird',parent:'',name:'鸟类调查',parameters:[{key:'species',label:'鸟种',type:'text'},{key:'direction',label:'朝向',type:'location'}]},
    {id:'bird-leaf',parent:'bird',name:'记录',parameters:[]},
    {id:'bee',parent:'',name:'蜜蜂',parameters:[]}
],locations:[
    {id:'a',parent:'',name:'建筑 A',parameters:[{key:'direction',label:'朝向',type:'choice',options:[{value:'N',label:'北'}]}]},
    {id:'room',parent:'a',name:'二楼',parameters:[]},
    {id:'b',parent:'',name:'建筑 B',parameters:[{key:'direction',label:'朝向',type:'choice',options:[{value:'S',label:'南'}]}]}
]};
test('building fields inherit through rooms and stay separated for different buildings',()=>{
    const fields=activeFields(schema,['bird-leaf'],['a','room','b']);
    assert.deepEqual(fields.work.map(f=>f.key),['species']);
    assert.equal(fields.locations.length,2);
    assert.deepEqual(fields.locations.map(f=>[f.owner_id,f.options[0].value]),[['a','N'],['b','S']]);
});
test('unrelated work and unknown selections never inherit global direction controls',()=>{
    assert.deepEqual(activeFields(schema,['bee'],['a']),{work:[],locations:[]});
    assert.deepEqual(activeFields(schema,[],['a']),{work:[],locations:[]});
    assert.deepEqual(activeFields(schema,['bird-leaf'],['unavailable']).locations,[]);
});
test('a room override remains bound to the room instead of changing its parent field',()=>{
    const copy=structuredClone(schema);copy.locations[1].parameters=[{key:'direction',label:'窗户方向',type:'choice',options:[{value:'E',label:'东'}]}];
    const fields=activeFields(copy,['bird-leaf'],['room','a']);
    assert.deepEqual(fields.locations.map(f=>[f.owner_id,f.options[0].value]),[['a','N'],['room','E']]);
});
test('a required work binding makes its building field required',()=>{
    const copy=structuredClone(schema);copy.nodes[0].parameters[1].required=true;
    assert.equal(activeFields(copy,['bird-leaf'],['a']).locations[0].required,true);
});
