'use strict';

// UI 1.1.6 build 14 — Broad Leaf physical-acceptance repairs.
//
// #164: provide an operator-facing Portainer environment scope editor on the
// existing protected Advanced Configuration plane. Environment inventory is
// obtained through the existing provider-test seam with scope temporarily
// removed, so ignored environments stay visible for explicit re-selection.
// #206: reconcile provider-only workload rows to canonical objects that already
// own a safe HTTP(S) presentation URL when provider-native identity, exact
// endpoint evidence, or owner+semantic identity yields one unique match. TCP
// transport evidence is correlation-only and can never synthesize a web URL.
// Dividend: preserve the actual managed adapter value in Advanced Configuration
// even when frozen Core's static adapter catalog does not list that module.

(()=>{
  function token(value){
    return String(value||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,'');
  }

  function safeHttpUrl(value){
    const text=String(value||'').trim();
    if(!text)return null;
    try{
      const parsed=new URL(text);
      return parsed.protocol==='http:'||parsed.protocol==='https:'?parsed.href:null;
    }catch(_error){return null;}
  }

  function presentationEndpoint(value){
    const safe=safeHttpUrl(value);
    if(!safe)return null;
    try{
      const parsed=new URL(safe);
      const host=String(parsed.hostname||'').trim().toLowerCase().replace(/^\[|\]$/g,'');
      const port=Number(parsed.port||(parsed.protocol==='https:'?443:80));
      return host&&Number.isInteger(port)&&port>0&&port<=65535?{host,port}:null;
    }catch(_error){return null;}
  }

  function imageKey(value){
    let text=String(value||'').trim().toLowerCase();
    if(!text)return'';
    text=text.split('@',1)[0];
    const slash=text.lastIndexOf('/');
    const colon=text.lastIndexOf(':');
    if(colon>slash)text=text.slice(0,colon);
    return token(text.slice(text.lastIndexOf('/')+1));
  }

  function canonicalKeys(object){
    const keys=new Set();
    for(const value of [object?.label,object?.icon]){
      const key=token(value);
      if(key)keys.add(key);
    }
    const id=String(object?.id||'');
    const idKey=token(id);
    if(idKey)keys.add(idKey);
    for(const hostId of object?.depends_on||[]){
      const prefix=`${hostId}_`;
      if(id.startsWith(prefix)){
        const suffix=token(id.slice(prefix.length));
        if(suffix)keys.add(suffix);
      }
    }
    return keys;
  }

  function workloadKeys(providerObject){
    const workload=providerObject?._provider_workload||{};
    const keys=new Set();
    for(const value of [workload.compose_service,workload.label,providerObject?.label]){
      const key=token(value);
      if(key)keys.add(key);
    }
    for(const image of workload.images||[]){
      const key=imageKey(image);
      if(key)keys.add(key);
    }
    return keys;
  }

  function keysOverlap(left,right){
    for(const item of left)if(right.has(item))return true;
    return false;
  }

  function sharesOwner(canonical,providerObject){
    const providerOwners=new Set(providerObject?.depends_on||[]);
    return(canonical?.depends_on||[]).some(owner=>providerOwners.has(owner));
  }

  function exactEndpointMatch(canonical,providerObject){
    const endpoint=presentationEndpoint(canonical?.presentation_url);
    if(!endpoint)return false;
    const workload=providerObject?._provider_workload||{};
    const rows=[...(workload.service_endpoints||[]),...(workload.backend_monitoring_endpoints||[])];
    for(const item of rows){
      if(!item||typeof item!=='object')continue;
      const host=String(item.host||'').trim().toLowerCase().replace(/^\[|\]$/g,'');
      const port=Number(item.public_port||item.port);
      if(host===endpoint.host&&port===endpoint.port)return true;
    }
    return false;
  }

  function directWorkloadIdentity(canonical,providerObject){
    const wanted=String(providerObject?._provider_workload?.identity||'').trim();
    if(!wanted)return false;
    for(const component of canonical?.components||[]){
      const metadata=component?.metadata&&typeof component.metadata==='object'?component.metadata:{};
      const provider=String(metadata.provider||component?.adapter||'').trim().toLowerCase();
      if(provider!=='portainer')continue;
      const identity=String(metadata.identity||metadata.workload_identity||'').trim();
      if(identity&&identity===wanted)return true;
    }
    return false;
  }

  function reconciliationScore(canonical,providerObject){
    if(!safeHttpUrl(canonical?.presentation_url))return 0;
    const direct=directWorkloadIdentity(canonical,providerObject);
    const endpoint=exactEndpointMatch(canonical,providerObject);
    const owner=sharesOwner(canonical,providerObject);
    const semantic=keysOverlap(canonicalKeys(canonical),workloadKeys(providerObject));
    if(direct)return 500;
    if(endpoint&&owner)return 450;
    if(endpoint&&semantic)return 425;
    if(endpoint)return 400;
    if(owner&&semantic)return 300;
    return 0;
  }

  function reconcilePresentationServices(site,model){
    const services=Array.isArray(model?.services)?[...model.services]:[];
    const providerRows=services.filter(row=>row?.kind==='provider_workload'&&row?._provider_workload);
    if(!providerRows.length)return model;

    // Safe canonical authority may live outside kind=service (for example an
    // integration-owned appliance object). It may participate here only if it
    // already owns an explicit HTTP(S) presentation URL.
    const authorities=(site?.objects||[]).filter(object=>
      object&&object.retired!==true&&!object._provider_workload&&safeHttpUrl(object.presentation_url)
    );
    const proposals=[];
    for(const providerObject of providerRows){
      const ranked=authorities
        .map(canonical=>({canonical,score:reconciliationScore(canonical,providerObject)}))
        .filter(row=>row.score>0)
        .sort((a,b)=>b.score-a.score);
      if(!ranked.length)continue;
      const best=ranked[0].score;
      const winners=ranked.filter(row=>row.score===best);
      if(winners.length!==1)continue;
      proposals.push({providerObject,canonical:winners[0].canonical,score:best});
    }

    // One canonical authority may not be consumed by multiple provider rows.
    const canonicalCounts=new Map();
    for(const proposal of proposals){
      const id=String(proposal.canonical.id||'');
      canonicalCounts.set(id,(canonicalCounts.get(id)||0)+1);
    }
    const replacements=new Map();
    const consumedCanonical=new Set();
    for(const proposal of proposals){
      const canonicalId=String(proposal.canonical.id||'');
      if(!canonicalId||canonicalCounts.get(canonicalId)!==1)continue;
      replacements.set(proposal.providerObject.id,{
        ...proposal.canonical,
        _provider_workload:proposal.providerObject._provider_workload,
      });
      consumedCanonical.add(canonicalId);
    }
    if(!replacements.size)return model;

    return{
      ...model,
      services:services.flatMap(service=>{
        const replacement=replacements.get(service?.id);
        if(replacement)return[replacement];
        if(consumedCanonical.has(String(service?.id||'')))return[];
        return[service];
      }),
    };
  }

  function environmentRows(metadata){
    const rows=[];
    const seen=new Set();
    for(const environment of metadata?.environments||[]){
      if(!environment||typeof environment!=='object')continue;
      const id=Number(environment.provider_id);
      if(!Number.isInteger(id)||id<=0||seen.has(id))continue;
      seen.add(id);
      rows.push({
        id,
        name:String(environment.name||`Environment ${id}`).trim()||`Environment ${id}`,
        key:String(environment.key||'').trim(),
        status:environment.status,
      });
    }
    return rows.sort((a,b)=>a.name.localeCompare(b.name)||a.id-b.id);
  }

  function selectedEnvironmentIds(config,rows){
    const raw=Array.isArray(config?.environment_ids)
      ?config.environment_ids.filter(value=>Number.isInteger(value)&&value>0)
      :[];
    if(!raw.length)return rows.map(row=>row.id);
    const selected=new Set(raw);
    return rows.filter(row=>selected.has(row.id)).map(row=>row.id);
  }

  function applyEnvironmentSelection(config,selectedIds,allIds){
    if(!config||typeof config!=='object')throw new Error('Portainer provider config is unavailable.');
    const all=[...new Set((allIds||[]).filter(value=>Number.isInteger(value)&&value>0))].sort((a,b)=>a-b);
    const selected=[...new Set((selectedIds||[]).filter(value=>Number.isInteger(value)&&value>0))].sort((a,b)=>a-b);
    if(!selected.length)throw new Error('At least one Portainer environment must remain selected.');
    if(all.length&&selected.length===all.length&&selected.every((value,index)=>value===all[index])){
      delete config.environment_ids;
    }else{
      config.environment_ids=selected;
    }
    return config;
  }

  globalThis.MonitorBoxUiPhase2Physical=Object.freeze({
    applyEnvironmentSelection,
    canonicalKeys,
    environmentRows,
    presentationEndpoint,
    reconcilePresentationServices,
    reconciliationScore,
    safeHttpUrl,
    selectedEnvironmentIds,
    workloadKeys,
  });

  if(typeof providerPresentationModel==='function'){
    const baseProviderPresentationModel=providerPresentationModel;
    providerPresentationModel=function(site){
      return reconcilePresentationServices(site,baseProviderPresentationModel(site));
    };
  }

  if(typeof renderProvider==='function'&&typeof document!=='undefined'){
    const baseRenderProvider=renderProvider;
    const inventoryCache=new Map();

    function repairAdapterSelect(box,provider){
      const adapter=String(provider?.adapter||'').trim();
      if(!adapter)return;
      const labels=[...box.querySelectorAll('label.field')];
      const wrap=labels.find(label=>String(label.firstChild?.textContent||'').trim()==='Adapter');
      const select=wrap?.querySelector('select');
      if(!select)return;
      if(![...select.options].some(option=>option.value===adapter)){
        const option=document.createElement('option');
        option.value=adapter;
        option.textContent=`${adapter} (managed module)`;
        select.append(option);
      }
      select.value=adapter;
    }

    function syncProviderJson(box,provider){
      const details=[...box.querySelectorAll('details')].find(node=>
        String(node.querySelector('summary')?.textContent||'').trim()==='Advanced provider configuration'
      );
      const area=details?.querySelector('textarea');
      if(area)area.value=JSON.stringify(provider.config||{},null,2);
    }

    async function loadPortainerEnvironments(provider){
      const config=provider?.config&&typeof provider.config==='object'?provider.config:{};
      const cacheKey=JSON.stringify([
        config.base_url||'',config.api_key_env||'',config.verify_tls!==false,
      ]);
      const cached=inventoryCache.get(cacheKey);
      if(cached)return cached;
      const promise=(async()=>{
        const probe=typeof deep==='function'?deep(provider):JSON.parse(JSON.stringify(provider));
        probe.config=probe.config&&typeof probe.config==='object'?probe.config:{};
        delete probe.config.environment_ids;
        probe.config.operation='inventory';
        probe.object_id=typeof objectId!=='undefined'?objectId:probe.object_id;
        const refs=(typeof working!=='undefined'&&working?.runtime?.local_agent?.credential_secret_refs)||{};
        const response=await api('/api/v2/config/providers/test',{
          method:'POST',
          body:JSON.stringify({provider:probe,credential_secret_refs:refs}),
        });
        if(response?.status!=='complete'||!response?.observation){
          throw new Error(response?.error||'Portainer environment inventory probe failed.');
        }
        const rows=environmentRows(response.observation.metadata||{});
        if(!rows.length)throw new Error('Portainer returned no selectable Docker environments.');
        return rows;
      })();
      inventoryCache.set(cacheKey,promise);
      try{return await promise;}
      catch(error){inventoryCache.delete(cacheKey);throw error;}
    }

    async function appendPortainerScope(box,provider){
      if(String(provider?.adapter||'').trim().toLowerCase()!=='portainer')return;
      const details=document.createElement('details');
      details.open=true;
      details.style.marginTop='12px';
      details.dataset.phase2PortainerScope='1';
      const summary=document.createElement('summary');
      summary.textContent='Portainer environment scope';
      const status=document.createElement('div');
      status.className='status';
      status.style.marginTop='8px';
      status.textContent='Loading authenticated environments…';
      details.append(summary,status);
      box.append(details);
      try{
        const rows=await loadPortainerEnvironments(provider);
        if(!box.isConnected)return;
        status.remove();
        const note=document.createElement('p');
        note.className='muted';
        note.textContent='Select the Portainer environments that belong to this MonitorBox site. Unselected environments remain in authenticated provider provenance but their descendant workloads are not actionable discoveries.';
        details.append(note);
        const selected=new Set(selectedEnvironmentIds(provider.config||{},rows));
        const allIds=rows.map(row=>row.id);
        const controls=[];
        for(const row of rows){
          const label=document.createElement('label');
          label.className='check';
          label.style.margin='7px 0';
          const input=document.createElement('input');
          input.type='checkbox';
          input.checked=selected.has(row.id);
          input.dataset.portainerEnvironmentId=String(row.id);
          const text=document.createElement('span');
          text.textContent=`${row.name} · environment ${row.id}`;
          label.append(input,text);
          details.append(label);
          controls.push(input);
          input.addEventListener('change',()=>{
            const chosen=controls.filter(control=>control.checked).map(control=>Number(control.dataset.portainerEnvironmentId));
            try{
              applyEnvironmentSelection(provider.config||(provider.config={}),chosen,allIds);
              syncProviderJson(box,provider);
            }catch(error){
              input.checked=true;
              if(typeof toast==='function')toast(error.message);
            }
          });
        }
        const hint=document.createElement('div');
        hint.className='secret-state';
        hint.textContent='All selected = all authenticated environments. A partial selection is stored as explicit environment_ids and survives refresh/restart.';
        details.append(hint);
      }catch(error){
        status.className='status bad';
        status.textContent=`Environment scope unavailable: ${error.message}`;
      }
    }

    renderProvider=function(obj,cap,provider){
      const box=baseRenderProvider(obj,cap,provider);
      repairAdapterSelect(box,provider);
      if(String(provider?.adapter||'').trim().toLowerCase()==='portainer'){
        void appendPortainerScope(box,provider);
      }
      return box;
    };
  }
})();
