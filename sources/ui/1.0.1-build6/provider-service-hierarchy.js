// UI 1.0.1 build 6: compose the Service Directory from canonical services plus
// provider-native Portainer workload truth. This is presentation-only: provider
// workload rows are never persisted as canonical health objects.
const PROVIDER_WORKLOAD_PREFIX='__provider_workload__:';
const providerHierarchyBaseFindObject=findObject;
const providerHierarchyBaseRenderDrawer=renderDrawer;

function providerNormalizeToken(value){
  return String(value||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,'');
}

function providerExactAddress(value){
  const text=String(value||'').trim().toLowerCase();
  if(!text||text.includes('/')||text==='localhost')return'';
  return text.replace(/^\[|\]$/g,'');
}

function providerUrlHost(value){
  const text=String(value||'').trim();
  if(!text||text.toLowerCase().startsWith('unix://'))return'';
  try{return String(new URL(text).hostname||'').trim().toLowerCase();}
  catch(_error){
    const match=text.match(/^[a-z][a-z0-9+.-]*:\/\/\[?([^\]/:]+)\]?/i);
    return match?String(match[1]).trim().toLowerCase():'';
  }
}

function portainerInventoryWorkloads(site){
  const byIdentity=new Map();
  for(const object of site?.objects||[]){
    for(const component of object?.components||[]){
      const metadata=component?.metadata||{};
      if(String(metadata.provider||'').trim().toLowerCase()!=='portainer')continue;
      if(metadata.authoritative!==true||!Array.isArray(metadata.workloads))continue;
      for(const workload of metadata.workloads){
        if(!workload||typeof workload!=='object')continue;
        const identity=String(workload.identity||'').trim();
        if(identity)byIdentity.set(identity,workload);
      }
    }
  }
  return[...byIdentity.values()];
}

function providerWorkloadEnvironmentHosts(workload){
  const hosts=new Set();
  const direct=providerUrlHost(workload?.environment_url);
  if(direct)hosts.add(direct);
  for(const endpoint of workload?.service_endpoints||[]){
    const host=providerExactAddress(endpoint?.host)||String(endpoint?.host||'').trim().toLowerCase();
    if(host)hosts.add(host);
  }
  return hosts;
}

function providerEnvironmentOwners(site,workloads){
  const localHosts=(site?.objects||[]).filter(object=>
    ['host','appliance'].includes(String(object?.kind||''))&&providerExactAddress(object?.address)
  );
  const owners=new Map();
  // A local unix:// Portainer environment has no network hostname. Its authenticated
  // controller-self row is nevertheless strong provider-native proof that the
  // inventory component's canonical Portainer service and its host own that
  // environment. This is identity/provenance, not label inference.
  for(const object of site?.objects||[]){
    const ownerHost=localHosts.find(host=>(object?.depends_on||[]).includes(host.id));
    if(!ownerHost)continue;
    for(const component of object?.components||[]){
      const metadata=component?.metadata||{};
      if(String(metadata.provider||'').trim().toLowerCase()!=='portainer'||metadata.authoritative!==true)continue;
      for(const workload of metadata.workloads||[]){
        if(workload?.discovery_suppression_reason!=='authenticated_portainer_controller')continue;
        const environmentKey=String(workload.environment_key||'').trim();
        if(environmentKey)owners.set(environmentKey,ownerHost);
      }
    }
  }
  const candidates=new Map();
  for(const workload of workloads){
    const environmentKey=String(workload?.environment_key||'').trim();
    if(!environmentKey)continue;
    let set=candidates.get(environmentKey);
    if(!set){set=new Set();candidates.set(environmentKey,set);}
    for(const host of providerWorkloadEnvironmentHosts(workload))set.add(host);
  }
  for(const [environmentKey,addresses] of candidates){
    if(owners.has(environmentKey))continue;
    const matches=localHosts.filter(host=>addresses.has(providerExactAddress(host.address)));
    if(matches.length===1)owners.set(environmentKey,matches[0]);
  }
  return owners;
}

function providerWorkloadRuntime(workload){
  let starting=false;
  const containers=Array.isArray(workload?.containers)?workload.containers:[];
  for(const container of containers){
    const state=String(container?.state||'unknown').trim().toLowerCase();
    const health=String(container?.health||'').trim().toLowerCase();
    const lifecycle=container?.lifecycle&&typeof container.lifecycle==='object'?container.lifecycle:{};
    if(
      lifecycle.confirmed_anomaly===true||health==='unhealthy'||
      state==='restarting'||state==='dead'
    ){
      const kind=lifecycle.crash_loop===true?'crash loop':
        lifecycle.oom_killed===true?'OOM kill':
        lifecycle.nonzero_exit===true?'non-zero exit':
        health==='unhealthy'?'unhealthy container':state;
      return{state:'failed',neutral:false,summary:`Docker runtime problem: ${kind}`};
    }
    if(health==='starting'||state==='created'||state==='starting')starting=true;
  }
  if(starting)return{state:'degraded',neutral:false,summary:'Docker workload is starting'};
  if(containers.length&&containers.every(container=>String(container?.state||'').trim().toLowerCase()==='running')){
    return{state:'healthy',neutral:false,summary:'Docker workload running'};
  }
  return{
    state:'unknown',
    neutral:true,
    summary:'Docker workload is not running; expected-state intent is not configured',
  };
}

function providerWorkloadObject(workload,host){
  const runtime=providerWorkloadRuntime(workload);
  const identity=String(workload.identity||'');
  const label=String(workload.compose_service||workload.label||identity||'Docker workload');
  const containers=(workload.containers||[]).filter(container=>container&&typeof container==='object');
  return{
    id:`${PROVIDER_WORKLOAD_PREFIX}${identity}`,
    label,
    kind:'provider_workload',
    state:runtime.state,
    underlying_state:runtime.state,
    summary:runtime.summary,
    retired:false,
    address:host?.address||'',
    presentation_url:null,
    icon:null,
    depends_on:host?[host.id]:[],
    components:containers.map((container,index)=>({
      id:`provider-container-${index}`,
      label:String(container.name||container.provider_id||`Container ${index+1}`),
      adapter:'portainer',
      enabled:true,
      state:providerWorkloadRuntime({containers:[container]}).state,
      summary:`${String(container.state||'unknown')}${container.health?` · ${container.health}`:''}`,
      metadata:{provider:'portainer',container,workload_identity:identity},
    })),
    health_participant:false,
    front_page:false,
    actions:[],
    _provider_workload:workload,
    _provider_health_neutral:runtime.neutral,
  };
}

function canonicalProviderKey(service,host){
  const hostId=String(host?.id||'');
  const id=String(service?.id||'');
  if(hostId&&id.startsWith(`${hostId}_`)){
    const suffix=providerNormalizeToken(id.slice(hostId.length+1));
    if(suffix)return suffix;
  }
  const label=providerNormalizeToken(service?.label);
  return label||providerNormalizeToken(id);
}

function providerWorkloadKey(workload){
  return providerNormalizeToken(workload?.compose_service||workload?.label||'');
}

function providerDirectIdentity(service){
  for(const component of service?.components||[]){
    const metadata=component?.metadata||{};
    if(String(metadata.provider||component?.adapter||'').trim().toLowerCase()!=='portainer')continue;
    const identity=String(metadata.identity||metadata.workload_identity||'').trim();
    if(identity)return identity;
  }
  return'';
}

function providerPresentationModel(site){
  const canonical=(site?.objects||[]).filter(object=>object.kind==='service'&&object.retired!==true);
  const inventory=portainerInventoryWorkloads(site);
  const owners=providerEnvironmentOwners(site,inventory);
  const local=inventory.filter(workload=>{
    const environmentKey=String(workload?.environment_key||'').trim();
    return owners.has(environmentKey)&&workload?.ignored!==true&&workload?.discovery_actionable!==false;
  });
  const byIdentity=new Map(local.map(workload=>[String(workload.identity||''),workload]));
  const byEnvironment=new Map();
  for(const workload of local){
    const key=String(workload.environment_key||'');
    const list=byEnvironment.get(key)||[];
    list.push(workload);byEnvironment.set(key,list);
  }
  const matched=new Set();
  const services=[];
  for(const service of canonical){
    let workload=null;
    const direct=providerDirectIdentity(service);
    if(direct&&byIdentity.has(direct))workload=byIdentity.get(direct);
    if(!workload){
      const host=(site?.objects||[]).find(object=>(service.depends_on||[]).includes(object.id)&&['host','appliance'].includes(object.kind));
      if(host){
        const environmentKeys=[...owners.entries()].filter(([,owner])=>owner.id===host.id).map(([key])=>key);
        const desired=canonicalProviderKey(service,host);
        const candidates=environmentKeys.flatMap(key=>byEnvironment.get(key)||[]).filter(row=>providerWorkloadKey(row)===desired);
        if(candidates.length===1)workload=candidates[0];
      }
    }
    if(workload){
      matched.add(String(workload.identity||''));
      services.push({...service,_provider_workload:workload});
    }else services.push(service);
  }
  for(const workload of local){
    const identity=String(workload.identity||'');
    if(matched.has(identity))continue;
    const host=owners.get(String(workload.environment_key||''));
    services.push(providerWorkloadObject(workload,host));
  }
  return{services,inventory,owners};
}

servicesForSite=function(site){
  return providerPresentationModel(site).services;
};

serviceHostGroups=function(site,services){
  const hosts=(site.objects||[]).filter(object=>['host','appliance'].includes(object.kind));
  const assigned=new Set();
  const groups=[];
  for(const host of hosts){
    const children=services.filter(service=>(service.depends_on||[]).includes(host.id));
    if(!children.length)continue;
    children.forEach(service=>assigned.add(service.id));
    groups.push({label:host.label,services:children});
  }
  const other=services.filter(service=>!assigned.has(service.id));
  if(other.length)groups.push({label:'Other',services:other});
  return groups;
};

serviceComposeProvenance=function(service){
  const workload=service?._provider_workload;
  if(workload&&typeof workload==='object'){
    const project=String(workload.compose_project||'').trim();
    const environmentKey=String(workload.environment_key||'').trim();
    if(project&&environmentKey){
      return{
        project,
        composeService:String(workload.compose_service||service.label||'').trim(),
        environmentKey,
        environmentLabel:String(workload.environment_name||environmentKey).trim(),
        key:`${environmentKey}\u0000${project}`,
      };
    }
  }
  for(const component of service?.components||[]){
    const metadata=component?.metadata||{};
    const provider=String(metadata.provider||component?.adapter||'').trim().toLowerCase();
    const project=String(metadata.compose_project||metadata.stack_name||'').trim();
    const composeService=String(metadata.compose_service||'').trim();
    const environmentKey=String(metadata.environment_key||metadata.environment_provider_id||'').trim();
    const environmentLabel=String(metadata.environment_name||metadata.environment||environmentKey).trim();
    const deployment=String(metadata.deployment_kind||'').trim().toLowerCase();
    if(provider!=='portainer'||!project||!environmentKey)continue;
    if(deployment&&deployment!=='compose')continue;
    return{project,composeService:composeService||String(service.label||'').trim(),environmentKey,environmentLabel:environmentLabel||environmentKey,key:`${environmentKey}\u0000${project}`};
  }
  return null;
};

function providerAggregateServices(services){
  const participating=services.filter(service=>service?._provider_health_neutral!==true);
  return participating.length?participating:services;
}

serviceGroupState=function(services){
  const relevant=providerAggregateServices(services);
  const ordered=orderedServices(relevant);
  return ordered.length?ordered[0].state:'unknown';
};

serviceGroupSummary=function(services){
  if(!services.length)return'No services configured';
  const relevant=providerAggregateServices(services);
  const state=serviceGroupState(services);
  const healthy=services.filter(service=>service.state==='healthy').length;
  const neutral=services.filter(service=>service._provider_health_neutral===true).length;
  if(stateRank(state)>0){
    const worst=orderedServices(relevant)[0];
    return`${healthy} healthy · ${services.length-healthy-neutral} need attention${neutral?` · ${neutral} intent-neutral`:''} · ${worst.label}: ${worst.summary}`;
  }
  return`${healthy} healthy${neutral?` · ${neutral} intent-neutral`:''} · ${services.length} visible service/workload(s)`;
};

serviceGroupObject=function(site){
  const services=servicesForSite(site);
  const state=serviceGroupState(services);
  return{
    id:SERVICE_GROUP_ID,label:'Services',kind:'service_group',state,underlying_state:state,
    summary:serviceGroupSummary(services),services,components:[],front_page:true,health_participant:false,
  };
};

function providerWorkloadFromObjectId(site,objectId){
  if(!String(objectId||'').startsWith(PROVIDER_WORKLOAD_PREFIX))return null;
  const identity=String(objectId).slice(PROVIDER_WORKLOAD_PREFIX.length);
  const model=providerPresentationModel(site);
  return model.services.find(service=>service.kind==='provider_workload'&&String(service._provider_workload?.identity||'')===identity)||null;
}

findObject=function(siteId,objectId){
  const site=app.state?.sites?.find(item=>item.id===siteId);
  const providerObject=site?providerWorkloadFromObjectId(site,objectId):null;
  if(providerObject)return{site,object:providerObject};
  return providerHierarchyBaseFindObject(siteId,objectId);
};

function renderProviderWorkloadDrawer(site,object){
  const workload=object._provider_workload||{};
  $('#drawer-eyebrow').textContent=`${site.label} · Docker workload`;
  $('#drawer-title').textContent=object.label;
  $('#drawer-state').className=`state-pill ${object.state}`;
  $('#drawer-state').textContent=stateLabel(object.state);
  const identity=String(workload.identity||'');
  const provenance=[workload.environment_name,workload.compose_project&&`Stack ${workload.compose_project}`,workload.compose_service&&`Service ${workload.compose_service}`].filter(Boolean).join(' · ');
  const containers=(workload.containers||[]).map(container=>{
    const runtime=providerWorkloadRuntime({containers:[container]});
    const name=String(container?.name||container?.provider_id||'Container');
    const detail=[container?.state,container?.health,container?.lifecycle?.restart_count!=null?`restarts ${container.lifecycle.restart_count}`:''].filter(Boolean).join(' · ');
    return`<div class="component-row"><span><strong>${esc(name)}</strong><small>${esc(detail||'Runtime state unavailable')}</small></span>${pill(runtime.state)}</div>`;
  }).join('');
  $('#drawer-body').innerHTML=`<section class="detail-section"><div class="detail-state"><div><h3>Current state</h3><strong>${esc(stateLabel(object.state))}</strong><p>${esc(object.summary)}</p></div>${pill(object.state)}</div></section><section class="detail-section"><h3>Portainer provenance</h3><p>${esc(provenance||'Portainer workload')}</p><small>${esc(identity)}</small></section><section class="detail-section"><h3>Containers</h3>${containers||'<p>No container rows available.</p>'}</section>`;
};

renderDrawer=function(){
  if(app.selected&&app.state){
    const {site,object}=findObject(app.selected.siteId,app.selected.objectId);
    if(site&&object?.kind==='provider_workload')return renderProviderWorkloadDrawer(site,object);
  }
  return providerHierarchyBaseRenderDrawer();
};
