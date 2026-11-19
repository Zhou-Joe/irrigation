const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../..');

function importFixture(items, cart=[]) {
  const elements = {poImportApply:{disabled:false},poImportStatus:{textContent:''},poFpo_number:{value:''},poForder_number:{value:''}};
  const catalog = [{id:7,name:'喷芯加长杆',code:'EXTENDER',path:'喷头 / 喷芯加长杆',unit:'个'}];
  const rows = items.map(item => ({querySelector(selector) {
    if (selector === '[data-import-include]') return {checked:item.include !== false};
    const values = {match:'喷头 / 喷芯加长杆 [EXTENDER]',quantity:'1500',price:'15.31',unit:'个',supplier:'供应商甲',...item};
    return {value:values[selector.slice(13,-1)]};
  }}));
  const scope = {_poPlannedCart:cart, renders:0, _poRenderPlanned(){scope.renders++;},
    document:{getElementById:id=>elements[id],querySelectorAll:()=>rows}};
  scope.window=scope;vm.createContext(scope);
  vm.runInContext(fs.readFileSync(path.join(root,'static/js/purchase-import.js'),'utf8'),scope);
  scope.payload={catalog,metadata:{po_number:'PO-330'},token:'preview'};
  vm.runInContext('poImportDocument=payload',scope);
  return {scope,elements};
}

test('PO import keeps suppliers and exact zero prices in the draft and applies only once',()=>{
  const h=importFixture([{price:'0'}]);h.scope.poImportApply();
  assert.equal(h.scope._poPlannedCart.length,1);
  assert.equal(h.scope._poPlannedCart[0].supplier,'供应商甲');
  assert.equal(h.scope._poPlannedCart[0].unit_price,'0');
  assert.equal(h.scope._poPlannedCart[0].quantity,1500);
  assert.equal(h.elements.poFpo_number.value,'PO-330');
  assert.equal(h.elements.poImportApply.disabled,true);
  h.scope.poImportApply();assert.equal(h.scope.renders,1);assert.equal(h.scope._poPlannedCart[0].quantity,1500);
});

test('unresolved materials and conflicting suppliers leave the existing draft untouched',()=>{
  const unresolved=importFixture([{match:'a material not in the catalog'}]);unresolved.scope.poImportApply();
  assert.equal(unresolved.scope._poPlannedCart.length,0);assert.match(unresolved.elements.poImportStatus.textContent,/实际目录/);
  const conflicting=importFixture([{supplier:'供应商甲'},{supplier:'供应商乙'}]);conflicting.scope.poImportApply();
  assert.equal(conflicting.scope._poPlannedCart.length,0);assert.equal(conflicting.scope.renders,0);
  assert.match(conflicting.elements.poImportStatus.textContent,/不能自动合并/);
});

test('only reviewed positive integer quantities and finite two-decimal prices enter the draft',()=>{
  for (const item of [{quantity:'1.5'},{quantity:'0'},{price:'NaN'},{price:'-1'},{price:'1.001'}]) {
    const h=importFixture([item]);h.scope.poImportApply();assert.equal(h.scope._poPlannedCart.length,0);
  }
});

test('individual pipeline layers can turn on after all layers are switched off',()=>{
  const source=fs.readFileSync(path.join(root,'static/js/map.js'),'utf8');
  const start=source.indexOf('    function setPipelineTypeVisibility('),end=source.indexOf('    function renderPipelines(',start);
  const irrigation={id:'irrigation'},flush={id:'flush'},children=new Set(),mapLayers=new Set(),inputs=[{checked:true},{checked:false}],master={};
  const group={addLayer:child=>children.add(child),removeLayer:child=>children.delete(child)};
  const scope={pipelineTypeGroups:new Map([['irrigation',irrigation],['flush',flush]]),hiddenPipelineTypes:new Set(['irrigation','flush']),
    pipelinesLayerGroup:group,pipelinesVisible:false,viewportUpdates:0,updatePipeOverlayTiers(){scope.viewportUpdates++;},document:{querySelectorAll:()=>inputs,getElementById:()=>master},
    map:{addLayer:layer=>mapLayers.add(layer),removeLayer:layer=>mapLayers.delete(layer)}};
  vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);
  scope.setPipelineTypeVisibility('irrigation',true);
  assert.equal(children.has(irrigation),true);assert.equal(children.has(flush),false);
  assert.equal(mapLayers.has(group),true);assert.equal(master.indeterminate,true);assert.equal(master.checked,false);
  inputs[0].checked=false;scope.setPipelineTypeVisibility('irrigation',false);
  assert.equal(mapLayers.has(group),false);assert.equal(master.indeterminate,false);assert.equal(scope.viewportUpdates,2);
});

test('changed template scripts compile with their real entry points',()=>{
  for (const name of ['settings.html','pipeline_form.html','inventory_management.html','_pipeline_management.html']) {
    const template=fs.readFileSync(path.join(root,'core/templates/core',name),'utf8');
    for (const match of template.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
      if (match[1].includes('application/json') || !match[2].trim()) continue;
      const code=match[2].replace(/\{%[\s\S]*?%\}/g,'').replace(/\{\{[\s\S]*?\}\}/g,'null');
      assert.doesNotThrow(()=>new vm.Script(code),name);
    }
  }
});
