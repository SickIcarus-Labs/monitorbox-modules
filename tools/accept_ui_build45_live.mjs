#!/usr/bin/env node
// UI45 #94: live public telemetry and inline renderer remain display-only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const base=new URL('../sources/ui/1.9.0-build45/',import.meta.url);
const registryCode=fs.readFileSync(new URL('card-item-registry.js',base),'utf8');
const renderCode=fs.readFileSync(new URL('card-composer-renderer.js',base),'utf8');
const stamp=()=>new Date().toISOString();
const components=[
  {id:'host-cpu',label:'Arrrrr2 CPU and memory',state:'healthy',
    metrics:{'cpu system percent':1,'cpu idle percent':93,
      'memory available kib':55322832,'memory total kib':65322832}},
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
assert.match(expired.unavailableReason,/delayed/);
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
  openDrawer:(s,o)=>{opened=s+'/'+o;},setInterval:(fn,ms)=>{interval={fn,ms};},
  parityCoreMarkup:()=>'',parityCoreObjects:s=>s.objects});
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

const cpuDerived=model.makeKey('object','a2','metric','host-cpu','@derived.cpu_used_percent');
const memDerived=model.makeKey('object','a2','metric','host-cpu','@derived.memory_used_percent');
const derivedCPU=model.display(site,cpuDerived);
const derivedRAM=model.display(site,memDerived);
assert.equal(derivedCPU.value,7,'CPU utilisation = 100 - observed idle');
assert(Math.abs(derivedRAM.value-15.31)<.02,'RAM = (total - available) / total');
const delayed=new Date(Date.now()-12000).toISOString();
model.setLiveSeries({series:[
  {...metrics[0],points:[{timestamp:delayed,valid:true,value:32}]},
  {...metrics[1],points:[{timestamp:delayed,valid:true,value:23}]},
  net(4e9,5e8),
]});
const cpuFallback=model.display(site,cpuKey);
assert(cpuFallback.fallback&&cpuFallback.available);
assert.equal(cpuFallback.value,7);
assert.equal(cpuFallback.freshness,'state');
const memoryFallback=model.display(site,memKey);
assert(memoryFallback.fallback&&memoryFallback.available);
assert(Math.abs(memoryFallback.value-15.31)<.02);
assert.match(context.MonitorBoxCardComposer.reading(cpuFallback).detail,/state/);
const freshState=structuredClone(site);
freshState.objects.find(o=>o.id==='a2').components
  .find(c=>c.id==='host-cpu').metrics={};
assert.equal(model.display(freshState,cpuKey).available,false,
  'Never fabricate a 1 Hz CPU value from unrelated health state');
// Actual observed interface telemetry uses a metric key with spaces.
// A unique matching NIC series must resolve its real line speed.
const screenshot=structuredClone(site);
screenshot.objects.find(o=>o.id==='a2').components
  .find(c=>c.id==='host-eth').metrics={'enp51s0 speed mbps':10000};
model.setLiveSeries({series:[net(1.4e9,2.9e8,2e9)]});
const speed=model.display(screenshot,ethKey);
assert(Math.abs(speed.value-14)<1e-9,'NIC utilization is 14% of 10 Gb/s');
assert.equal(speed.basis,'link');
assert.equal(speed.maximum,1e10);
const found=context.MonitorBoxCardComposer.reading(speed);
assert.match(found.detail,/reported link speed/);
// Twenty-four independently selected readings must not force empty
// neighboring host/Internet cards to the height of Arrrrr2.
const longSite=structuredClone(site);
const extended=longSite.objects.find(o=>o.id==='a2');
for(let n=1;n<=24;n++)extended.components[0].metrics['diagnostic '+n]=n;
longSite.objects.push(
  {id:'goliath',label:'Goliath',kind:'host',state:'healthy',components:[]},
  {id:'internet',label:'Internet',kind:'dashboard_card',
    family:'internet',state:'healthy',components:[]},
  {id:'network',label:'Network',kind:'dashboard_card',
    family:'network',state:'healthy',components:[]},
  {id:'cameras',label:'Cameras',kind:'dashboard_card',
    family:'cameras',state:'healthy',components:[]},
  {id:'power',label:'Power',kind:'dashboard_card',
    family:'power',state:'healthy',components:[]},
);
const longItems=Object.keys(extended.components[0].metrics).filter(x=>
  x.startsWith('diagnostic ')).map(metric=>({key:model.makeKey(
  'object','a2','metric','host-cpu',metric),mode:'list'}));
context.MonitorBoxCardLayout.displayFor=(_site,key)=>key==='host:a2'
  ?{items:longItems}:null;
app.state.sites=[longSite];
const masonry=context.parityCoreMarkup();
assert.equal((masonry.match(/class="mb-card-column"/g)||[]).length,3);
const column2=masonry.match(/data-mb-column="1">([\s\S]*?)<\/div>/);
assert(column2&&column2[1].includes('Goliath')&&column2[1].includes('Network'),
  'Neighboring cards remain in the independent second column');
assert(masonry.includes('mb-masonry-site'));
const css=fs.readFileSync(new URL('card-composer.css',base),'utf8');
assert(css.includes('align-items:start')&&css.includes('.mb-card-columns'));
assert.equal(JSON.stringify(site),before,'Telemetry changes cannot mutate source monitoring');

console.log('UI45: site-scoped 1 Hz gauge/rate, link-vs-scale basis, network status migration, fresh/stale/missing and inline rendering: PASS');
