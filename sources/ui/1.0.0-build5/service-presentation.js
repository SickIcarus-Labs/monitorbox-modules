'use strict';

// Restore the established v1 service hierarchy without creating a second
// health model. Canonical service objects remain in /api/v2/state and retain
// their individual drawers; this layer only composes how they are presented.
const servicePresentationBaseRenderSite=renderSite;
const servicePresentationBaseFindObject=findObject;
const servicePresentationBaseRenderDrawer=renderDrawer;
const SERVICE_GROUP_ID='__services__';
const nativeServiceIcons=new Set([
  'plex','homeassistant','homebridge','sonarr','radarr','qbittorrent','portainer',
  'pihole','cockpit','seerr','tautulli','lidarr','prowlarr','bazarr','sabnzbd',
  'ombi','scrob',
]);
let servicePresentationParent=null;

function servicesForSite(site){
  return(site?.objects||[]).filter(object=>object.kind==='service'&&object.retired!==true);
}

function orderedServices(services){
  return[...services].sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
}

function serviceGroupState(services){
  const ordered=orderedServices(services);
  return ordered.length?ordered[0].state:'unknown';
}

function serviceGroupSummary(services){
  if(!services.length)return'No services configured';
  const healthy=services.filter(service=>service.state==='healthy').length;
  const planned=services.filter(service=>service.state==='planned').length;
  const worst=orderedServices(services)[0];
  if(stateRank(worst.state)>0)return`${healthy} healthy · ${services.length-healthy} need attention · ${worst.label}: ${worst.summary}`;
  if(planned)return`${healthy} healthy · ${planned} planned`;
  return`${healthy} of ${services.length} reporting normally`;
}

function serviceHostGroups(site,services){
  const hosts=(site.objects||[]).filter(object=>object.kind==='host');
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
}

function serviceComposeProvenance(service){
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
    return{
      project,
      composeService:composeService||String(service.label||'').trim(),
      environmentKey,
      environmentLabel:environmentLabel||environmentKey,
      key:`${environmentKey}\u0000${project}`,
    };
  }
  return null;
}

function servicePresentationEntries(services){
  const grouped=new Map(),plain=[];
  for(const service of services){
    const provenance=serviceComposeProvenance(service);
    if(!provenance){plain.push(service);continue;}
    let group=grouped.get(provenance.key);
    if(!group){
      group={
        key:provenance.key,
        project:provenance.project,
        environmentKey:provenance.environmentKey,
        environmentLabel:provenance.environmentLabel,
        services:[],
      };
      grouped.set(provenance.key,group);
    }
    group.services.push(service);
  }
  const stackGroups=[],singletons=[...plain];
  for(const group of grouped.values()){
    if(group.services.length<2){singletons.push(...group.services);continue;}
    group.state=serviceGroupState(group.services);
    stackGroups.push(group);
  }
  const projectCounts=new Map();
  for(const group of stackGroups)projectCounts.set(group.project,(projectCounts.get(group.project)||0)+1);
  const entries=stackGroups.map(group=>({
    kind:'stack',
    state:group.state,
    label:projectCounts.get(group.project)>1?`${group.project} · ${group.environmentLabel}`:group.project,
    group,
  }));
  entries.push(...singletons.map(service=>({kind:'service',state:service.state,label:service.label,service})));
  return entries.sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
}

function serviceGroupObject(site){
  const services=servicesForSite(site);
  const state=serviceGroupState(services);
  return{
    id:SERVICE_GROUP_ID,
    label:'Services',
    kind:'service_group',
    state,
    underlying_state:state,
    summary:serviceGroupSummary(services),
    services,
    components:[],
    front_page:true,
    health_participant:false,
  };
}

findObject=function(siteId,objectId){
  if(objectId!==SERVICE_GROUP_ID)return servicePresentationBaseFindObject(siteId,objectId);
  const site=app.state?.sites?.find(item=>item.id===siteId);
  return{site,object:site?serviceGroupObject(site):undefined};
};

function serviceDirectoryNames(services){
  return servicePresentationEntries(services).map(entry=>entry.kind==='stack'?`${entry.label} (${entry.group.services.length})`:entry.service.label).join(' · ');
}

function serviceDirectory(site,services){
  return serviceHostGroups(site,services).map(group=>`<span class="service-directory-group"><b>${esc(group.label)}</b><small>${esc(serviceDirectoryNames(group.services))}</small></span>`).join('');
}

function renderServiceSummaryCard(site){
  const services=servicesForSite(site);
  if(!services.length)return'';
  const state=serviceGroupState(services),summary=serviceGroupSummary(services);
  return`<button class="card services-summary-card ${esc(state)}" data-site="${esc(site.id)}" data-object="${SERVICE_GROUP_ID}" type="button"><span class="card-top"><span><h3>Services</h3><span class="card-type">Service directory</span></span>${pill(state)}</span><span class="card-summary">${esc(summary)}</span>${stateRank(state)===0?`<span class="service-directory">${serviceDirectory(site,services)}</span>`:''}</button>`;
}

renderSite=function(site){
  const original=site.objects||[];
  const services=servicesForSite(site);
  site.objects=original.filter(object=>object.kind!=='service');
  let html;
  try{html=servicePresentationBaseRenderSite(site);}
  finally{site.objects=original;}
  if(!services.length)return html;
  const marker='</div></section>';
  const index=html.lastIndexOf(marker);
  if(index<0)return html;
  return`${html.slice(0,index)}${renderServiceSummaryCard(site)}${html.slice(index)}`;
};

function serviceIcon(service){
  const icon=nativeServiceIcons.has(service.icon)?service.icon:null;
  const letters=String(service.label||'').split(/\s+/).filter(Boolean).map(word=>word[0]).join('').slice(0,2).toUpperCase()||'S';
  const body=icon?`<img src="/static/icons/${esc(icon)}.svg" alt="">`:`<span>${esc(letters)}</span>`;
  if(service.presentation_url)return`<a class="service-icon icon-outbound" href="${esc(service.presentation_url)}" target="_blank" rel="noopener" aria-label="Open ${esc(service.label)}">${body}<i>↗</i></a>`;
  return`<span class="service-icon" aria-hidden="true">${body}</span>`;
}

function serviceRow(site,service,parent){
  const component=(service.components||[]).find(item=>item.enabled&&item.state!=='healthy')||(service.components||[]).find(item=>item.enabled);
  const detail=component?.summary||service.summary||'Status unavailable';
  return`<div class="service-navigation-row">${serviceIcon(service)}<button class="component-row service-navigation-button" data-service-object="${esc(service.id)}" data-service-parent="${esc(parent)}" type="button"><span><strong>${esc(service.label)}</strong><small>${esc(detail)}</small></span>${pill(service.state)}</button></div>`;
}

function serviceRows(site,services,parent){
  return orderedServices(services).map(service=>serviceRow(site,service,parent)).join('');
}

function serviceStackRow(site,entry,parent){
  const group=entry.group;
  const count=group.services.length;
  const attention=stateRank(entry.state)>0;
  const serviceNames=orderedServices(group.services).map(service=>service.label).join(' · ');
  return`<details class="service-compose-group ${esc(entry.state)}" data-compose-stack="${esc(group.key)}"${attention?' open':''}><summary class="service-compose-summary"><span class="service-compose-copy"><strong>${esc(entry.label)}</strong><small>${count} services · ${esc(group.environmentLabel)} · ${esc(serviceNames)}</small></span>${pill(entry.state)}</summary><div class="service-compose-members service-list">${serviceRows(site,group.services,parent)}</div></details>`;
}

function servicePresentationRows(site,services,parent){
  return servicePresentationEntries(services).map(entry=>entry.kind==='stack'?serviceStackRow(site,entry,parent):serviceRow(site,entry.service,parent)).join('');
}

function bindServiceNavigation(site){
  document.querySelectorAll('[data-service-object]').forEach(node=>node.addEventListener('click',()=>{
    const parentId=node.dataset.serviceParent||SERVICE_GROUP_ID;
    const parent=parentId===SERVICE_GROUP_ID?serviceGroupObject(site):(site.objects||[]).find(item=>item.id===parentId);
    servicePresentationParent=parent?{siteId:site.id,objectId:parent.id,label:parent.label}:null;
    openDrawer(site.id,node.dataset.serviceObject);
  }));
  document.querySelector('[data-service-back]')?.addEventListener('click',()=>{
    const parent=servicePresentationParent;
    servicePresentationParent=null;
    if(parent)openDrawer(parent.siteId,parent.objectId);
  });
}

function renderServiceGroupDrawer(site,object){
  $('#drawer-eyebrow').textContent=`${site.label} · service directory`;
  $('#drawer-title').textContent='Services';
  $('#drawer-state').className=`state-pill ${object.state}`;
  $('#drawer-state').textContent=stateLabel(object.state);
  const groups=serviceHostGroups(site,object.services);
  $('#drawer-body').innerHTML=`<section class="detail-section"><div class="detail-state"><div><h3>Current state</h3><strong>${esc(stateLabel(object.state))}</strong><p>${esc(object.summary)}</p></div>${pill(object.state)}</div></section>${groups.map(group=>`<section class="detail-section"><h3>${esc(group.label)}</h3><div class="service-list">${servicePresentationRows(site,group.services,SERVICE_GROUP_ID)}</div></section>`).join('')}`;
  bindServiceNavigation(site);
}

function appendHostedServices(site,host){
  const hosted=servicesForSite(site).filter(service=>(service.depends_on||[]).includes(host.id));
  if(!hosted.length)return;
  $('#drawer-body').insertAdjacentHTML('beforeend',`<section class="detail-section"><h3>Services</h3><div class="service-list">${servicePresentationRows(site,hosted,host.id)}</div></section>`);
  bindServiceNavigation(site);
}

function prependServiceBack(site,service){
  const parent=servicePresentationParent;
  if(!parent||parent.siteId!==site.id)return;
  $('#drawer-body').insertAdjacentHTML('afterbegin',`<div class="service-back-row"><button class="button secondary" data-service-back type="button">← ${esc(parent.label)}</button><span>${esc(service.label)}</span></div>`);
  bindServiceNavigation(site);
}

renderDrawer=function(){
  if(!app.selected||!app.state)return servicePresentationBaseRenderDrawer();
  const {site,object}=findObject(app.selected.siteId,app.selected.objectId);
  if(!site||!object)return servicePresentationBaseRenderDrawer();
  if(object.kind==='service_group')return renderServiceGroupDrawer(site,object);
  servicePresentationBaseRenderDrawer();
  if(object.kind==='host')appendHostedServices(site,object);
  if(object.kind==='service')prependServiceBack(site,object);
};