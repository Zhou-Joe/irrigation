const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function fixture(){
  const elements=new Map(),checkboxes=[],types=[];
  const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',hidden:false,classList:{add(){},remove(){}}});return elements.get(id);};
  const state={pdxfToken:'drawing-a',pdxfData:{blocks:[],labels:[],shape_candidates:[
    {id:'shape:a',include_guess:true,valve_type_guess:'washdown',template_name:'WD',text:'WD',reason:'内部文字与图形',confidence:.99,label_refs:['wd'],source_refs:[{layer:'100',index:2}]},
    {id:'shape:b',include_guess:false,valve_type_guess:'',template_name:'Triangle',text:'',reason:'常见图形',confidence:.94,label_refs:[],source_refs:[{layer:'100',index:4}]}
  ]},VALVE_LABELS:{gate:'闸阀',washdown:'冲洗阀'},pdxfEl:element,
    pdxfEsc:value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    changes:0,pdxfMappingChanged(){state.changes++;},document:{getElementById:element,
      querySelectorAll:selector=>selector==='.pdxf-shape-include'?checkboxes:selector==='.pdxf-shape-type'?types:[]}};
  vm.createContext(state);vm.runInContext(fs.readFileSync(path.join(__dirname,'../dxf-symbols.js'),'utf8'),state);
  return {state,element,checkboxes,types};
}

test('only displayed suggestions are preselected; a changed library cannot silently add unseen devices',()=>{
  const {state:s,checkboxes,types}=fixture();s.pdxfRenderShapes();
  assert.equal(s.pdxfCollectShapeSpecs()['shape:a'].include,true);
  checkboxes.push({dataset:{shape:'shape:a'},checked:false});types.push({dataset:{shape:'shape:a'},value:'washdown'});
  assert.equal(s.pdxfCollectShapeSpecs()['shape:a'].include,false);
  s.pdxfData.shape_candidates.push({...s.pdxfData.shape_candidates[0],id:'shape:new',source_refs:[{layer:'100',index:9}]});
  assert.equal(s.pdxfCollectShapeSpecs()['shape:new'].include,false);
});
test('a batch type choice selects candidates and keeps individual source identities',()=>{
  const {state:s,element}=fixture();s.pdxfRenderShapes();element('pdxfShapeBulkType').value='gate';s.pdxfApplyShapeType();
  const specs=s.pdxfCollectShapeSpecs();
  assert.equal(specs['shape:a'].valve_type,'gate');assert.equal(specs['shape:b'].include,true);
  const lookup=s.pdxfShapePartLookup(specs);
  assert.equal(lookup['100\u00002'].id,'shape:a');assert.equal(lookup['100\u00004'].id,'shape:b');
  assert.equal(s.changes,1);
});
test('WD is part of its symbol even with annotations/reference lines off, while device visibility is respected',()=>{
  const {state:s}=fixture();s.pdxfRenderShapes();
  const specs={blocks:{opaque:{include:true}},shapes:s.pdxfCollectShapeSpecs()};
  assert.equal(s.pdxfInlineSymbolLabel({block:'opaque',inline_symbol:true},specs,false,true),true);
  assert.equal(s.pdxfInlineSymbolLabel({source_id:'wd'},specs,false,true),true);
  assert.equal(s.pdxfInlineSymbolLabel({source_id:'ordinary-note'},specs,false,true),false);
  assert.equal(s.pdxfInlineSymbolLabel({block:'opaque',inline_symbol:true},specs,true,false),false);
});
test('candidate names and reasons render as text, and a new drawing clears old choices',()=>{
  const {state:s,element}=fixture();s.pdxfData.shape_candidates[0].template_name='<img src=x onerror=bad>';
  s.pdxfData.shape_candidates[0].text='';s.pdxfRenderShapes();
  assert.ok(!element('pdxfShapeBody').innerHTML.includes('<img'));
  assert.ok(element('pdxfShapeBody').innerHTML.includes('&lt;img'));
  s.pdxfCollectShapeSpecs();s.pdxfToken='drawing-b';s.pdxfData.shape_candidates=[];
  assert.equal(Object.keys(s.pdxfCollectShapeSpecs()).length,0);
});
