'use strict';

// UI 1.1.1 build 9: restore the accepted traffic-detail presentation contract.
// Counter telemetry remains authoritative for throughput even when optional
// gateway-flow attribution is empty or unavailable. Busiest-client counter
// series are presentation data and must remain visible when their shape is valid.
const uiBuild9BaseLiveChart=liveChart;
const uiBuild9BaseTrafficAttributionHtml=trafficAttributionHtml;

function uiBuild9BusiestCounterSeries(series){
  if(!series||series.kind==='counter_pair')return series;
  if(series.traffic_subject!=='busiest')return series;
  const points=Array.isArray(series.points)?series.points:[];
  const counterShaped=points.some(point=>point&&point.valid&&(
    Number.isFinite(Number(point.rx))||Number.isFinite(Number(point.tx))
  ));
  return counterShaped?{...series,kind:'counter_pair'}:series;
}

liveChart=function(series,...args){
  return uiBuild9BaseLiveChart(uiBuild9BusiestCounterSeries(series),...args);
};

renderLiveOverview=function(){
  const section=document.querySelector('#live-overview'),grid=document.querySelector('#live-overview-grid');
  if(!section||!grid)return;
  const counters=(app.liveTelemetry.series||[])
    .map(uiBuild9BusiestCounterSeries)
    .filter(series=>series?.kind==='counter_pair')
    .sort((a,b)=>liveOverviewRank(a)-liveOverviewRank(b)||String(a.label).localeCompare(String(b.label)));
  if(!counters.length){section.classList.add('hidden');grid.innerHTML='';return;}
  section.classList.remove('hidden');
  grid.innerHTML=counters.map(item=>liveChart(item,300)).join('');
  bindTrafficCards(grid);
};

function uiBuild9ProviderFailureHtml(payload){
  const detail=String(payload?.error||payload?.provider_error||'').trim();
  const failure=detail
    ? `<p class="component-meta" style="margin-top:.65rem">Provider/configuration error: ${esc(detail)}</p>`
    : '';
  return`<section class="detail-section"><h3>Flow attribution</h3><div class="chart-empty">Flow attribution unavailable — the traffic-detail provider or its configuration is unavailable for this graph.</div><p class="component-meta" style="margin-top:.65rem">Throughput above remains valid from counter telemetry. Gateway-flow attribution is a separate optional evidence source.</p>${failure}</section>`;
}

trafficAttributionHtml=function(payload){
  if(payload?.attribution_available===false)return uiBuild9ProviderFailureHtml(payload);
  return uiBuild9BaseTrafficAttributionHtml(payload);
};

refreshTrafficAttribution=async function(selection=app.liveTrafficSelection){
  if(!selection?.subject)return;
  const token=++app.liveTrafficRequest;
  selection.lastFetchAt=Date.now();
  let payload;
  try{
    payload=await api(`/api/v2/sites/${encodeURIComponent(selection.siteId)}/traffic/${encodeURIComponent(selection.subject)}?window=900`);
  }catch(error){
    payload={
      subject:selection.subject,
      attribution_available:false,
      provider_available:false,
      error:error?.message||String(error),
      scope:'Gateway-visible routed traffic only',
    };
  }
  if(app.liveTrafficSelection!==selection||token!==app.liveTrafficRequest)return;
  if(selection.subject==='busiest'){
    const current=trafficSeriesIdentity(selectedTrafficSeries());
    const currentKey=trafficIdentityKey(current);
    const resolvedKey=trafficIdentityKey(payload.resolved_subject||null);
    if(currentKey&&resolvedKey&&currentKey!==resolvedKey){
      selection.identity=current;
      selection.identityKey=currentKey;
      app.liveTrafficPayload=null;
      renderTrafficDrawer();
      void refreshTrafficAttribution(selection);
      return;
    }
  }
  app.liveTrafficPayload=payload;
  renderTrafficDrawer();
};
