'use strict';

// UI 1.1.1 build 9: keep throughput evidence independent from optional
// gateway-flow attribution. The accepted live-telemetry producer already emits
// busiest-client data as a normal counter_pair series; this delta deliberately
// does not coerce malformed producer data or replace the baseline chart renderer.
const uiBuild9BaseTrafficAttributionHtml=trafficAttributionHtml;

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
