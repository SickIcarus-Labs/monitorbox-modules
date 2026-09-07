'use strict';

app.dashboardConfiguration={loaded:false,configured:false,sites:{}};

function dashboardWidgetSites(){
  const ordered=(app.state?.sites||[]).map(site=>site.id);
  const extras=Object.keys(app.dashboardConfiguration.sites||{}).filter(id=>!ordered.includes(id)).sort();
  return[...ordered,...extras];
}

function dashboardLiveWidgets(){
  const output=[];
  dashboardWidgetSites().forEach(siteId=>{
    const site=app.dashboardConfiguration.sites?.[siteId];
    if(!site||!Array.isArray(site.widgets))return;
    site.widgets.forEach((widget,index)=>{
      if(widget?.kind!=='live_metric'||widget.enabled===false)return;
      const source=widget.source||{};
      const metricId=String(source.metric_id||'');
      if(!metricId)return;
      output.push({siteId,index,widget,metricId,objectId:String(source.object_id||''),runtimeCheckId:String(source.runtime_check_id||'')});
    });
  });
  return output;
}

function dashboardWidgetSeries(item){
  return(app.liveTelemetry.series||[]).find(series=>{
    if(series.site_id!==item.siteId||series.id!==item.metricId)return false;
    if(item.objectId&&String(series.object_id||'')!==item.objectId)return false;
    if(item.runtimeCheckId&&String(series.check_id||'')!==item.runtimeCheckId)return false;
    return true;
  })||null;
}

function dashboardWidgetPlaceholder(item){
  const label=item.widget.label||item.metricId;
  return`<article class="metric-chart"><div class="chart-headline"><strong>${esc(label)}</strong><span>Waiting</span></div><div class="chart-empty">Collecting configured live metric…</div></article>`;
}

const baseRenderLiveOverviewForWidgets=renderLiveOverview;
renderLiveOverview=function(){
  if(!app.dashboardConfiguration.loaded||!app.dashboardConfiguration.configured){baseRenderLiveOverviewForWidgets();return;}
  const section=document.querySelector('#live-overview'),grid=document.querySelector('#live-overview-grid');
  if(!section||!grid)return;
  const widgets=dashboardLiveWidgets();
  if(!widgets.length){section.classList.add('hidden');grid.innerHTML='';return;}
  section.classList.remove('hidden');
  grid.innerHTML=widgets.map(item=>{
    const series=dashboardWidgetSeries(item);
    if(!series)return dashboardWidgetPlaceholder(item);
    const configuredLabel=item.widget.label,presentation=item.widget.presentation||{};
    const windowSeconds=Math.min(Math.max(Number(presentation.window_seconds)||300,30),900);
    return liveChart(configuredLabel?{...series,label:configuredLabel}:series,windowSeconds);
  }).join('');
  bindTrafficCards(grid);
};

async function loadDashboardConfiguration(){
  try{
    const payload=await api('/api/v2/dashboard/config');
    app.dashboardConfiguration={loaded:true,configured:payload.configured===true,revision:payload.revision,sites:payload.sites||{}};
  }catch(error){
    console.warn('dashboard widget configuration unavailable; preserving runtime fallback',error);
    app.dashboardConfiguration={loaded:true,configured:false,sites:{}};
  }
  renderLiveOverview();
}

void loadDashboardConfiguration();
