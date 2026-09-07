'use strict';

app.liveTelemetry={series:[]};
app.liveTelemetryViewer=sessionStorage.getItem('monitorbox-live-viewer')||requestId();
sessionStorage.setItem('monitorbox-live-viewer',app.liveTelemetryViewer);
app.liveTrafficSelection=null;
app.liveTrafficPayload=null;
app.liveTrafficRequest=0;

const baseRenderForTelemetry=render;
const baseRenderComponentsForTelemetry=renderComponents;

function liveSeries(siteId,objectId=null){
  return(app.liveTelemetry.series||[]).filter(series=>series.site_id===siteId&&(!objectId||series.object_id===objectId));
}

function liveObjectIndex(siteId,objectId){
  const site=(app.state?.sites||[]).find(item=>item.id===siteId);
  const index=(site?.objects||[]).findIndex(item=>item.id===objectId);
  return index<0?999:index;
}

function liveOverviewRank(series){
  // Production v1 order: ordinary host counters in manifest order, then WAN,
  // then the dynamically selected busiest client/host. This stays generic: no
  // deployment host names or IDs are encoded here.
  if(series.traffic_subject==='wan')return 10000;
  if(series.traffic_subject==='busiest')return 20000;
  return liveObjectIndex(series.site_id,series.object_id);
}

function liveDetailRank(series){
  const label=String(series.label||'').toLowerCase();
  if(series.kind==='counter_pair'||label.includes('network')||label.includes('throughput'))return 0;
  if(label.includes('cpu'))return 10;
  if(label.includes('memory')||label.includes('ram'))return 20;
  if(label.includes('load'))return 30;
  if(label.includes('battery'))return 40;
  if(label.includes('runtime'))return 50;
  return 100;
}

function liveNumber(value,unit){
  if(!Number.isFinite(value))return'—';
  if(unit==='bit/s'){
    const units=['bit/s','Kbit/s','Mbit/s','Gbit/s','Tbit/s'];let v=value,i=0;
    while(Math.abs(v)>=1000&&i<units.length-1){v/=1000;i++;}
    return`${v.toFixed(Math.abs(v)>=100?0:Math.abs(v)>=10?1:2)} ${units[i]}`;
  }
  if(unit==='GiB')return`${value.toFixed(1)} GiB`;
  if(unit==='%')return`${value.toFixed(Math.abs(value)>=10?0:1)}%`;
  if(unit==='min')return`${value.toFixed(Math.abs(value)>=100?0:1)} min`;
  return`${value.toFixed(Math.abs(value)>=100?0:Math.abs(value)>=10?1:2)}${unit?` ${unit}`:''}`;
}

function livePath(points,key,left,right,top,bottom,min,max,startMs,endMs,maxGapMs){
  let path='',started=false,previousTimestamp=null;
  const span=Math.max(endMs-startMs,1);
  points.forEach(point=>{
    const timestamp=new Date(point.timestamp).getTime();
    const value=point.valid?Number(point[key]):NaN;
    if(!Number.isFinite(timestamp)||timestamp<startMs||timestamp>endMs||!Number.isFinite(value)){
      if(Number.isFinite(timestamp))previousTimestamp=timestamp;
      started=false;
      return;
    }
    if(previousTimestamp!==null&&timestamp-previousTimestamp>maxGapMs)started=false;
    const x=left+(right-left)*((timestamp-startMs)/span);
    const y=bottom-(bottom-top)*((value-min)/(max-min));
    path+=`${started?'L':'M'}${x.toFixed(1)},${y.toFixed(1)} `;
    started=true;
    previousTimestamp=timestamp;
  });
  return path;
}

function liveChart(series,windowSeconds=300,interactive=true){
  const endMs=Date.now(),startMs=endMs-windowSeconds*1000;
  const points=(series.points||[]).filter(point=>{
    const timestamp=new Date(point.timestamp).getTime();
    return Number.isFinite(timestamp)&&timestamp>=startMs&&timestamp<=endMs;
  });
  const valid=points.filter(point=>point.valid);
  if(valid.length<2)return'<div class="chart-empty">Collecting live samples…</div>';
  const counter=series.kind==='counter_pair',values=[];
  valid.forEach(point=>{if(counter){if(Number.isFinite(point.rx))values.push(Number(point.rx));if(Number.isFinite(point.tx))values.push(Number(point.tx));}else if(Number.isFinite(point.value))values.push(Number(point.value));});
  if(!values.length)return'<div class="chart-empty">Live samples unavailable.</div>';
  const configured=Number(series.maximum),minimum=0;
  let maximum=Number.isFinite(configured)&&configured>0?configured:Math.max(...values,1)*1.08;
  if(maximum<=minimum)maximum=minimum+1;
  const W=640,H=210,left=68,right=626,top=12,bottom=178;
  const grid=[0,.5,1].map(r=>{const value=maximum-(maximum-minimum)*r,yy=top+(bottom-top)*r;return`<line class="chart-grid" x1="${left}" x2="${right}" y1="${yy}" y2="${yy}"/><text class="chart-axis" x="58" y="${yy+4}" text-anchor="end">${esc(liveNumber(value,series.unit||''))}</text>`;}).join('');
  const first=valid[0],last=valid[valid.length-1];
  const activeCadence=Math.max(.5,Number(series.active_interval_seconds)||1);
  const backgroundCadence=Math.max(.5,Number(series.background_interval_seconds)||15);
  const nominal=Math.max(activeCadence,backgroundCadence);
  const maxGapMs=Math.max(2500,nominal*2500);
  const primary=livePath(points,counter?'rx':'value',left,right,top,bottom,minimum,maximum,startMs,endMs,maxGapMs);
  const secondary=counter?livePath(points,'tx',left,right,top,bottom,minimum,maximum,startMs,endMs,maxGapMs):'';
  const current=counter?`${liveNumber(Number(last.rx),series.unit)} ↓ · ${liveNumber(Number(last.tx),series.unit)} ↑`:liveNumber(Number(last.value),series.unit);
  const subject=counter&&last.subject?.name?` · ${esc(last.subject.name)}`:'';
  const drill=counter&&interactive?` data-traffic-site="${esc(series.site_id)}" data-traffic-subject="${esc(series.traffic_subject||'')}" data-traffic-label="${esc(series.label)}" data-traffic-series="${esc(series.id)}" data-traffic-object="${esc(series.object_id||'')}" role="button" tabindex="0" style="cursor:pointer"`:'';
  return`<article class="metric-chart"${drill}><div class="chart-headline"><strong>${esc(series.label)}${subject}</strong><span>${esc(current)}</span></div><div class="chart-wrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Live ${esc(series.label)}"><g>${grid}</g><path class="chart-path" d="${primary}"/>${secondary?`<path class="chart-path chart-path-secondary" d="${secondary}"/>`:''}<text class="chart-axis" x="${left}" y="202">${esc(ageText(first.timestamp))}</text><text class="chart-axis" x="${right}" y="202" text-anchor="end">live</text></svg></div></article>`;
}

function liveTelemetrySection(site,object){
  const series=liveSeries(site.id,object.id).sort((a,b)=>liveDetailRank(a)-liveDetailRank(b)||String(a.label).localeCompare(String(b.label)));
  if(!series.length)return'';
  return`<section id="live-telemetry-section" class="detail-section"><h3>Live telemetry <span class="live-diagnostic-label">● LIVE</span></h3><div class="live-detail-grid">${series.map(item=>liveChart(item,900)).join('')}</div><p class="component-meta" style="margin-top:.65rem">Viewer-aware presentation samples are ephemeral and are not written to canonical monitoring history.</p></section>`;
}

renderComponents=function(site,object){return baseRenderComponentsForTelemetry(site,object)+liveTelemetrySection(site,object);};

function renderLiveOverview(){
  const section=document.querySelector('#live-overview'),grid=document.querySelector('#live-overview-grid');
  if(!section||!grid)return;
  const counters=(app.liveTelemetry.series||[]).filter(series=>series.kind==='counter_pair')
    .sort((a,b)=>liveOverviewRank(a)-liveOverviewRank(b)||String(a.label).localeCompare(String(b.label)));
  if(!counters.length){section.classList.add('hidden');grid.innerHTML='';return;}
  section.classList.remove('hidden');
  grid.innerHTML=counters.map(item=>liveChart(item,300)).join('');
  bindTrafficCards(grid);
}

render=function(){baseRenderForTelemetry();renderLiveOverview();};

function refreshSelectedLiveSection(){
  if(!app.selected)return;
  const {site,object}=findObject(app.selected.siteId,app.selected.objectId);if(!site||!object)return;
  const html=liveTelemetrySection(site,object),existing=document.querySelector('#live-telemetry-section');
  if(existing){if(html)existing.outerHTML=html;else existing.remove();bindTrafficCards(document);return;}
  if(!html)return;
  const history=document.querySelector('#history-charts')?.closest('.detail-section');
  if(history)history.insertAdjacentHTML('beforebegin',html);
  bindTrafficCards(document);
}

function trafficRate(flow){return liveNumber(Number(flow.average_bits_per_second),'bit/s');}
function trafficBytes(value){
  if(!Number.isFinite(Number(value)))return'—';
  const units=['B','KiB','MiB','GiB','TiB'];let v=Number(value),i=0;
  while(Math.abs(v)>=1024&&i<units.length-1){v/=1024;i++;}
  return`${v.toFixed(Math.abs(v)>=100?0:Math.abs(v)>=10?1:2)} ${units[i]}`;
}
function trafficWhen(flow){
  const value=flow.last_seen_at||flow.time;
  if(!value)return'';
  const parsed=new Date(value);
  return Number.isFinite(parsed.getTime())?` · ${ageText(parsed.toISOString())}`:'';
}
function trafficRow(flow){
  const peer=flow.peer||`${flow.source||'Unknown'} → ${flow.destination||'Unknown'}`;
  const direction=flow.subject_direction?` · ${flow.subject_direction}`:'';
  const service=flow.service||flow.protocol||'Unknown';
  return`<div class="component-row"><strong>${esc(peer)}</strong><span>${esc(trafficBytes(flow.bytes))}</span><p>${esc(service)}${esc(direction)} · ${esc(trafficRate(flow))}${esc(trafficWhen(flow))}</p></div>`;
}

function selectedTrafficSeries(){
  const selected=app.liveTrafficSelection;
  if(!selected)return null;
  return(app.liveTelemetry.series||[]).find(series=>series.site_id===selected.siteId&&series.id===selected.seriesId)||null;
}

function trafficSeriesIdentity(series){
  const points=(series?.points||[]).filter(point=>point.valid&&point.subject&&typeof point.subject==='object');
  const subject=points.length?points[points.length-1].subject:null;
  if(!subject)return null;
  return{
    name:subject.name?String(subject.name):'',
    ip:subject.ip?String(subject.ip):'',
    mac:subject.mac?String(subject.mac).toLowerCase():'',
  };
}

function trafficIdentityKey(identity){
  if(!identity)return'';
  return`${identity.mac||''}|${identity.ip||''}|${identity.name||''}`;
}

function trafficAttributionHtml(payload){
  const selected=app.liveTrafficSelection;
  if(selected?.subject&&!payload){
    const who=selected.identity?.name?` for ${esc(selected.identity.name)}`:'';
    return`<section class="detail-section"><h3>Flow attribution</h3><div class="chart-empty">Refreshing matching flow attribution${who}…</div></section>`;
  }
  if(!payload?.attribution_available){
    return`<section class="detail-section"><h3>Flow attribution</h3><div class="chart-empty">Flow attribution unavailable — no flow-capable provider is configured for this graph.</div><p class="component-meta" style="margin-top:.65rem">Throughput remains valid from the configured counter telemetry. SNMP/interface counters measure traffic volume but do not identify clients or flows.</p></section>`;
  }
  if(payload.subject==='busiest'&&!payload.resolved_subject){
    return`<section class="detail-section"><h3>Flow attribution</h3><div class="chart-empty">The busiest-client identity is still being established. MonitorBox will not substitute another client's flows.</div></section>`;
  }
  const flows=payload.flows||[];
  const coverage=Number(payload.coverage_seconds||0);
  const samples=Number(payload.sample_count||0);
  const coverageText=samples?`${Math.round(coverage)}s sampled across ${samples} matching provider snapshots`:'No matching sampled provider evidence yet';
  const partial=payload.provider_partial||payload.partial;
  const warning=partial?' Attribution is sampled/partial; traffic the provider did not expose remains unattributed.':'';
  const error=payload.error?` Last provider error: ${payload.error}.`:'';
  const resolved=payload.resolved_subject?.name?` · ${esc(payload.resolved_subject.name)}`:'';
  const dynamicNote=payload.subject==='busiest'?' Busiest-client attribution is identity-bound; previous winners are not mixed into this list.':'';
  return`<section class="detail-section"><h3>Dominant recent flows${resolved}</h3><div class="component-list">${flows.length?flows.map(trafficRow).join(''):'<div class="chart-empty">No matching gateway-visible flows were captured in this interval.</div>'}</div><p class="component-meta" style="margin-top:.65rem">${esc(payload.scope||'Gateway-visible routed traffic only')}. ${esc(payload.limitation||'Same-L2 switched traffic does not cross the gateway and is not attributed.')} ${esc(coverageText)}.${esc(warning)}${esc(dynamicNote)}${esc(error)}</p></section>`;
}

function renderTrafficDrawer(){
  const selected=app.liveTrafficSelection;if(!selected)return;
  const series=selectedTrafficSeries();
  $('#drawer-eyebrow').textContent='Last fifteen minutes';
  $('#drawer-title').textContent=selected.label||series?.label||'Network traffic';
  $('#drawer-state').className='state-pill healthy';
  $('#drawer-state').textContent='15 min';
  $('#drawer-body').innerHTML=`<section class="detail-section"><h3>Traffic history</h3><div id="traffic-detail-chart">${series?liveChart(series,900,false):'<div class="chart-empty">Collecting 15-minute detail samples…</div>'}</div><p class="component-meta" style="margin-top:.65rem">Front-page graphs show five minutes; traffic detail preserves the v1 fifteen-minute drill-down window.</p></section>${trafficAttributionHtml(app.liveTrafficPayload)}`;
  const drawer=$('#drawer');if(!drawer.open)drawer.showModal();
}

async function refreshTrafficAttribution(selection=app.liveTrafficSelection){
  if(!selection?.subject)return;
  const token=++app.liveTrafficRequest;
  selection.lastFetchAt=Date.now();
  let payload;
  try{
    payload=await api(`/api/v2/sites/${encodeURIComponent(selection.siteId)}/traffic/${encodeURIComponent(selection.subject)}?window=900`);
  }catch(error){
    payload={subject:selection.subject,attribution_available:true,flows:[],partial:true,error:error.message,scope:'Gateway-visible routed traffic only'};
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
}

function refreshTrafficDrawerGraph(){
  const selected=app.liveTrafficSelection;if(!selected)return;
  const series=selectedTrafficSeries();
  if(selected.subject==='busiest'){
    const identity=trafficSeriesIdentity(series);
    const identityKey=trafficIdentityKey(identity);
    if(identityKey&&identityKey!==selected.identityKey){
      selected.identity=identity;
      selected.identityKey=identityKey;
      selected.lastFetchAt=0;
      app.liveTrafficPayload=null;
      app.liveTrafficRequest++;
      renderTrafficDrawer();
      void refreshTrafficAttribution(selected);
      return;
    }
  }
  const target=document.querySelector('#traffic-detail-chart');if(!target)return;
  target.innerHTML=series?liveChart(series,900,false):'<div class="chart-empty">Collecting 15-minute detail samples…</div>';
  if(selected.subject&&Date.now()-Number(selected.lastFetchAt||0)>=10000){
    void refreshTrafficAttribution(selected);
  }
}

async function openTrafficDetails(siteId,subject,label,seriesId,objectId){
  app.selected=null;
  app.liveTrafficRequest++;
  app.liveTrafficSelection={siteId,subject,label,seriesId,objectId,lastFetchAt:0};
  const identity=subject==='busiest'?trafficSeriesIdentity(selectedTrafficSeries()):null;
  app.liveTrafficSelection.identity=identity;
  app.liveTrafficSelection.identityKey=trafficIdentityKey(identity);
  app.liveTrafficPayload=subject?null:{attribution_available:false};
  renderTrafficDrawer();
  if(subject)await refreshTrafficAttribution(app.liveTrafficSelection);
}

function bindTrafficCards(root=document){
  root.querySelectorAll('[data-traffic-series]').forEach(card=>{
    if(card.dataset.trafficBound==='1')return;
    card.dataset.trafficBound='1';
    const open=()=>openTrafficDetails(card.dataset.trafficSite,card.dataset.trafficSubject||'',card.dataset.trafficLabel,card.dataset.trafficSeries,card.dataset.trafficObject||'');
    card.addEventListener('click',open);
    card.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});
  });
}

function repaintLiveTelemetry(){
  if(document.hidden)return;
  renderLiveOverview();
  refreshSelectedLiveSection();
  refreshTrafficDrawerGraph();
}

let liveTelemetryRefreshRunning=false;
async function refreshLiveTelemetry(){
  if(liveTelemetryRefreshRunning)return;
  liveTelemetryRefreshRunning=true;
  const selectedDetail=app.selected?`${app.selected.siteId}/${app.selected.objectId}`:'';
  const trafficDetail=app.liveTrafficSelection?`${app.liveTrafficSelection.siteId}/${app.liveTrafficSelection.objectId}`:'';
  const detail=selectedDetail||trafficDetail;
  const windowSeconds=detail?900:300;
  try{
    app.liveTelemetry=await api(`/api/v2/live?window=${windowSeconds}${detail?`&detail=${encodeURIComponent(detail)}`:''}`,{headers:{'X-MonitorBox-Viewer':app.liveTelemetryViewer}});
    repaintLiveTelemetry();
  }catch(_){}
  finally{liveTelemetryRefreshRunning=false;}
}

$('#drawer')?.addEventListener('close',()=>{app.liveTrafficRequest++;app.liveTrafficSelection=null;app.liveTrafficPayload=null;});
refreshLiveTelemetry();
setInterval(refreshLiveTelemetry,1000);
setInterval(repaintLiveTelemetry,1000);