'use strict';

// Presentation compatibility layer for the production v1 dashboard contract.
// The v2 controller remains the sole health model; this file only maps its
// canonical site/object state into the proven v1 information hierarchy.
const MONITORBOX_BUILD_ID='v2.0b22';

function parityState(state){return stateLabel(state);}
function parityStateChip(state){return`<span class="parity-state ${esc(state)}"><i></i>${esc(parityState(state))}</span>`;}
function parityObjects(site){return site?.objects||[];}
function parityMetric(object,key){
  for(const component of object?.components||[]){
    const value=component.metrics?.[key];
    if(Number.isFinite(value))return Number(value);
  }
  return null;
}
function parityCoreObjects(site){
  const excluded=new Set(['service','camera','ups','network_device','remote_site','appliance','service_group']);
  // Preserve manifest order. Conceptual Cameras is a composed top-level object;
  // it must remain visible even when its raw Scrypted inventory is hidden.
  return parityObjects(site).filter(object=>(object.front_page!==false||object.id==='cameras')&&object.id!=='monitor'&&!excluded.has(object.kind));
}
function parityNetworkChildren(site){
  // Canonical network-device objects are deliberately front_page=false when a
  // conceptual Network object exists. They are still the children that must be
  // composed into the v1 Network summary and drill-down.
  return parityObjects(site)
    .filter(object=>object.kind==='network_device'||object.kind==='remote_site')
    .sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
}
function parityCameras(site){
  return parityObjects(site).filter(object=>object.kind==='camera')
    .sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
}
function parityUps(site){
  return parityObjects(site).filter(object=>object.kind==='ups')
    .sort((a,b)=>String(a.label).localeCompare(String(b.label)));
}
function paritySummary(object){return object?.summary||worstSummary(object||{components:[]});}

function parityPowerRows(site){
  return parityUps(site).map(ups=>{
    const charge=parityMetric(ups,'battery.charge');
    const runtime=parityMetric(ups,'battery.runtime');
    const source=(ups.components||[]).map(c=>c.metadata?.power_source).find(Boolean)||'unknown';
    const sourceLabel=source==='utility'?'Utility':source==='battery'?'On battery':'Unknown';
    const telemetry=`${Number.isFinite(charge)?`${Math.round(charge)}%`:'—'} · ${Number.isFinite(runtime)?`${Math.round(runtime/60)}m`:'—'}`;
    return`<span class="parity-power-row"><b>${esc(ups.label)}</b><small>${esc(sourceLabel)}</small><strong>${esc(telemetry)}</strong></span>`;
  }).join('');
}

function parityCoreCard(site,object){
  let body=`<span class="parity-card-copy">${esc(paritySummary(object))}</span>`;
  if(object.id==='network'){
    const children=parityNetworkChildren(site);
    if(children.length)body=`<span class="parity-mini-directory">${children.map(child=>`<small><b>${esc(child.label)}</b>${parityStateChip(child.state)}</small>`).join('')}</span>`;
  }else if(object.id==='cameras'){
    const cameras=parityCameras(site),counts=object.camera_counts||{},healthy=Number.isFinite(counts.healthy)?counts.healthy:cameras.filter(camera=>camera.state==='healthy').length,expected=Number.isFinite(counts.expected)?counts.expected:cameras.length;
    body=`<span class="parity-card-copy parity-composition-value"><b>${healthy} / ${expected}</b><small>cameras healthy</small></span><span class="parity-camera-directory">${cameras.map(camera=>`<small>${parityStateChip(camera.state)}${esc(camera.label)}</small>`).join('')}</span>`;
  }else if(object.id==='power'){
    const rows=parityPowerRows(site);
    body=rows?`<span class="parity-power-list">${rows}</span>`:`<span class="parity-card-copy">${esc(paritySummary(object))}</span>`;
  }
  return`<button class="parity-card ${esc(object.state)}" data-site="${esc(site.id)}" data-object="${esc(object.id)}" type="button"><span class="parity-card-head"><strong>${esc(object.label)}</strong>${parityStateChip(object.state)}</span>${body}</button>`;
}

function parityCoreMarkup(){
  const sites=app.state?.sites||[],multi=sites.length>1;
  return sites.map(site=>`${multi?`<div class="parity-site-label">${esc(site.label)}</div>`:''}${parityCoreObjects(site).map(object=>parityCoreCard(site,object)).join('')}`).join('');
}
function parityServiceMarkup(){
  const sites=app.state?.sites||[],multi=sites.length>1;
  return sites.map(site=>{
    const services=servicesForSite(site);
    if(!services.length)return'';
    return`${multi?`<div class="parity-site-label">${esc(site.label)}</div>`:''}${renderServiceSummaryCard(site)}`;
  }).join('');
}
function parityServiceCount(){return(app.state?.sites||[]).flatMap(site=>servicesForSite(site)).length;}
function parityHealthyServiceCount(){return(app.state?.sites||[]).flatMap(site=>servicesForSite(site)).filter(service=>service.state==='healthy').length;}

function openParityCondition(condition){
  if(condition.site_id){
    const found=findObject(condition.site_id,String(condition.id||''));
    if(found.site&&found.object){
      openDrawer(condition.site_id,String(condition.id));
      return;
    }
  }
  // Controller-wide conditions (for example an unmapped DB Canary problem)
  // have no canonical site object. They still need a useful diagnostic target.
  $('#drawer-eyebrow').textContent='MonitorBox · condition';
  $('#drawer-title').textContent=condition.label||condition.id||'Condition';
  $('#drawer-state').className=`state-pill ${esc(condition.state||'unknown')}`;
  $('#drawer-state').textContent=stateLabel(condition.state||'unknown');
  $('#drawer-body').innerHTML=`<section class="detail-section"><h3>Current condition</h3><div class="detail-state"><div><strong>${esc(stateLabel(condition.state||'unknown'))}</strong><p>${esc(condition.summary||'Status unavailable')}</p></div>${pill(condition.state||'unknown')}</div></section>`;
}

function bindParityGlobalConditions(conditions){
  document.querySelectorAll('[data-global-condition]').forEach(node=>node.addEventListener('click',()=>{
    const index=Number(node.dataset.globalCondition);
    const condition=conditions[index];
    if(condition)openParityCondition(condition);
  }));
}

function openParityGlobal(){
  stopCameraLive(false);
  app.selected=null;
  const model=app.state?.global||{},conditions=Array.isArray(model.conditions)?model.conditions:[];
  $('#drawer-eyebrow').textContent='Overall health';
  $('#drawer-title').textContent='MonitorBox';
  $('#drawer-state').className=`state-pill ${esc(model.state||app.state?.overall||'unknown')}`;
  $('#drawer-state').textContent=stateLabel(model.state||app.state?.overall||'unknown');
  const conditionRows=conditions.length?conditions.map((condition,index)=>{
    const site=(app.state?.sites||[]).find(item=>item.id===condition.site_id);
    const label=site?`${site.label} · ${condition.label||condition.id}`:(condition.label||condition.id);
    return`<button class="parity-global-condition" data-global-condition="${index}" type="button"><strong>${esc(label)}</strong>${pill(condition.state||'unknown')}<p>${esc(condition.summary||'Needs attention')}</p></button>`;
  }).join(''):'<div class="chart-empty">All configured health participants are reporting normally.</div>';
  $('#drawer-body').innerHTML=`<section class="detail-section"><h3>Current conditions</h3><div class="parity-global-conditions">${conditionRows}</div></section><section class="detail-section"><h3>Actions</h3><div class="action-list"><button class="button" data-parity-check-all type="button">Check Everything Now</button></div></section>`;
  document.querySelector('[data-parity-check-all]')?.addEventListener('click',()=>$('#check-all')?.click());
  bindParityGlobalConditions(conditions);
  const drawer=$('#drawer');if(!drawer.open)drawer.showModal();
}

render=function(){
  if(!app.state)return;
  const model=app.state.global||{},overall=model.state||app.state.overall||'unknown';
  const global=$('#global');
  global.className=`global parity-global ${overall}`;
  $('#global-state').className=`state-pill ${overall}`;
  $('#global-state').textContent=stateLabel(overall);
  $('#build-id').textContent=MONITORBOX_BUILD_ID;
  document.title=`${app.state.title||'MonitorBox'} · ${MONITORBOX_BUILD_ID}`;
  const conditions=Array.isArray(model.conditions)?model.conditions:[];
  $('#global-title').textContent=model.summary||(overall==='healthy'?'Everything is fine':overall==='failed'?'Action required':overall==='degraded'?'Something needs attention':'Monitoring state is incomplete');
  $('#global-copy').textContent=conditions.length?`${conditions.length} current condition${conditions.length===1?'':'s'} · tap to inspect`:'All monitored systems are reporting normally.';
  $('#core-grid').innerHTML=parityCoreMarkup();
  $('#services-grid').innerHTML=parityServiceMarkup();
  const total=parityServiceCount(),healthy=parityHealthyServiceCount();
  $('#services-summary').textContent=total?`${healthy} of ${total} reporting normally · tap to inspect`:'No services configured';
  const sites=app.state.sites||[],agents=sites.reduce((sum,site)=>sum+(site.agents||[]).length,0),connected=sites.reduce((sum,site)=>sum+(site.agents||[]).filter(agent=>agent.connected).length,0);
  $('#footer-state').textContent=`${connected}/${agents} agents connected · ${total} services · ${MONITORBOX_BUILD_ID}`;
  bindCards();
  global.onclick=openParityGlobal;
};
