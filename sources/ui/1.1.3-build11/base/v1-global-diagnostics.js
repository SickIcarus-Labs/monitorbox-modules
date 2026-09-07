'use strict';

const v1GlobalBaseOpenParityGlobal=openParityGlobal;

function v1ControllerDiagnostics(){
  const controller=app.state?.controller;if(!controller)return'';
  const m=controller.metrics||{},boxes=[];
  if(Number.isFinite(m.uptime_seconds))boxes.push(parityMetricBox('controller uptime',`${Math.floor(m.uptime_seconds/3600)}h ${Math.floor((m.uptime_seconds%3600)/60)}m`));
  if(Number.isFinite(m.filesystem_free_bytes))boxes.push(parityMetricBox('state filesystem free',parityFormatBytes(m.filesystem_free_bytes)));
  if(Number.isFinite(m.database_bytes))boxes.push(parityMetricBox('controller database',parityFormatBytes(m.database_bytes)));
  if(Number.isFinite(m.wal_bytes))boxes.push(parityMetricBox('controller WAL',parityFormatBytes(m.wal_bytes)));
  if(Number.isFinite(m.process_rss_bytes))boxes.push(parityMetricBox('controller RSS',parityFormatBytes(m.process_rss_bytes)));
  const agents=(app.state?.sites||[]).flatMap(site=>(site.agents||[]).map(agent=>({site,agent}))),connected=agents.filter(item=>item.agent.connected).length;
  boxes.push(parityMetricBox('agents connected',`${connected}/${agents.length}`));
  return`<section class="detail-section"><h3>MonitorBox diagnostics</h3><p class="parity-detail-summary">${esc(controller.summary||'Controller diagnostic state available')}</p><div class="metrics">${boxes.join('')}</div></section>`;
}

openParityGlobal=function(){
  v1GlobalBaseOpenParityGlobal();
  const actions=document.querySelector('[data-parity-check-all]')?.closest('.detail-section');
  const html=v1ControllerDiagnostics();
  if(html&&actions)actions.insertAdjacentHTML('beforebegin',html);
};
