'use strict';

app.livePingState={sessions:[]};
app.pingLeases={};
app.pingTimers={};

const baseRenderActions=renderActions;
const baseBindDrawer=bindDrawer;

function pingAction(object){return(object.actions||[]).find(action=>action.kind==='ping');}
function pingSession(siteId,objectId){return(app.livePingState.sessions||[]).find(item=>item.site_id===siteId&&item.object_id===objectId);}

function livePingSection(site,object){
  const action=pingAction(object);
  if(!action)return'';
  const session=pingSession(site.id,object.id),lease=app.pingLeases[`${site.id}/${object.id}`];
  if(!session&&!lease)return`<section class="detail-section"><h3>Live diagnostics</h3><button class="button secondary" data-live-ping-start type="button">Continuous ping</button><p class="component-meta" style="margin-top:.65rem">Ephemeral live samples are collected by the site agent and are not written to monitoring history.</p></section>`;
  const stats=session?.statistics||{},samples=(session?.samples||[]).map(item=>({time:item.timestamp,value:item.reachable?item.latency_ms:null}));
  const latest=[...(session?.samples||[])].reverse().find(item=>item.reachable&&Number.isFinite(item.latency_ms));
  return`<section class="detail-section"><h3>Continuous ping <span class="live-diagnostic-label">● LIVE</span></h3><div class="metrics"><div class="metric"><b>${latest?`${Number(latest.latency_ms).toFixed(1)} ms`:'No reply'}</b><span>latest RTT</span></div><div class="metric"><b>${stats.minimum_ms??'—'}${stats.minimum_ms!=null?' ms':''}</b><span>minimum</span></div><div class="metric"><b>${stats.average_ms??'—'}${stats.average_ms!=null?' ms':''}</b><span>average</span></div><div class="metric"><b>${stats.maximum_ms??'—'}${stats.maximum_ms!=null?' ms':''}</b><span>maximum</span></div><div class="metric"><b>${stats.loss_percent??0}%</b><span>packet loss</span></div></div>${samples.length>1?chart('live_latency_ms',samples):'<div class="chart-empty">Collecting samples…</div>'}<div class="action-list"><button class="button secondary" data-live-ping-stop type="button">Stop continuous ping</button></div>${session?.last_error?`<p class="component-meta">${esc(session.last_error)}</p>`:''}</section>`;
}

renderActions=function(site,object){
  const originalActions=object.actions;
  object.actions=(originalActions||[]).filter(action=>action.kind!=='ping');
  const html=baseRenderActions(site,object);
  object.actions=originalActions;
  return html+livePingSection(site,object);
};

bindDrawer=function(site,object){
  baseBindDrawer(site,object);
  document.querySelector('[data-live-ping-start]')?.addEventListener('click',()=>startLivePing(site.id,object.id));
  document.querySelector('[data-live-ping-stop]')?.addEventListener('click',()=>stopLivePing(site.id,object.id));
};

async function refreshLivePing(){
  try{
    app.livePingState=await api('/api/v2/live-ping');
    if(app.selected&&app.pingLeases[`${app.selected.siteId}/${app.selected.objectId}`])renderDrawer();
  }catch(_){}
}

async function acquireLivePing(siteId,objectId,leaseId=null){
  const body=leaseId?{lease_id:leaseId}:{};
  return api(`/api/v2/live-ping/${encodeURIComponent(siteId)}/${encodeURIComponent(objectId)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

async function startLivePing(siteId,objectId){
  const key=`${siteId}/${objectId}`;
  try{
    const result=await acquireLivePing(siteId,objectId,app.pingLeases[key]);
    app.pingLeases[key]=result.lease_id;
    app.livePingState.sessions=[...(app.livePingState.sessions||[]).filter(item=>!(item.site_id===siteId&&item.object_id===objectId)),result.session];
    clearInterval(app.pingTimers[key]);
    app.pingTimers[key]=setInterval(async()=>{
      if(!app.selected||app.selected.siteId!==siteId||app.selected.objectId!==objectId){await stopLivePing(siteId,objectId,false);return;}
      try{const renewed=await acquireLivePing(siteId,objectId,app.pingLeases[key]);app.pingLeases[key]=renewed.lease_id;await refreshLivePing();}catch(_){await stopLivePing(siteId,objectId,false);}
    },8000);
    renderDrawer();
    await refreshLivePing();
  }catch(error){toast(`Continuous ping unavailable: ${error.message}`);}
}

async function stopLivePing(siteId,objectId,notify=true){
  const key=`${siteId}/${objectId}`,lease=app.pingLeases[key];
  clearInterval(app.pingTimers[key]);delete app.pingTimers[key];delete app.pingLeases[key];
  if(lease){try{await fetch(`/api/v2/live-ping/${encodeURIComponent(siteId)}/${encodeURIComponent(objectId)}/leases/${encodeURIComponent(lease)}`,{method:'DELETE',keepalive:true});}catch(_){}}
  app.livePingState.sessions=(app.livePingState.sessions||[]).filter(item=>!(item.site_id===siteId&&item.object_id===objectId));
  if(app.selected?.siteId===siteId&&app.selected?.objectId===objectId)renderDrawer();
  if(notify)toast('Continuous ping stopped');
}

setInterval(()=>{if(Object.keys(app.pingLeases).length)refreshLivePing();},1000);
window.addEventListener('beforeunload',()=>{for(const [key] of Object.entries(app.pingLeases)){const slash=key.indexOf('/');stopLivePing(key.slice(0,slash),key.slice(slash+1),false);}});
