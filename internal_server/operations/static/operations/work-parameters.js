/* Work observations inherit their work branch; building fields stay per building. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.FOSWorkParameters=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
    'use strict';
    function inherited(entries,id){
        const path=[],seen=new Set();let item=entries.get(String(id));
        while(item){if(seen.has(String(item.id)))throw Error('参数层级存在循环。');seen.add(String(item.id));path.unshift(item);item=entries.get(String(item.parent||''));}
        const result=new Map();for(const parent of path)for(const field of parent.parameters||[])result.set(field.key,{...field,owner_id:String(parent.id),owner_label:parent.name});return [...result.values()];
    }
    function activeFields(schema,nodeIds,locationIds){
        const nodes=new Map(schema.nodes.map(n=>[String(n.id),n])),places=new Map(schema.locations.map(p=>[String(p.id),p]));
        const work=new Map(),bindings=new Map(),locations=new Map();
        for(const id of [...nodeIds].map(String).sort())for(const field of inherited(nodes,id)){
            if(field.type==='location'){
                const previous=bindings.get(field.key);
                bindings.set(field.key,{...field,required:!!(field.required||previous?.required)});
            }else work.set(field.key,field);
        }
        for(const id of [...locationIds].map(String).sort())for(const field of inherited(places,id))if(bindings.has(field.key))locations.set(field.owner_id+':'+field.key,{...field,required:!!(field.required||bindings.get(field.key).required)});
        return {work:[...work.values()],locations:[...locations.values()]};
    }
    function mount(form,schema,onChange=()=>{}){
        const host=form.querySelector('#pestParameters');if(!host)return {sync(){},destroy(){}};
        const doc=form.ownerDocument,values=new Map(),controls=new Map();let fingerprint='';
        const key=(section,field)=>section+':'+(section==='locations'?field.owner_id||field.location_id:'')+':'+field.key;
        for(const section of ['work','locations'])for(const item of schema.values?.[section]||[])values.set(key(section,item),item);
        const hidden=doc.createElement('input');hidden.type='hidden';hidden.name='parameters';form.append(hidden);
        function serialize(){
            const result={work:[],locations:[]};
            for(const {section,field,input,readValue,readLabel} of controls.values()){
                const value=readValue?readValue():input.value;
                const item={key:field.key,value:value||null};if(section==='locations')item.location_id=field.owner_id;
                result[section].push(item);values.set(key(section,field),{...item,value_label:readLabel?readLabel():input.selectedOptions?.[0]?.textContent||input.value});
            }
            hidden.value=JSON.stringify(result);
        }
        function sync(){
            const ids=name=>[...form.querySelectorAll('input[name="'+name+'"]')].map(input=>input.value);
            const fields=activeFields(schema,ids('nodes'),ids('locations')),next=JSON.stringify(fields);
            if(next===fingerprint){serialize();return;}
            if(controls.size)serialize();fingerprint=next;host.replaceChildren();controls.clear();
            let count=0;
            for(const section of ['work','locations'])for(const field of fields[section]){
                const chips=field.type==='choice'&&field.key==='impact_direction';
                const row=doc.createElement(chips?'fieldset':'div');row.className=chips?'v2-fg v2-direction-field':'v2-fg';
                const label=doc.createElement(chips?'legend':'label');label.className='v2-fl';label.textContent=(section==='locations'?field.owner_label+' · ':'')+field.label+(field.unit?'（'+field.unit+'）':'');
                const old=values.get(key(section,field)),id='pestParameter'+(++count);let input,readValue=null,readLabel=null;
                if(chips){
                    input=doc.createElement('div');input.className='v2-direction-options';
                    const options=field.required?[...field.options]:[{value:'',label:'未记录'},...field.options];
                    if(old?.value!=null&&!field.options.some(choice=>choice.value===old.value))options.push({value:String(old.value),label:old.value_label||String(old.value),historical:true});
                    for(const option of options){
                        const choice=doc.createElement('label'),radio=doc.createElement('input'),caption=doc.createElement('span');choice.className='v2-direction-chip';
                        radio.type='radio';radio.name=id;radio.value=option.value;radio.required=!!field.required;radio.checked=option.value===(old?.value??'');radio.dataset.choiceLabel=option.label;
                        caption.textContent=option.label+(option.historical?'（历史选项）':'');choice.append(radio,caption);input.append(choice);
                    }
                    readValue=()=>input.querySelector('input:checked')?.value||'';
                    readLabel=()=>input.querySelector('input:checked')?.dataset.choiceLabel||'';
                }else if(field.type==='choice'){
                    input=doc.createElement('select');input.className='v2-select';
                    const blank=doc.createElement('option');blank.value='';blank.textContent=field.required?'请选择':'未记录 / 未选择';input.append(blank);
                    for(const choice of field.options){const option=doc.createElement('option');option.value=choice.value;option.textContent=choice.label;input.append(option);}
                    if(old?.value!=null&&!field.options.some(c=>c.value===old.value)){const option=doc.createElement('option');option.value=String(old.value);option.textContent=(old.value_label||old.value)+'（历史选项）';input.append(option);}
                }else{
                    input=doc.createElement('input');input.className='v2-input';input.type=['integer','number'].includes(field.type)?'number':field.type==='text'?'text':field.type;
                    if(field.type==='integer')input.step='1';if(field.type==='number')input.step='any';if(field.type==='text')input.maxLength=2000;if(field.type==='time')input.step='1';
                }
                input.id=id;if(!chips){input.required=!!field.required;input.value=old?.value??'';label.htmlFor=input.id;}
                input.addEventListener('input',()=>{serialize();onChange();});input.addEventListener('change',()=>{serialize();onChange();});
                row.append(label,input);host.append(row);controls.set(key(section,field),{section,field,input,readValue,readLabel});
            }
            host.hidden=!count;serialize();
        }
        const selection=()=>sync();form.addEventListener('pest-selection-change',selection);sync();
        return {sync,destroy(){form.removeEventListener('pest-selection-change',selection);hidden.remove();host.replaceChildren();}};
    }
    return {activeFields,mount};
});
