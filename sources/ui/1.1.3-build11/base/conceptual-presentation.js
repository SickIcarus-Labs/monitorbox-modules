'use strict';

// The controller exposes canonical objects plus optional conceptual presentation
// groups. Keep raw child objects addressable in state/API while rendering only
// the configured front-page participants. This is presentation policy, not a
// second health model: overall/site/global state comes from the controller.
const conceptualBaseWorstSummary=worstSummary;
const conceptualBaseRenderSite=renderSite;
const conceptualBaseRenderActions=renderActions;
const conceptualBaseBindDrawer=bindDrawer;

worstSummary=function(object){
  return object.summary||conceptualBaseWorstSummary(object);
};

renderSite=function(site){
  const original=site.objects;
  site.objects=(original||[]).filter(object=>object.front_page!==false);
  try{return conceptualBaseRenderSite(site);}
  finally{site.objects=original;}
};

renderActions=function(site,object){
  const base=conceptualBaseRenderActions(site,object);
  if(object.id!=='power')return base;
  return base.replace(
    '</div></section>',
    '<button class="button secondary" data-clear-power-events type="button">Clear recent power events</button></div></section>',
  );
};

bindDrawer=function(site,object){
  conceptualBaseBindDrawer(site,object);
  if(object.id!=='power')return;
  document.querySelector('[data-clear-power-events]')?.addEventListener('click',event=>{
    clearPowerEvents(site.id,event.currentTarget);
  });
};

async function clearPowerEvents(siteId,button){
  if(!globalThis.confirm("Clear MonitorBox's local power/lifecycle event journal? Current power and lifecycle state will not be changed."))return;
  if(button)button.disabled=true;
  try{
    const operation=await api(`/api/v2/sites/${encodeURIComponent(siteId)}/power/events/clear`,{
      method:'POST',headers:{'Idempotency-Key':requestId()},
    });
    app.operation=operation;showOperation();
    await pollOperation(operation.id);
    toast('Power event journal cleared');
  }catch(error){toast(`Clear failed: ${error.message}`);}
  finally{if(button)button.disabled=false;}
}

function fallbackGlobalConditions(){
  return(app.state.sites||[]).flatMap(site=>(site.objects||[])
    .filter(object=>object.health_participant!==false&&stateRank(object.state)>0)
    .map(object=>({site_id:site.id,id:object.id,label:object.label,state:object.state,summary:object.summary})));
}

render=function(){
  if(!app.state)return;
  const model=app.state.global||{},overall=model.state||app.state.overall||'unknown',global=$('#global');
  global.className=`global ${overall}`;
  $('#global-state').className=`state-pill ${overall}`;
  $('#global-state').textContent=stateLabel(overall);
  const conditionModels=Array.isArray(model.conditions)?model.conditions:fallbackGlobalConditions();
  const conditions=conditionModels.map(condition=>{
    const site=(app.state.sites||[]).find(item=>item.id===condition.site_id);
    return site?`${site.label}: ${condition.label||condition.id}`:(condition.label||condition.id);
  });
  $('#global-title').textContent=model.summary||(overall==='healthy'?'Everything is fine':overall==='failed'?'Action required':overall==='degraded'?'Something needs attention':'Monitoring state is incomplete');
  $('#global-copy').textContent=conditions.length?`${conditions.length} condition${conditions.length===1?'':'s'}: ${conditions.slice(0,3).join(' · ')}${conditions.length>3?'…':''}`:'All configured health participants are reporting normally.';
  $('#sites').innerHTML=(app.state.sites||[]).map(renderSite).join('');
  bindCards();
};
