'use strict';

(() => {
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));

  function endpointHost(value){
    let text=String(value??'').trim();
    if(!text)return '';
    try{
      if(text.includes('://')){
        const parsed=new URL(text);
        return String(parsed.hostname||'').trim().replace(/^\[|\]$/g,'').replace(/\.$/,'').toLowerCase();
      }
    }catch(_error){}
    text=text.split(/[/?#]/,1)[0].trim();
    const bracketed=text.match(/^\[([^\]]+)\](?::\d+)?$/);
    if(bracketed)return bracketed[1].replace(/\.$/,'').toLowerCase();
    const colonCount=(text.match(/:/g)||[]).length;
    if(colonCount===1)text=text.slice(0,text.lastIndexOf(':'));
    return text.replace(/\.$/,'').toLowerCase();
  }

  function fieldSubject(value){
    let text=String(value??'').trim();
    if(!text)return '';
    text=text.replace(/(?:[_\s-]+(?:status|state|health))$/i,'');
    text=text.replace(/[_-]+/g,' ');
    text=text.replace(/([A-Za-z])(\d+)/g,'$1 $2').replace(/(\d+)([A-Za-z])/g,'$1 $2');
    text=text.replace(/\s+/g,' ').trim();
    if(!text)return '';
    const words=text.split(' ').map((word,index)=>{
      if(/^[A-Z0-9]+$/.test(word)&&/[A-Z]/.test(word))return word;
      const lower=word.toLowerCase();
      return index===0?lower.charAt(0).toUpperCase()+lower.slice(1):lower;
    });
    return words.join(' ');
  }

  function maintenanceSubject(maintenance){
    const explicit=String(maintenance?.subject||maintenance?.label||'').trim();
    if(explicit)return fieldSubject(explicit);
    const subjects=[...new Set((Array.isArray(maintenance?.fields)?maintenance.fields:[])
      .map(fieldSubject).filter(Boolean))];
    if(!subjects.length)return '';
    if(subjects.length===1)return subjects[0];
    if(subjects.length===2)return `${subjects[0]} + ${subjects[1]}`;
    return `${subjects[0]} + ${subjects[1]} + ${subjects.length-2} more`;
  }

  function maintenanceFacts(object,limit=2){
    if(!object || String(object.state||'').toLowerCase()!=='healthy')return [];
    const facts=[];
    for(const component of object.components||[]){
      if(!component || component.enabled===false)continue;
      const metadata=component.metadata;
      const maintenance=metadata&&typeof metadata==='object'?metadata.maintenance:null;
      if(!maintenance || typeof maintenance!=='object' || maintenance.health_neutral!==true)continue;
      const state=String(maintenance.state||'').trim();
      if(!state)continue;
      const subject=maintenanceSubject(maintenance);
      const fact=subject?`${subject} ${state.toLocaleLowerCase()}`:state;
      if(!facts.includes(fact))facts.push(fact);
      if(facts.length>=limit)break;
    }
    return facts;
  }

  function maintenanceMarkup(object){
    const facts=maintenanceFacts(object);
    if(!facts.length)return '';
    return `<span class="phase6-maintenance" data-maintenance-health-neutral="true">${esc(facts.join(' · '))}</span>`;
  }

  function workspaceRelationships(model){
    const systems=Array.isArray(model?.systems)?model.systems:[];
    const objects=Array.isArray(model?.objects)?model.objects:[];
    const connections=Array.isArray(model?.connections)?model.connections:[];
    const systemById=new Map(systems.map(item=>[String(item.id||''),item]).filter(([id])=>id));
    const systemIds=new Set(systemById.keys());
    const objectById=new Map(objects.map(item=>[String(item.id||''),item]));
    const bySystem=new Map(systems.map(item=>[String(item.id||''),[]]));
    const byConnection=new Map();

    for(const connection of connections){
      const connectionId=String(connection?.id||'');
      if(!connectionId)continue;
      const exposedIds=[...new Set((connection.exposes_object_ids||[]).map(String).filter(Boolean))];
      const exposed=exposedIds.map(id=>objectById.get(id)).filter(Boolean);
      byConnection.set(connectionId,{connection,objects:exposed});

      const parents=new Set((connection.parent_ids||[]).map(String).filter(id=>systemIds.has(id)));
      for(const object of exposed){
        for(const dependency of object.depends_on||[]){
          const id=String(dependency||'');
          if(systemIds.has(id))parents.add(id);
        }
      }
      for(const systemId of parents){
        bySystem.get(systemId)?.push({connection,objects:exposed});
      }
    }

    // Physical Broad Leaf acceptance exposed a generic provenance gap: a
    // Connection may be hosted by a System without an explicit System parent.
    // Fall back only when the normalized Connection host exactly matches one
    // unique System address, and only for Connections with no explicit path.
    const assigned=new Set();
    for(const paths of bySystem.values()){
      for(const path of paths)assigned.add(String(path?.connection?.id||''));
    }
    const systemsByAddress=new Map();
    for(const system of systems){
      const host=endpointHost(system?.address);
      if(!host)continue;
      if(!systemsByAddress.has(host))systemsByAddress.set(host,[]);
      systemsByAddress.get(host).push(system);
    }
    for(const connection of connections){
      const connectionId=String(connection?.id||'');
      if(!connectionId || assigned.has(connectionId))continue;
      const host=endpointHost(connection?.endpoint||[connection?.host,connection?.port].filter(value=>value!==undefined&&value!==null&&String(value)!=='').join(':'));
      if(!host)continue;
      const matches=systemsByAddress.get(host)||[];
      if(matches.length!==1)continue;
      const path=byConnection.get(connectionId);
      if(!path)continue;
      bySystem.get(String(matches[0].id||''))?.push(path);
      assigned.add(connectionId);
    }

    const systemsByConnection=new Map(connections.map(connection=>[String(connection?.id||''),[]]));
    for(const [systemId,paths] of bySystem){
      const system=systemById.get(systemId);
      if(!system)continue;
      for(const path of paths){
        const connectionId=String(path?.connection?.id||'');
        if(!connectionId)continue;
        const related=systemsByConnection.get(connectionId)||[];
        if(!related.some(item=>String(item.id||'')===systemId))related.push(system);
        systemsByConnection.set(connectionId,related);
      }
    }
    return {bySystem,byConnection,systemsByConnection};
  }

  function targetSelector(kind,id){
    const safe=globalThis.CSS?.escape?globalThis.CSS.escape(String(id)):String(id).replace(/["\\]/g,'\\$&');
    return `[data-workspace-${kind}="${safe}"]`;
  }

  function relationButton(kind,id,label){
    return `<button type="button" class="phase6-relation-link" data-phase6-kind="${esc(kind)}" data-phase6-id="${esc(id)}">${esc(label)}</button>`;
  }

  function categoryLabel(kind){
    const normalized=String(kind||'object').trim().toLowerCase();
    const labels={ups:'Power / UPS',camera:'Cameras',service:'Services'};
    return labels[normalized]||normalized.replaceAll('_',' ').replace(/\b\w/g,ch=>ch.toUpperCase());
  }

  function decorateObjectIndex(model,root){
    const container=root.querySelector?.('#objectRows');
    if(!container)return;
    container.querySelector?.('.phase6-object-index')?.remove();
    const groups=new Map();
    for(const object of model.objects||[]){
      const kind=String(object?.kind||'object').trim().toLowerCase()||'object';
      if(!groups.has(kind))groups.set(kind,[]);
      groups.get(kind).push(object);
    }
    if(!groups.size)return;
    const index=document.createElement('div');
    index.className='phase6-object-index';
    index.dataset.phase6ObjectIndex='true';
    index.innerHTML=`<span class="phase6-relation-heading">Object index</span>${[...groups.entries()].map(([kind,items])=>`<span class="phase6-object-category" data-phase6-category="${esc(kind)}"><span>${esc(categoryLabel(kind))} (${items.length})</span><span class="phase6-relation-path">${items.map(item=>relationButton('object',item.id,item.label||item.id)).join('')}</span></span>`).join('')}`;
    container.prepend(index);
  }

  function decorateWorkspace(model,root=document){
    if(!model||!root?.querySelectorAll)return;
    root.querySelectorAll('.phase6-relations').forEach(node=>node.remove());
    root.querySelectorAll('.phase6-object-index').forEach(node=>node.remove());
    decorateObjectIndex(model,root);
    const graph=workspaceRelationships(model);

    for(const system of model.systems||[]){
      const systemId=String(system.id||'');
      const paths=graph.bySystem.get(systemId)||[];
      if(!paths.length)continue;
      const row=root.querySelector(targetSelector('system',systemId));
      const first=row?.firstElementChild;
      if(!first)continue;
      const box=document.createElement('div');
      box.className='phase6-relations';
      box.dataset.phase6Relationship='system-connections';
      box.innerHTML=`<span class="phase6-relation-heading">Connections</span>${paths.map(path=>{
        const connectionLabel=path.connection.label||path.connection.adapter||path.connection.id;
        const objects=path.objects.map(object=>relationButton('object',object.id,object.label||object.id)).join('');
        return `<span class="phase6-relation-path">${relationButton('connection',path.connection.id,connectionLabel)}${objects?`<span aria-hidden="true">→</span>${objects}`:''}</span>`;
      }).join('')}`;
      first.append(box);
    }

    for(const [connectionId,path] of graph.byConnection){
      if(!path.objects.length)continue;
      const row=root.querySelector(targetSelector('connection',connectionId));
      const first=row?.firstElementChild;
      if(!first)continue;
      const box=document.createElement('div');
      box.className='phase6-relations';
      box.dataset.phase6Relationship='connection-objects';
      box.innerHTML=`<span class="phase6-relation-heading">Objects</span><span class="phase6-relation-path">${path.objects.map(object=>relationButton('object',object.id,object.label||object.id)).join('')}</span>`;
      first.append(box);
    }

    root.querySelectorAll('.phase6-relation-link').forEach(button=>{
      button.onclick=()=>{
        const target=root.querySelector(targetSelector(button.dataset.phase6Kind,button.dataset.phase6Id));
        if(!target)return;
        target.scrollIntoView?.({behavior:'smooth',block:'center'});
        target.classList.add('phase6-related-target');
        target.setAttribute?.('tabindex','-1');
        target.focus?.({preventScroll:true});
        setTimeout(()=>target.classList.remove('phase6-related-target'),1400);
      };
    });
  }

  globalThis.MonitorBoxPhase6Convergence={
    endpointHost,maintenanceSubject,maintenanceFacts,maintenanceMarkup,
    workspaceRelationships,categoryLabel,decorateObjectIndex,decorateWorkspace
  };
})();
