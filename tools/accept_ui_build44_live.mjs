#!/usr/bin/env node
// UI44 #94: live public telemetry and inline renderer remain display-only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const base=new URL('../sources/ui/1.8.0-build44/',import.meta.url);
const registryCode=fs.readFileSync(new URL('card-item-registry.js',base),'utf8');
const renderCode=fs.readFileSync(new URL('card-composer-renderer.js',base),'utf8');
const stamp=()=>new Date().toISOString();
const components=[
  {id:'host-cpu',label:'Arrrrr2 CPU and memory',state:'healthy',
    metrics:{'cpu system percent':1,'memory available kib':55322832}},
  {id:'host-eth',label:'Arrrrr2 Ethernet statistics',state:'healthy',
    metrics:{'link_speed_mbps':10000}},
];
const site={id:'home',objects:[
  {id:'a2',label:'Arrrrr2',kind:'host',state:'healthy',components},
  {id:'ups',label:'UPS',kind:'ups',state:'degraded',components:[]},
],cards:[]};
const gauge=(id,value,unit,check_id='host-cpu')=>({
  id,site_id:'home',object_id:'a2',check_id,kind:'gauge',
  label:id,unit,maximum:100,
  points:[{timestamp:stamp(),valid:true,value}],
});
const net=(rx,tx,maximum=2e9)=>({
  id:'enp51s0',site_id:'home',object_id:'a2',check_id:'host-eth',
  kind:'counter_pair',label:'Ethernet enp51s0',unit:'bit/s',maximum,
  points:[{timestamp:stamp(),valid:true,rx,tx}],
});
const metrics=[gauge('CPU',49.2,'%'),gauge('Memory used',33,'%'),net(2e9,3e8)];
const context=vm.createContext({Date,Intl,Number,Math,JSON,Object,Array,Map,Set,
  String,console});
context.globalThis=context;
vm.runInContext(registryCode,context);
const model=context.MonitorBoxCardItems;
const before=JSON.stringify(site);
assert.equal(model.catalog(site).groups.find(g=>g.id==='hosts').sources[0]
  .items.some(x=>x.type==='live'),false);
model.setLiveSeries({series:metrics});
const catalog=model.catalog(site);
const rows=catalog.groups.find(g=>g.id==='hosts').sources[0].items;
const liveKeys=rows.filter(x=>x.type==='live');
assert.equal(liveKeys.length,3);
const cpuKey=model.makeKey('object','a2','live','host-cpu','CPU');
const memKey=model.makeKey('object','a2','live','host-cpu','Memory used');
const ethKey=model.makeKey('object','a2','live','host-eth','enp51s0');
assert.equal(model.parseKey(ethKey)[2],'live');
assert.equal(model.display(site,cpuKey,catalog.items).value,49.2);
assert.equal(model.display(site,memKey,catalog.items).unit,'%');
const ethernet=model.display(site,ethKey,catalog.items);
assert.equal(ethernet.value,20,'Reported 10 Gb/s NIC speed overrides 2 Gb/s graph ceiling');
assert.equal(ethernet.basis,'link');
assert.equal(ethernet.rx,2e9);
assert.equal(ethernet.tx,3e8);
const oldCheck=model.makeKey('object','a2','check','host-eth','');
assert.equal(model.display(site,oldCheck,catalog.items).value,20,
  'An existing Ethernet-status selection upgrades only with one exact counter series');
const cpuStatic=rows.find(x=>x.type==='metric'&&x.metricKey==='cpu system percent');
const memStatic=rows.find(x=>x.type==='metric'&&x.metricKey==='memory available kib');
assert.equal(cpuStatic.unit,'%');
assert.equal(memStatic.unit,'KiB');
assert.equal(model.display(site,cpuStatic.key,catalog.items).value,1);
assert.equal(JSON.stringify(site),before,'Live overlays cannot mutate canonical site state');

model.setLiveSeries({series:[metrics[0],metrics[1],net(2e9,3e8)]});
const noNic=structuredClone(site);
delete noNic.objects[0].components[1].metrics.link_speed_mbps;
const fallback=model.display(noNic,ethKey);
assert.equal(fallback.value,100);
assert.equal(fallback.basis,'configured',
  'A chart maximum may provide a labeled percentage but is not reported link speed');
model.setLiveSeries({series:[metrics[0],metrics[1],net(2e9,3e8,null)]});
const noCapacity=model.display(noNic,ethKey);
assert.equal(noCapacity.value,null);
assert.equal(noCapacity.maximum,null);
assert.equal(noCapacity.available,true,'Rates remain available even without link capacity');
const otherSite=structuredClone(site);otherSite.id='remote';
assert.equal(model.display(otherSite,ethKey).available,false,'Never mix site telemetry');
const stale={...net(2e9,3e8),points:[{
  timestamp:new Date(Date.now()-11000).toISOString(),valid:true,rx:2e9,tx:3e8,
}]};
model.setLiveSeries({series:[stale]});
const expired=model.display(site,ethKey);
assert.equal(expired.available,false);
assert.equal(expired.state,'unknown');
assert.match(expired.unavailableReason,/stale/);
assert.equal(model.display(site,oldCheck).available,false,
  'An observed but stale traffic series cannot appear healthy');
model.setLiveSeries({series:[{...net(2e9,3e8),points:[{
  timestamp:stamp(),valid:false,rx:2e9,tx:3e8,
}]}]});
assert.equal(model.display(site,ethKey).available,false);
model.setLiveSeries({series:[net(2e9,3e8),{
  ...net(12e6,8e6),id:'enp177s0',
}]});
assert.equal(model.display(site,oldCheck).type,'check',
  'Never silently choose one interface when exact check has multiple series');

model.setLiveSeries({series:metrics});
let interval=null,opened=null;
const safe=value=>String(value).replace(/&/g,'&amp;')
  .replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const originalCard=(s,o)=>'<button class="parity-card" data-object="'+safe(o.id)+'">'+safe(o.label)+'</button>';
const app={state:{sites:[site]},liveTelemetry:{series:metrics}};
const doc={hidden:false,addEventListener(){},querySelectorAll(){return [];}};
Object.assign(context,{app,document:doc,esc:safe,parityCoreCard:originalCard,
  openDrawer:(s,o)=>{opened=s+'/'+o;},setInterval:(fn,ms)=>{interval={fn,ms};}});
context.MonitorBoxCardLayout={displayFor:(_site,key)=>key==='host:a2'
  ?{items:[{key:cpuKey,mode:'value'},{key:memKey,mode:'list'},
      {key:ethKey,mode:'tile'},{key:oldCheck,mode:'list'}]}:null};
vm.runInContext(renderCode,context);
const html=context.parityCoreCard(site,site.objects[0]);
assert(html.includes('mb-card-shell')&&html.includes('mb-card-native'));
assert(!html.includes('mb-card-items"><button'), 'No second-level tile grid');
assert.equal((html.match(/class="parity-card"/g)||[]).length,1,
  'The accepted canonical card must appear exactly once');
assert(html.includes('49.2%')&&html.includes('33%'));
assert(html.includes('20%')&&html.includes('↓ 2 Gbit/s'));
assert(html.includes('of reported link speed'));
assert(!html.includes('Arrrrr2 Arrrrr2'));
assert(interval&&interval.ms===1000,
  'Selected readings must repaint at the same 1 Hz cadence as live graphs');
const fmt=context.MonitorBoxCardComposer.quantity;
assert.equal(fmt(55322832,'KiB'),'52.8 GiB');
assert.equal(fmt(120000000,'bit/s'),'120 Mbit/s');
assert.equal(context.MonitorBoxCardComposer.reading(noCapacity).meta,'LIVE');
model.setLiveSeries({series:[]});
assert.equal(model.display(site,ethKey).available,false,
  'A missing previously selected series must fail closed');
console.log('UI44: site-scoped 1 Hz gauge/rate, link-vs-scale basis, network status migration, fresh/stale/missing and inline rendering: PASS');
