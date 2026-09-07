'use strict';

// Specialized v1-compatible drill-downs layered on the canonical v2 object
// model. V2 remains authoritative, but the UI presents operator-level facts
// rather than every raw SNMP/storage implementation metric.
const v1DetailBaseRenderDrawer=renderDrawer;
const POWER_EVENT_TYPES=new Set([
  'commanded_reboot','commanded_shutdown','lifecycle_recovered','lifecycle_recovery_overdue',
  'utility_loss','utility_restoration','boost','boost_cleared','trim','trim_cleared',
  'lb','lb_cleared','rb','rb_cleared','over','over_cleared','bypass','bypass_cleared',
  'communications_lost','communications_restored','power_policy_threshold',
]);

function parityFormatBytes(value){
  if(!Number.isFinite(value))return'—';
  const units=['B','KiB','MiB','GiB','TiB','PiB'];let n=value,index=0;
  while(Math.abs(n)>=1024&&index<units.length-1){n/=1024;index++;}
  return`${n.toFixed(Math.abs(n)>=100?0:Math.abs(n)>=10?1:2)} ${units[index]}`;
}
function parityFormatMetric(value,kind='number'){
  if(!Number.isFinite(value))return'—';
  if(kind==='percent')return`${value.toFixed(Math.abs(value)>=10?0:1)}%`;
  if(kind==='temperature')return`${value.toFixed(1)} °C`;
  if(kind==='bytes')return parityFormatBytes(value);
  if(kind==='runtime')return`${(value/60).toFixed(value>=600?0:1)} min`;
  if(kind==='mbps')return`${value.toFixed(value>=100?0:1)} Mbps`;
  return Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
}
function parityAllMetrics(object){
  const result={};
  for(const component of object?.components||[]){
    for(const [key,value] of Object.entries(component.metrics||{}))if(Number.isFinite(value))result[key]=Number(value);
  }
  return result;
}
function parityFirstMetric(metrics,keys){for(const key of keys)if(Number.isFinite(metrics[key]))return metrics[key];return null;}
function parityMetricBox(label,value){return`<div class="metric"><b>${esc(value)}</b><span>${esc(label)}</span></div>`;}
function parityInsert(html){
  if(!html)return;
  const sections=[...document.querySelectorAll('#drawer-body > .detail-section')];
  const checks=sections.find(section=>section.querySelector(':scope > h3')?.textContent==='Checks');
  if(checks){checks.insertAdjacentHTML('beforebegin',html);return;}
  const history=document.querySelector('#history-charts')?.closest('.detail-section');
  if(history)history.insertAdjacentHTML('beforebegin',html);
  else $('#drawer-body')?.insertAdjacentHTML('beforeend',html);
}
function parityBindObjectNavigation(root=document){
  root.querySelectorAll('[data-parity-object]').forEach(node=>{
    if(node.dataset.parityBound==='1')return;
    node.dataset.parityBound='1';
    node.addEventListener('click',()=>openDrawer(node.dataset.paritySite,node.dataset.parityObject));
  });
}

function parityComponentAside(object,component){
  if(object.kind==='service'&&Number.isFinite(component.metrics?.latency_ms))return`${Number(component.metrics.latency_ms).toFixed(0)} ms`;
  return'';
}
function parityCompactChecks(site,object){
  const components=object.components||[];
  if(!components.length)return'<section class="detail-section"><h3>Checks</h3><p class="component-meta">No direct checks.</p></section>';
  return`<section class="detail-section"><h3>Checks</h3><div class="component-list">${components.map(component=>{
    const aside=parityComponentAside(object,component);
    return`<div class="component-row parity-check-row"><div><strong>${esc(component.label||component.id)}</strong><div class="component-meta">${esc(component.adapter)} · ${esc(ageText(component.observed_at))}</div></div>${aside?`<span class="parity-check-aside">${esc(aside)}</span>`:pill(component.state)}<p>${esc(component.summary||'Status unavailable')}</p><button class="button secondary" data-run-check="${esc(component.id)}" type="button">Check now</button></div>`;
  }).join('')}</div></section>`;
}

// The generic v2 drawer originally graphed the first numeric keys it found.
// That exposed implementation values such as CPU idle and allocation units.
// V1 parity uses curated 15-minute live telemetry and dedicated capacity views.
renderComponents=function(site,object){
  const live=typeof liveTelemetrySection==='function'?liveTelemetrySection(site,object):'';
  return parityCompactChecks(site,object)+live;
};
loadCharts=async function(){
  const history=document.querySelector('#history-charts')?.closest('.detail-section');
  if(history)history.remove();
};

function parityControllerHealth(object){
  const component=(object.components||[]).find(item=>item.adapter==='controller-self');
  if(!component)return'';
  const m=component.metrics||{},boxes=[];
  if(Number.isFinite(m.uptime_seconds))boxes.push(parityMetricBox('controller uptime',`${Math.floor(m.uptime_seconds/3600)}h ${Math.floor((m.uptime_seconds%3600)/60)}m`));
  if(Number.isFinite(m.filesystem_free_bytes))boxes.push(parityMetricBox('state filesystem free',parityFormatBytes(m.filesystem_free_bytes)));
  if(Number.isFinite(m.filesystem_free_percent))boxes.push(parityMetricBox('state filesystem free',parityFormatMetric(m.filesystem_free_percent,'percent')));
  if(Number.isFinite(m.database_bytes))boxes.push(parityMetricBox('controller database',parityFormatBytes(m.database_bytes)));
  if(Number.isFinite(m.wal_bytes))boxes.push(parityMetricBox('controller WAL',parityFormatBytes(m.wal_bytes)));
  if(Number.isFinite(m.process_rss_bytes))boxes.push(parityMetricBox('controller RSS',parityFormatBytes(m.process_rss_bytes)));
  return`<section class="detail-section parity-highlight"><h3>MonitorBox controller health</h3><p class="parity-detail-summary">${esc(component.summary||'Controller self-health status unavailable')}</p>${boxes.length?`<div class="metrics">${boxes.join('')}</div>`:''}</section>`;
}

function parityHostGlance(object){
  if(object.kind!=='host')return'';
  const m=parityAllMetrics(object),boxes=[];
  let cpu=parityFirstMetric(m,['cpu_pct','cpu_usage_percent','cpu_used_percent']);
  const idle=parityFirstMetric(m,['cpu_idle_percent']);
  if(!Number.isFinite(cpu)&&Number.isFinite(idle))cpu=Math.max(0,Math.min(100,100-idle));

  const totalBytes=parityFirstMetric(m,['memory_total_bytes','mem_total_bytes']);
  const totalKib=parityFirstMetric(m,['memory_total_kib','mem_total_kib']);
  const total=Number.isFinite(totalBytes)?totalBytes:Number.isFinite(totalKib)?totalKib*1024:null;
  const usedBytes=parityFirstMetric(m,['memory_used_bytes','mem_used_bytes']);
  const usedKib=parityFirstMetric(m,['memory_used_kib','mem_used_kib']);
  let used=Number.isFinite(usedBytes)?usedBytes:Number.isFinite(usedKib)?usedKib*1024:null;
  const availableBytes=parityFirstMetric(m,['memory_available_bytes','mem_available_bytes']);
  const availableKib=parityFirstMetric(m,['memory_available_kib','mem_available_kib']);
  const available=Number.isFinite(availableBytes)?availableBytes:Number.isFinite(availableKib)?availableKib*1024:null;
  if(!Number.isFinite(used)&&Number.isFinite(total)&&Number.isFinite(available))used=total-available;

  if(Number.isFinite(cpu))boxes.push(parityMetricBox('CPU used',parityFormatMetric(cpu,'percent')));
  if(Number.isFinite(total)&&Number.isFinite(used)&&total>0)boxes.push(parityMetricBox('RAM used',`${parityFormatMetric(used/total*100,'percent')} · ${parityFormatBytes(used)}`));
  const cpuTemp=parityFirstMetric(m,['cpu_temperature_celsius','cpu_temperature_c','temperature_c']);
  const systemTemp=parityFirstMetric(m,['system_temperature_celsius','system_temperature_c']);
  if(Number.isFinite(cpuTemp))boxes.push(parityMetricBox('CPU temperature',parityFormatMetric(cpuTemp,'temperature')));
  if(Number.isFinite(systemTemp)&&systemTemp!==cpuTemp)boxes.push(parityMetricBox('system temperature',parityFormatMetric(systemTemp,'temperature')));
  const speed=parityFirstMetric(m,['interface_speed_mbps','network_speed_mbps']);
  if(Number.isFinite(speed))boxes.push(parityMetricBox('link speed',parityFormatMetric(speed,'mbps')));
  return boxes.length?`<section class="detail-section"><h3>At a glance</h3><div class="metrics">${boxes.join('')}</div></section>`:'';
}
function parityStorageRows(object){
  if(object.kind!=='host')return'';
  const m=parityAllMetrics(object),rows=[];
  const labels=prefix=>({root:'System',containers:'Containers',plexdata:'PlexData'})[prefix.toLowerCase()]||prefix.replace(/[_-]+/g,' ').replace(/\b\w/g,ch=>ch.toUpperCase());
  for(const key of Object.keys(m)){
    const match=key.match(/^(.*)_total_units$/);if(!match)continue;
    const prefix=match[1],totalUnits=m[key],usedUnits=m[`${prefix}_used_units`],allocation=m[`${prefix}_allocation_bytes`];
    if(![totalUnits,usedUnits,allocation].every(Number.isFinite)||totalUnits<=0||allocation<=0)continue;
    const total=totalUnits*allocation,used=usedUnits*allocation,pct=Math.max(0,Math.min(100,used/total*100));
    rows.push(`<div class="parity-capacity"><span><b>${esc(labels(prefix))}</b><small>${Math.round(pct)}% · ${esc(parityFormatBytes(total-used))} free</small></span><i><b style="width:${pct}%"></b></i></div>`);
  }
  for(const key of Object.keys(m)){
    const match=key.match(/^(pool[_-]?\d+)_capacity_bytes$/i);if(!match)continue;
    const prefix=match[1],total=m[key],free=m[`${prefix}_free_bytes`];
    if(!Number.isFinite(total)||!Number.isFinite(free)||total<=0)continue;
    const used=Math.max(0,total-free),pct=Math.max(0,Math.min(100,used/total*100));
    rows.push(`<div class="parity-capacity"><span><b>${esc(labels(prefix))}</b><small>${Math.round(pct)}% · ${esc(parityFormatBytes(free))} free</small></span><i><b style="width:${pct}%"></b></i></div>`);
  }
  return rows.length?`<section class="detail-section"><h3>Storage</h3><div class="parity-capacity-list">${rows.join('')}</div></section>`:'';
}

function parityNetworkAggregate(site,object){
  if(object.id!=='network')return'';
  const children=(site.objects||[]).filter(item=>item.kind==='network_device'||item.kind==='remote_site')
    .sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
  const rows=children.map(child=>`<button class="component-row parity-nav-row" data-parity-site="${esc(site.id)}" data-parity-object="${esc(child.id)}" type="button"><span><strong>${esc(child.label)}</strong><small>${esc(child.summary||'Status unavailable')}</small></span>${pill(child.state)}</button>`).join('');
  return`<section class="detail-section"><h3>Infrastructure and required paths</h3><div class="component-list">${rows||'<div class="chart-empty">No network child objects are configured.</div>'}</div></section>`;
}
function parityNetworkDevice(object){
  if(object.kind!=='network_device'&&object.kind!=='remote_site')return'';
  const evidence=(object.components||[]).find(item=>item.adapter==='unifi-component')||(object.components||[]).find(item=>item.adapter==='unifi-vpn');
  if(!evidence)return'';
  const n=evidence.metadata||{},m=evidence.metrics||{},identity=[];
  if(n.model)identity.push(parityMetricBox('model',n.model));
  if(n.ip)identity.push(parityMetricBox('management IP',n.ip));
  if(n.version)identity.push(parityMetricBox('firmware',n.version));
  if(n.mac)identity.push(parityMetricBox('MAC',n.mac));
  if(Number.isFinite(n.temperature_c??m.temperature_c))identity.push(parityMetricBox('temperature',parityFormatMetric(Number(n.temperature_c??m.temperature_c),'temperature')));
  const speed=Number(n.uplink_speed_mbps??m.uplink_speed_mbps),expected=Number(n.expected_uplink_speed_mbps??m.expected_uplink_speed_mbps);
  const link=[];
  if(Number.isFinite(speed))link.push(parityMetricBox('negotiated uplink',parityFormatMetric(speed,'mbps')));
  if(Number.isFinite(expected))link.push(parityMetricBox('expected uplink',parityFormatMetric(expected,'mbps')));
  if(n.uplink_parent_name)link.push(parityMetricBox('uplink parent',n.uplink_parent_name));
  if(n.expectation_source)link.push(parityMetricBox('expectation source',String(n.expectation_source).replaceAll('_',' ')));
  if(Number.isFinite(n.uplink_error_delta))link.push(parityMetricBox('new physical errors',String(n.uplink_error_delta)));
  const radios=(n.radios||[]).map(radio=>`<div class="component-row"><strong>${esc(radio.name||radio.band||'Radio')}</strong><span>${esc(radio.configured_enabled===false?'Disabled':radio.operational?'Operational':'Not operational')}</span><p>${radio.channel!=null?`Channel ${esc(radio.channel)}`:'Channel unavailable'}${radio.band?` · ${esc(radio.band)}`:''}</p></div>`).join('');
  return`${identity.length?`<section class="detail-section"><h3>Device identity</h3><div class="metrics">${identity.join('')}</div></section>`:''}${link.length?`<section class="detail-section"><h3>Uplink</h3><div class="metrics">${link.join('')}</div></section>`:''}${radios?`<section class="detail-section"><h3>Radios</h3><div class="component-list">${radios}</div></section>`:''}`;
}

function parityUpsRows(site){
  return(site.objects||[]).filter(item=>item.kind==='ups').map(ups=>{
    const m=parityAllMetrics(ups),source=(ups.components||[]).map(c=>c.metadata?.power_source).find(Boolean)||'unknown';
    const detail=[
      Number.isFinite(m['battery.charge'])?`${Math.round(m['battery.charge'])}% charge`:null,
      Number.isFinite(m['battery.runtime'])?`${Math.round(m['battery.runtime']/60)} min runtime`:null,
      Number.isFinite(m['ups.load'])?`${Math.round(m['ups.load'])}% load`:null,
    ].filter(Boolean).join(' · ');
    return`<button class="component-row parity-nav-row" data-parity-site="${esc(site.id)}" data-parity-object="${esc(ups.id)}" type="button"><span><strong>${esc(ups.label)}</strong><small>${esc(detail||ups.summary||'UPS telemetry unavailable')}</small></span><b>${esc(source==='battery'?'Battery':source==='utility'?'Utility':'Unknown')}</b></button>`;
  }).join('');
}
function parityPowerAggregate(site,object){
  if(object.id!=='power')return'';
  const power=site.power||{},thresholds=power.protective_thresholds||{},thresholdRows=Object.entries(thresholds).map(([objectId,value])=>{
    const target=(site.objects||[]).find(item=>item.id===objectId),deadline=value?.deadline;
    return`<div class="component-row"><strong>${esc(target?.label||objectId)}</strong><span>${esc(value?.state==='threshold_reached'?'Threshold reached':'Scheduled')}</span><p>${deadline?`Deadline ${esc(new Date(deadline).toLocaleString())}`:'Deadline unavailable'}</p></div>`;
  }).join('');
  const outage=power.outage_started_at||power.primary_outage_started_at;
  return`<section class="detail-section"><h3>UPSes</h3><div class="component-list">${parityUpsRows(site)||'<div class="chart-empty">No UPS objects configured.</div>'}</div></section>${outage?`<section class="detail-section"><h3>Outage context</h3><div class="metrics">${parityMetricBox('outage started',new Date(outage).toLocaleString())}${parityMetricBox('elapsed',ageText(outage))}</div>${thresholdRows?`<div class="component-list" style="margin-top:.65rem">${thresholdRows}</div>`:''}</section>`:''}<section class="detail-section" id="parity-power-events"><h3>Recent power events · 72 hours</h3><div class="chart-empty">Loading power-event journal…</div></section>`;
}
async function parityLoadPowerEvents(siteId){
  const target=document.querySelector('#parity-power-events');if(!target)return;
  try{
    const payload=await api(`/api/v2/events?site_id=${encodeURIComponent(siteId)}&limit=250`),cutoff=Date.now()-72*3600*1000;
    const events=(payload.events||[]).filter(event=>POWER_EVENT_TYPES.has(String(event.event_type||event.type||''))&&new Date(event.occurred_at).getTime()>=cutoff);
    target.innerHTML=`<h3>Recent power events · 72 hours</h3><div class="component-list">${events.length?events.map(event=>`<div class="component-row"><strong>${esc(event.summary||event.event_type||'Power event')}</strong><span>${esc(ageText(event.occurred_at))}</span>${event.object_id?`<p>${esc(event.object_id)}</p>`:''}</div>`).join(''):'<div class="chart-empty">No recent power events.</div>'}</div>`;
  }catch(error){target.innerHTML=`<h3>Recent power events · 72 hours</h3><div class="chart-empty">Power-event journal unavailable: ${esc(error.message)}</div>`;}
}
function parityUpsIdentity(object){
  if(object.kind!=='ups')return'';
  const metadata=(object.components||[]).map(c=>c.metadata||{}).find(m=>m['ups.model']||m['ups.serial']||m['ups.status'])||{},m=parityAllMetrics(object),boxes=[];
  for(const [key,label] of [['ups.model','model'],['ups.serial','serial'],['ups.mfr','manufacturer'],['ups.status','status']])if(metadata[key])boxes.push(parityMetricBox(label,metadata[key]));
  for(const [key,label] of [['input.voltage','input voltage'],['output.voltage','output voltage'],['battery.voltage','battery voltage'],['ups.realpower','present watts']])if(Number.isFinite(m[key]))boxes.push(parityMetricBox(label,parityFormatMetric(m[key])));
  return boxes.length?`<section class="detail-section"><h3>UPS identity and electrical telemetry</h3><div class="metrics">${boxes.join('')}</div></section>`:'';
}

function parityCameraAggregate(site,object){
  if(object.id!=='cameras')return'';
  const cameras=(site.objects||[]).filter(item=>item.kind==='camera').sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
  const rows=cameras.map(camera=>`<button class="component-row parity-nav-row" data-parity-site="${esc(site.id)}" data-parity-object="${esc(camera.id)}" type="button"><span><strong>${esc(camera.label)}</strong><small>${esc(camera.summary||'Camera status unavailable')}</small></span>${pill(camera.state)}</button>`).join('');
  return`<section class="detail-section"><h3>Cameras</h3><div class="component-list">${rows||'<div class="chart-empty">No cameras configured.</div>'}</div></section>`;
}
function parityCameraIdentity(object){
  if(object.kind!=='camera')return'';
  const metadata=(object.components||[]).map(c=>c.metadata||{}).find(m=>m.camera_id||m.native_id||m.provider||m.profiles)||{},boxes=[];
  if(metadata.camera_id)boxes.push(parityMetricBox('Scrypted ID',metadata.camera_id));
  if(metadata.native_id)boxes.push(parityMetricBox('native ID',metadata.native_id));
  if(metadata.provider)boxes.push(parityMetricBox('provider',metadata.provider));
  if(metadata.selected_profile_id)boxes.push(parityMetricBox('selected profile',metadata.selected_profile_id));
  return boxes.length?`<section class="detail-section"><h3>Camera identity</h3><div class="metrics">${boxes.join('')}</div></section>`:'';
}

function paritySpecializedDetail(site,object){
  return[
    parityControllerHealth(object),
    parityHostGlance(object),
    parityStorageRows(object),
    parityNetworkAggregate(site,object),
    parityNetworkDevice(object),
    parityPowerAggregate(site,object),
    parityUpsIdentity(object),
    parityCameraAggregate(site,object),
    parityCameraIdentity(object),
  ].join('');
}

renderDrawer=function(){
  v1DetailBaseRenderDrawer();
  if(!app.selected||!app.state)return;
  const {site,object}=findObject(app.selected.siteId,app.selected.objectId);if(!site||!object)return;
  parityInsert(paritySpecializedDetail(site,object));
  parityBindObjectNavigation(document);
  if(object.id==='power')parityLoadPowerEvents(site.id);
};
