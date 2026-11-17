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
        const requested=new Set([...nodeIds].map(String));
        for(const id of [...requested]){let node=nodes.get(id);const seen=new Set();while(node&&!seen.has(String(node.id))){seen.add(String(node.id));for(const item of node.related_forms||[])requested.add(String(item.id));node=nodes.get(String(node.parent||''));}}
        for(const id of [...requested].sort())for(const field of inherited(nodes,id)){
            if(field.type==='location'){
                const previous=bindings.get(field.key);
                bindings.set(field.key,{...field,required:!!(field.required||previous?.required)});
            }else work.set(field.key,field);
        }
        for(const id of [...locationIds].map(String).sort())for(const field of inherited(places,id))if(bindings.has(field.key))locations.set(field.owner_id+':'+field.key,{...field,required:!!(field.required||bindings.get(field.key).required)});
        return {work:[...work.values()],locations:[...locations.values()]};
    }
    function editableChoice(doc,input,id,field){
        const wrap=doc.createElement('div'),toggle=doc.createElement('button'),list=doc.createElement('div');
        wrap.className='pest-parameter-combo';toggle.type='button';toggle.className='pest-combo-toggle';
        toggle.setAttribute('aria-label','展开'+field.label+'选项');toggle.setAttribute('aria-controls',id+'Options');
        toggle.innerHTML='<svg class="ui-icon" aria-hidden="true"><use href="#pwa-chevron-down"/></svg>';
        list.id=id+'Options';list.className='pest-combo-options';list.hidden=true;list.setAttribute('role','listbox');list.setAttribute('aria-label',field.label+'选项');
        input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');input.setAttribute('aria-controls',list.id);input.autocomplete='off';
        const choices=field.options||[];let matches=[],active=-1;
        function close(){list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;}
        function choose(choice){input.value=choice.value;input.dispatchEvent(new doc.defaultView.Event('input',{bubbles:true}));input.focus();close();}
        function open(all=false){
            const query=input.value.trim().toLocaleLowerCase();active=-1;list.replaceChildren();input.removeAttribute('aria-activedescendant');
            matches=choices.filter(choice=>all||!query||(choice.value+' '+choice.label).toLocaleLowerCase().includes(query));
            matches.forEach((choice,index)=>{
                const option=doc.createElement('button');option.type='button';option.tabIndex=-1;option.id=id+'Option'+index;option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.textContent=choice.label;
                option.addEventListener('pointerdown',event=>event.preventDefault());option.addEventListener('click',()=>choose(choice));list.append(option);
            });
            if(!matches.length){const empty=doc.createElement('div');empty.className='pest-combo-empty';empty.textContent='暂无已有选项';list.append(empty);}
            list.hidden=false;input.setAttribute('aria-expanded','true');
        }
        input.addEventListener('focus',()=>open(true));input.addEventListener('input',()=>open());
        input.addEventListener('keydown',event=>{
            if(event.isComposing)return;
            if(event.key==='Escape'&&!list.hidden){event.preventDefault();event.stopPropagation();close();}
            else if(event.key==='ArrowDown'||event.key==='ArrowUp'){
                event.preventDefault();if(list.hidden)open(true);if(!matches.length)return;
                active=active<0?(event.key==='ArrowUp'?matches.length-1:0):Math.max(0,Math.min(matches.length-1,active+(event.key==='ArrowDown'?1:-1)));
                [...list.querySelectorAll('[role=option]')].forEach((option,index)=>{option.setAttribute('aria-selected',String(index===active));if(index===active){input.setAttribute('aria-activedescendant',option.id);option.scrollIntoView?.({block:'nearest'});}});
            }else if(event.key==='Enter'&&!list.hidden&&active>=0){event.preventDefault();choose(matches[active]);}
        });
        toggle.addEventListener('click',()=>{const expand=list.hidden;input.focus();if(expand)open(true);else close();});
        wrap.addEventListener('focusout',event=>{if(!wrap.contains(event.relatedTarget))close();});
        wrap.append(input,toggle,list);return wrap;
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
            const fields=activeFields(schema,ids('nodes'),ids('locations')),next=JSON.stringify([fields,ids('nodes')]);
            if(next===fingerprint){serialize();return;}
            if(controls.size)serialize();fingerprint=next;host.replaceChildren();controls.clear();
            let count=0;
            const related=new Map(),nodes=new Map(schema.nodes.map(n=>[String(n.id),n]));
            for(const id of ids('nodes')){let node=nodes.get(id);const seen=new Set();while(node&&!seen.has(String(node.id))){seen.add(String(node.id));for(const item of node.related_forms||[])related.set(item.id,item);node=nodes.get(String(node.parent||''));}}
            for(const item of related.values()){const prompt=doc.createElement('p');prompt.className='pest-related-form-prompt';prompt.setAttribute('role','note');prompt.textContent=item.prompt;host.append(prompt);}
            for(const section of ['work','locations'])for(const field of fields[section]){
                if(section==='work'&&field.hidden)continue;
                const chips=field.type==='choice'&&field.key==='impact_direction';
                const row=doc.createElement(chips?'fieldset':'div');row.className=chips?'v2-fg v2-direction-field':'v2-fg';
                const label=doc.createElement(chips?'legend':'label');label.className='v2-fl';label.textContent=(section==='locations'?field.owner_label+' · ':'')+field.label+(field.unit?'（'+field.unit+'）':'');
                const old=values.get(key(section,field)),id='pestParameter'+(++count);let input,widget,readValue=null,readLabel=null;
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
                }else if(field.allow_custom){
                    input=doc.createElement('input');input.type='text';input.className='v2-input';input.maxLength=2000;
                    widget=editableChoice(doc,input,id,field);
                    readLabel=()=>field.options.find(choice=>choice.value===input.value)?.label||input.value;
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
                row.append(label,widget||input);host.append(row);controls.set(key(section,field),{section,field,input,readValue,readLabel});
            }
            host.hidden=!count;serialize();
        }
        const selection=()=>sync();form.addEventListener('pest-selection-change',selection);sync();
        return {sync,destroy(){form.removeEventListener('pest-selection-change',selection);hidden.remove();host.replaceChildren();}};
    }
    return {activeFields,mount};
});
