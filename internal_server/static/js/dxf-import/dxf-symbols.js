/* Review shape candidates and reuse examples across drawings. */
var pdxfShapeState={token:null,specs:Object.create(null),templates:[],learning:false,corner:null,rectangle:null,refs:[],busy:false};

function pdxfResetShapes(){
  pdxfStopShapeLearning();pdxfShapeState.token=null;pdxfShapeState.specs=Object.create(null);pdxfShapeState.refs=[];
  ['pdxfShapeStatus','pdxfSampleStatus'].forEach(function(id){pdxfStatus(id,'');});
}
function pdxfShapeChoices(useSuggestions){
  var items=pdxfData&&pdxfData.shape_candidates||[];
  if(pdxfShapeState.token!==pdxfToken){pdxfShapeState.token=pdxfToken;pdxfShapeState.specs=Object.create(null);}
  items.forEach(function(item){if(!pdxfShapeState.specs[item.id])pdxfShapeState.specs[item.id]={include:!!(useSuggestions&&item.include_guess),valve_type:item.valve_type_guess||''};});
  return pdxfShapeState.specs;
}
function pdxfCollectShapeSpecs(){
  var specs=pdxfShapeChoices();
  document.querySelectorAll('.pdxf-shape-include').forEach(function(input){if(specs[input.dataset.shape])specs[input.dataset.shape].include=input.checked;});
  document.querySelectorAll('.pdxf-shape-type').forEach(function(input){if(specs[input.dataset.shape])specs[input.dataset.shape].valve_type=input.value;});
  var result={};(pdxfData&&pdxfData.shape_candidates||[]).forEach(function(item){result[item.id]=Object.assign({},specs[item.id]);});
  var master=document.getElementById('pdxfShapeAll'),values=Object.values(result),count=values.filter(function(item){return item.include;}).length;
  if(master){master.checked=values.length>0&&count===values.length;master.indeterminate=count>0&&count<values.length;}
  return result;
}
function pdxfShapeOptions(chosen,placeholder){
  return '<option value="">'+(placeholder||'选择设备类型')+'</option>'+Object.keys(VALVE_LABELS).map(function(kind){
    return '<option value="'+kind+'"'+(chosen===kind?' selected':'')+'>'+pdxfEsc(VALVE_LABELS[kind])+'</option>';
  }).join('');
}
function pdxfRenderShapes(){
  var body=pdxfEl('pdxfShapeBody');if(!body)return;
  var items=pdxfData&&pdxfData.shape_candidates||[],specs=pdxfShapeChoices(true);
  pdxfEl('pdxfShapeCount').textContent=items.length+' 个多段线候选';
  pdxfEl('pdxfShapeTools').hidden=!items.length;
  pdxfEl('pdxfDeviceTab').textContent='设备 '+((pdxfData.blocks||[]).length+items.length);
  pdxfEl('pdxfShapeBulkType').innerHTML=pdxfShapeOptions('','批量选择类型…');
  body.innerHTML=items.map(function(item,index){var spec=specs[item.id];return '<tr data-filter="'+pdxfEsc(item.template_name+' '+item.text).toLowerCase()+'" data-shape-row="'+item.id+'">'+
    '<td><label class="pdxf-shape-check"><input type="checkbox" class="pdxf-shape-include" data-shape="'+item.id+'" aria-label="导入候选 '+(index+1)+'"'+(spec.include?' checked':'')+' onchange="pdxfMappingChanged()"></label></td>'+
    '<td><button type="button" class="pdxf-layer-name" data-shape="'+item.id+'" onclick="pdxfFocusShape(this.dataset.shape)">'+pdxfEsc(item.text||item.template_name)+' '+(index+1)+'</button><span class="pdxf-sub">'+pdxfEsc(item.reason)+' · 相似度 '+Math.round(item.confidence*100)+'%</span></td>'+
    '<td><select class="pdxf-select pdxf-shape-type" data-shape="'+item.id+'" aria-label="候选 '+(index+1)+' 设备类型" onchange="pdxfMappingChanged()">'+pdxfShapeOptions(spec.valve_type)+'</select></td></tr>';
  }).join('')||'<tr><td colspan="3" class="pdxf-muted">未找到常见阀门图形。可以圈选一个样本，查找不同画法的同类设备。</td></tr>';
  if(items.length>=600)pdxfEl('pdxfShapeCount').textContent+='（当前最多显示 600 个）';
}
function pdxfApplyShapeType(){
  var kind=pdxfEl('pdxfShapeBulkType').value;if(!kind)return;
  var specs=pdxfShapeChoices();(pdxfData.shape_candidates||[]).forEach(function(item){specs[item.id]={include:true,valve_type:kind};});
  pdxfRenderShapes();pdxfMappingChanged();
}
function pdxfSelectAllShapes(checked){
  document.querySelectorAll('.pdxf-shape-include').forEach(function(input){input.checked=checked;});pdxfMappingChanged();
}
function pdxfShapePart(layer,index,specs){
  return (pdxfData.shape_candidates||[]).find(function(item){return specs[item.id]&&specs[item.id].include&&item.source_refs.some(function(ref){return ref.layer===layer&&ref.index===index;});});
}
function pdxfShapePartLookup(specs){
  var lookup=Object.create(null);
  (pdxfData.shape_candidates||[]).forEach(function(item){if(specs[item.id]&&specs[item.id].include)item.source_refs.forEach(function(ref){lookup[ref.layer+'\u0000'+ref.index]=item;});});
  return lookup;
}
function pdxfFocusShape(id){
  var item=(pdxfData.shape_candidates||[]).find(function(value){return value.id===id;});if(!item)return;
  var b=item.bounds,corners=[[b[0],b[1]],[b[0],b[3]],[b[2],b[1]],[b[2],b[3]]].map(function(p){return pdxfGeographic({dxf_x:p[0],dxf_y:p[1]});}).filter(Boolean);
  if(corners.length)pdxfMap.fitBounds(L.latLngBounds(corners).pad(2),{maxZoom:22});
}
function pdxfDrawShapeCandidates(specs){
  if(!pdxfEl('pdxfShowDevices').checked)return;
  var raw=L.layerGroup().addTo(pdxfCadMap),geo=L.layerGroup().addTo(pdxfMap);
  (pdxfData.shape_candidates||[]).forEach(function(item){var selected=specs.shapes[item.id]&&specs.shapes[item.id].include;
    var style={radius:5,color:selected?'#347350':'#b47b31',weight:1.4,fillOpacity:selected ? .25 : 0,interactive:!pdxfCal.on,dashArray:selected?null:'3 2'};
    var text=pdxfEsc((item.text||item.template_name)+(selected?' · 已选中':' · 待核对'));
    L.circleMarker([item.y,item.x],style).bindTooltip(text).on('click',function(){pdxfFocusShape(item.id);}).addTo(raw);
    var point=pdxfGeographic(Object.assign({dxf_x:item.x,dxf_y:item.y},item));
    if(point)L.circleMarker(point,Object.assign({},style,{pane:'pdxfPreview',renderer:pdxfPreviewRenderer})).bindTooltip(text).on('click',function(){pdxfFocusShape(item.id);}).addTo(geo);
  });
  pdxfCadLayers.shapes=raw;pdxfLayers.shapes=geo;
}
function pdxfHasInlineSymbols(){
  return !!(pdxfData&&((pdxfData.labels||[]).some(function(layer){return layer.points.some(function(p){return p.inline_symbol;});})||
    (pdxfData.shape_candidates||[]).some(function(item){return item.text;})));
}
function pdxfInlineSymbolLabel(point,specs,reference,devices){
  if(!devices)return false;
  if(point.inline_symbol&&point.block&&((specs.blocks[point.block]&&specs.blocks[point.block].include)||reference))return true;
  return (pdxfData.shape_candidates||[]).some(function(item){return (item.label_refs||[]).includes(point.source_id)&&
    (reference||specs.shapes[item.id]&&specs.shapes[item.id].include);});
}
function pdxfTemplateParams(){
  var form=new FormData();form.append('token',pdxfToken);
  if(pdxfBatchMode&&pdxfEl('pdxfCalBatch').value)form.append('batch_id',pdxfEl('pdxfCalBatch').value);
  return form;
}
function pdxfRenderTemplates(items){
  pdxfShapeState.templates=items||[];var holder=pdxfEl('pdxfSavedShapeList');if(!holder)return;
  holder.innerHTML=items.map(function(item){return '<li><span>'+pdxfEsc(item.name)+'<small>'+pdxfEsc(item.valve_type_display)+'</small></span>'+
    (item.can_delete?'<button type="button" class="pdxf-template-delete" data-id="'+item.id+'" onclick="pdxfDeleteShapeTemplate(this.dataset.id)">删除</button>':'')+'</li>';
  }).join('')||'<li class="pdxf-muted">尚无自定义图形。保存一次后，可以在其他 DXF 中复用。</li>';
}
function pdxfRefreshShapeCandidates(){
  if(!pdxfData||!pdxfToken)return Promise.resolve();
  var token=pdxfToken,form=pdxfTemplateParams();form.append('action','recognize');
  return pdxfPost(window.__DXF__.urls.symbolTemplates,form).then(function(data){
    if(token!==pdxfToken)return;
    pdxfData.shape_candidates=data.shape_candidates||[];pdxfRenderTemplates(data.templates);pdxfRenderShapes();pdxfMappingChanged();
  });
}
function pdxfDeleteShapeTemplate(id){
  if(pdxfShapeState.busy)return;pdxfShapeState.busy=true;
  var form=new FormData();form.append('action','delete');form.append('id',id);
  pdxfPost(window.__DXF__.urls.symbolTemplates,form).then(function(data){pdxfRenderTemplates(data.templates);return pdxfRefreshShapeCandidates();})
    .catch(function(error){pdxfStatus('pdxfShapeStatus',error.message,true);}).finally(function(){pdxfShapeState.busy=false;});
}
function pdxfLoadShapeTemplates(){
  fetch(window.__DXF__.urls.symbolTemplates,{credentials:'same-origin'}).then(function(response){return response.json();}).then(function(data){
    if(!data.success)throw Error(data.error||'图形模板加载失败');pdxfRenderTemplates(data.templates);
  }).catch(function(error){pdxfStatus('pdxfShapeStatus',error.message,true);});
}
function pdxfStartShapeLearning(){
  if(!pdxfData||pdxfBusy||pdxfShapeState.busy)return;
  if(pdxfCal.on)pdxfCalStop();pdxfStopShapeLearning();
  pdxfShapeState.learning=true;pdxfShapeState.corner=null;pdxfShapeState.refs=[];
  pdxfEl('pdxfSamplePanel').hidden=false;pdxfEl('pdxfSampleSave').disabled=true;
  pdxfEl('pdxfSampleType').innerHTML=pdxfShapeOptions('');
  pdxfStatus('pdxfSampleStatus','点击阀门样本范围的两个对角，只框住完整符号。');
  pdxfEl('pdxfOriginalDialog').classList.add('pdxf-sampling');
  if(!pdxfEl('pdxfOriginalDialog').open)pdxfOpenOriginal();
  pdxfCadMap.invalidateSize();pdxfCadMap.on('click',pdxfShapeSampleClick);pdxfCadMap.on('mousemove',pdxfShapeSampleMove);
}
function pdxfStopShapeLearning(){
  pdxfShapeState.learning=false;pdxfShapeState.corner=null;
  if(typeof pdxfCadMap!=='undefined'&&pdxfCadMap){pdxfCadMap.off('click',pdxfShapeSampleClick);pdxfCadMap.off('mousemove',pdxfShapeSampleMove);
    if(pdxfShapeState.rectangle)pdxfCadMap.removeLayer(pdxfShapeState.rectangle);}
  pdxfShapeState.rectangle=null;
  pdxfShapeState.refs=[];
  var panel=document.getElementById('pdxfSamplePanel'),dialog=document.getElementById('pdxfOriginalDialog');
  if(panel)panel.hidden=true;if(dialog)dialog.classList.remove('pdxf-sampling');
}
function pdxfShapeSampleMove(event){
  if(!pdxfShapeState.learning||!pdxfShapeState.corner)return;
  var box=L.latLngBounds(pdxfShapeState.corner,event.latlng);
  if(!pdxfShapeState.rectangle)pdxfShapeState.rectangle=L.rectangle(box,{color:'#347350',weight:2,fillOpacity:.08,interactive:false}).addTo(pdxfCadMap);
  else pdxfShapeState.rectangle.setBounds(box);
}
function pdxfShapeSampleClick(event){
  if(!pdxfShapeState.learning)return;
  if(!pdxfShapeState.corner){pdxfShapeState.corner=event.latlng;pdxfStatus('pdxfSampleStatus','再点击范围的另一个对角。');return;}
  var box=L.latLngBounds(pdxfShapeState.corner,event.latlng),refs=[];
  pdxfShapeSampleMove(event);
  pdxfData.preview.layers.forEach(function(layer){layer.paths.forEach(function(path,index){
    if(path.length&&path.every(function(p){return box.contains([p.dxf_y,p.dxf_x]);}))refs.push({layer:layer.layer,index:index});
  });});
  pdxfShapeState.corner=null;pdxfShapeState.refs=refs;
  if(!refs.length||refs.length>20){pdxfEl('pdxfSampleSave').disabled=true;pdxfStatus('pdxfSampleStatus',refs.length?'圈入图形过多，请缩小范围后重选。':'没有框入完整图形，请重新点击两个对角。',true);return;}
  pdxfEl('pdxfSampleSave').disabled=false;
  pdxfStatus('pdxfSampleStatus','已圈入 '+refs.length+' 个图形。填写名称和类型后，保存并查找同类。');
}
function pdxfSaveShapeTemplate(){
  if(pdxfShapeState.busy||!pdxfShapeState.refs.length)return;
  var name=pdxfEl('pdxfSampleName').value.trim(),kind=pdxfEl('pdxfSampleType').value;
  if(!name||!kind){pdxfStatus('pdxfSampleStatus','请填写图形名称并选择设备类型。',true);return;}
  var token=pdxfToken,form=pdxfTemplateParams();form.append('name',name);form.append('valve_type',kind);form.append('parts_json',JSON.stringify(pdxfShapeState.refs));
  pdxfShapeState.busy=true;pdxfEl('pdxfSampleSave').disabled=true;
  pdxfPost(window.__DXF__.urls.symbolTemplates,form).then(function(data){
    if(token!==pdxfToken)return;pdxfRenderTemplates(data.templates);return pdxfRefreshShapeCandidates();
  }).then(function(){if(token!==pdxfToken)return;pdxfStopShapeLearning();pdxfEl('pdxfSamplePanel').hidden=true;pdxfEl('pdxfOriginalDialog').close();pdxfStatus('pdxfShapeStatus','图形已保存并完成识别，可在其他 DXF 中复用。');})
    .catch(function(error){pdxfStatus('pdxfSampleStatus',error.message||'保存失败，请重试。',true);})
    .finally(function(){pdxfShapeState.busy=false;pdxfEl('pdxfSampleSave').disabled=false;});
}
function pdxfSymbolsInit(){
  var dialog=pdxfEl('pdxfOriginalDialog');dialog.addEventListener('close',pdxfStopShapeLearning);
  pdxfLoadShapeTemplates();
}
