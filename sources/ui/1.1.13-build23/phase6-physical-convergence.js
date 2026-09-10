'use strict';

(()=>{
  const phase6=globalThis.MonitorBoxPhase6Convergence||{};
  const SYSTEM_KINDS=new Set(['host','appliance','network_device','remote_site']);
  let workspaceModel=null;
  let workspaceFetch=null;
  let advancedScheduled=false;

  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));

  function maintenanceMarkup(object){
    return typeof phase6.maintenanceMarkup==='function'?phase6.maintenanceMarkup(object):'';
  }

  function installParityMaintenance(){
    if(typeof parityCoreCard!=='function' || parityCoreCard?.phase6Build23)return false;
    const base=parityCoreCard;
    const wrapped=function(site,object){
      const markup=base(site,object);
      const maintenance=maintenanceMarkup(object);
      if(!maintenance)return markup;
      return markup.replace('</button>',`${maintenance}</button>`);
    };
    wrapped.phase6Build23=true;
    parityCoreCard=wrapped;
    if(typeof app!=='undefined'&&app?.state&&typeof render==='function')render();
    return true;
  }

  function relationGraph(model){
    if(typeof phase6.workspaceRelationships==='function')return phase6.workspaceRelationships(model);
    return {bySystem:new Map(),byConnection:new Map(),systemsByConnection:new Map()};
  }

  function currentWorkingSite(){
    if(typeof working==='undefined'||!working||typeof siteId==='undefined')return null;
    return (working.sites||[]).find(site=>String(site.id)===String(siteId))||null;
  }

  function nativeObject(id){
    const site=currentWorkingSite();
    return site?.objects?.find(item=>String(item.id)===String(id))||null;
  }

  function selectNativeObject(id){
    if(!nativeObject(id))return false;
    objectId=String(id);
    if(typeof renderEditor==='function')renderEditor();
    scheduleAdvanced();
    return true;
  }

  function kindLabel(kind){
    const normalized=String(kind||'object').trim().toLowerCase();
    const known={
      ups:'UPS',camera:'Cameras',cameras:'Cameras',service:'Services',
      service_group:'Service groups',integration:'Integrations',grouped_object:'Grouped objects',
    };
    return known[normalized]||normalized.replaceAll('_',' ').replace(/\b\w/g,ch=>ch.toUpperCase());
  }

  function rowButton(kind,id,label,meta=''){
    const canSelect=kind!=='connection'&&!!nativeObject(id);
    return `<button class="phase6-advanced-row${canSelect?'':' relation-only'}" type="button" data-phase6-advanced-kind="${esc(kind)}" data-phase6-advanced-id="${esc(id)}"${canSelect?'':' aria-disabled="true"'}><span><strong>${esc(label||id)}</strong>${meta?`<small>${esc(meta)}</small>`:''}</span></button>`;
  }

  function connectionDisplayLabel(connection,graph){
    const id=String(connection?.id||'');
    const base=String(connection?.label||connection?.adapter||id||'Connection');
    const systems=graph?.systemsByConnection?.get(id)||[];
    if(systems.length!==1)return base;
    const systemLabel=String(systems[0]?.label||systems[0]?.id||'').trim();
    if(!systemLabel || base.toLowerCase().includes(systemLabel.toLowerCase()))return base;
    return `${base} · ${systemLabel}`;
  }

  function connectionRow(path,graph){
    const connection=path.connection||path;
    const id=String(connection.id||'');
    const label=connectionDisplayLabel(connection,graph);
    const endpoint=connection.endpoint||[connection.host,connection.port].filter(value=>value!==undefined&&value!==null&&String(value)!=='').join(':');
    const objects=path.objects||[];
    const objectRefs=objects.map(object=>rowButton('object',object.id,object.label||object.id,kindLabel(object.kind))).join('');
    return `<div class="phase6-advanced-connection" data-phase6-connection="${esc(id)}"><div class="phase6-advanced-connection-head"><strong>${esc(label)}</strong><small>${esc([connection.adapter,endpoint].filter(Boolean).join(' · '))}</small></div>${objectRefs?`<div class="phase6-advanced-path"><span>Objects</span>${objectRefs}</div>`:''}</div>`;
  }

  function systemRow(system,graph){
    const id=String(system.id||'');
    const paths=graph.bySystem?.get(id)||[];
    return `<div class="phase6-advanced-system" data-phase6-system="${esc(id)}">${rowButton('system',id,system.label||id,kindLabel(system.kind))}${paths.length?`<div class="phase6-advanced-system-paths"><span class="phase6-advanced-path-label">Connections</span>${paths.map(path=>connectionRow(path,graph)).join('')}</div>`:''}</div>`;
  }

  function groupMarkup(label,count,body,kind=''){
    return `<details class="tree-group phase6-advanced-group" ${kind?`data-phase6-category="${esc(kind)}"`:''}><summary>${esc(label)} (${count})</summary><div class="tree-group-body phase6-advanced-group-body">${body}</div></details>`;
  }

  function buildAdvancedMarkup(model,term=''){
    const systems=Array.isArray(model?.systems)?model.systems:[];
    const connections=Array.isArray(model?.connections)?model.connections:[];
    const objects=Array.isArray(model?.objects)?model.objects:[];
    const graph=relationGraph(model);
    const needle=String(term||'').trim().toLowerCase();
    const matches=item=>!needle||`${item?.label||''} ${item?.id||''} ${item?.kind||''} ${item?.adapter||''} ${item?.endpoint||''}`.toLowerCase().includes(needle);

    const sections=[];
    const systemRows=systems.filter(system=>matches(system)||((graph.bySystem?.get(String(system.id||''))||[]).some(path=>matches(path.connection)||path.objects.some(matches))));
    if(systemRows.length||!needle)sections.push(groupMarkup('Systems',systems.length,systemRows.map(system=>systemRow(system,graph)).join('')||'<div class="tree-empty">No Systems match this search.</div>','systems'));

    const connectionRows=connections.map(connection=>graph.byConnection?.get(String(connection.id||''))||{connection,objects:[]}).filter(path=>{
      if(matches(path.connection)||path.objects.some(matches))return true;
      const related=graph.systemsByConnection?.get(String(path.connection?.id||''))||[];
      return related.some(matches);
    });
    if(connectionRows.length||!needle)sections.push(groupMarkup('Connections',connections.length,connectionRows.map(path=>connectionRow(path,graph)).join('')||'<div class="tree-empty">No Connections match this search.</div>','connections'));

    const groups=new Map();
    for(const object of objects){
      const kind=String(object?.kind||'object').trim().toLowerCase()||'object';
      if(SYSTEM_KINDS.has(kind))continue;
      if(!groups.has(kind))groups.set(kind,[]);
      groups.get(kind).push(object);
    }
    const ordered=[...groups.entries()].sort(([left],[right])=>{
      const rank=value=>value==='ups'?0:(value==='camera'||value==='cameras')?1:value==='service'?2:3;
      return rank(left)-rank(right)||kindLabel(left).localeCompare(kindLabel(right));
    });
    for(const [kind,items] of ordered){
      const visible=items.filter(matches);
      if(!visible.length&&needle)continue;
      sections.push(groupMarkup(`Objects · ${kindLabel(kind)}`,items.length,visible.map(object=>rowButton('object',object.id,object.label||object.id,object.id)).join('')||'<div class="tree-empty">No Objects match this search.</div>',kind));
    }
    return sections.join('')||'<div class="tree-empty">No canonical Systems, Connections, or Objects match this search.</div>';
  }

  function advancedSummary(model){
    const systems=Array.isArray(model?.systems)?model.systems:[];
    const connections=Array.isArray(model?.connections)?model.connections:[];
    const objects=Array.isArray(model?.objects)?model.objects:[];
    const ups=objects.filter(item=>String(item?.kind||'').toLowerCase()==='ups').length;
    const cameras=objects.filter(item=>['camera','cameras'].includes(String(item?.kind||'').toLowerCase())).length;
    return `Systems ${systems.length} · Connections ${connections.length} · Objects ${objects.length} (UPS ${ups}, Cameras ${cameras}) · select any item to inspect Abilities / Metrics`;
  }

  function renderAdvanced(model){
    if(location.pathname!=='/settings/advanced'||!model)return false;
    const native=document.getElementById('objects');
    const search=document.getElementById('objectSearch');
    if(!native||!search)return false;
    native.classList.add('phase6-native-tree');
    native.setAttribute('aria-hidden','true');

    const oldIndex=document.getElementById('advancedSemanticIndex');
    if(oldIndex)oldIndex.hidden=true;
    const h3=native.closest('aside')?.querySelector('.section-head h3');
    if(h3)h3.textContent='Systems · Connections · Objects';
    search.placeholder='Find a System / Connection / Object…';

    let summary=document.getElementById('phase6AdvancedSummary');
    if(!summary){
      summary=document.createElement('div');
      summary.id='phase6AdvancedSummary';
      summary.className='advanced-semantic-index phase6-advanced-summary';
      search.insertAdjacentElement('afterend',summary);
    }
    summary.textContent=advancedSummary(model);

    let index=document.getElementById('phase6AdvancedIndex');
    if(!index){
      index=document.createElement('div');
      index.id='phase6AdvancedIndex';
      index.className='object-list phase6-advanced-index';
      summary.insertAdjacentElement('afterend',index);
    }
    index.innerHTML=buildAdvancedMarkup(model,search.value);
    for(const details of index.querySelectorAll('details'))details.open=!!search.value;
    index.querySelectorAll('[data-phase6-advanced-id]').forEach(button=>{
      const kind=button.dataset.phase6AdvancedKind;
      if(kind==='connection')return;
      button.onclick=()=>selectNativeObject(button.dataset.phase6AdvancedId);
    });
    return true;
  }

  async function loadWorkspaceModel({fresh=false}={}){
    if(!fresh&&workspaceModel)return workspaceModel;
    if(workspaceFetch)return workspaceFetch;
    workspaceFetch=fetch('/api/v2/config/workspace/state',{headers:{Accept:'application/json'},cache:'no-store'})
      .then(async response=>{
        if(!response.ok)throw new Error(`workspace state HTTP ${response.status}`);
        workspaceModel=await response.json();
        return workspaceModel;
      })
      .finally(()=>{workspaceFetch=null;});
    return workspaceFetch;
  }

  function scheduleAdvanced(){
    if(location.pathname!=='/settings/advanced'||advancedScheduled)return;
    advancedScheduled=true;
    queueMicrotask(async()=>{
      advancedScheduled=false;
      try{renderAdvanced(await loadWorkspaceModel());}catch(_error){}
    });
  }

  function installAdvanced(){
    if(location.pathname!=='/settings/advanced')return;
    const search=document.getElementById('objectSearch');
    search?.addEventListener('input',scheduleAdvanced);
    const native=document.getElementById('objects');
    if(native)new MutationObserver(scheduleAdvanced).observe(native,{childList:true,subtree:true});
    if(typeof load==='function'&&!load.phase6Build23){
      const baseLoad=load;
      const wrapped=async function(...args){
        const result=await baseLoad(...args);
        workspaceModel=null;
        try{renderAdvanced(await loadWorkspaceModel({fresh:true}));}catch(_error){}
        return result;
      };
      wrapped.phase6Build23=true;
      load=wrapped;
    }
    scheduleAdvanced();
  }

  globalThis.MonitorBoxPhase6Physical=Object.freeze({
    advancedSummary,buildAdvancedMarkup,connectionDisplayLabel,installParityMaintenance,kindLabel,renderAdvanced,
  });

  if(typeof document!=='undefined'){
    const start=()=>{
      installParityMaintenance();
      installAdvanced();
      // Some dashboard compatibility layers replace parityCoreCard after this
      // script is parsed; one microtask catches that without creating a timer.
      queueMicrotask(installParityMaintenance);
    };
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});
    else start();
  }
})();
