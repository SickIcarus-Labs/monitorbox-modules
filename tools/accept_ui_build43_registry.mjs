#!/usr/bin/env node
// Pure public-projection contract: no provider or Core mutation, no browser.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const code=fs.readFileSync(new URL('../sources/ui/1.7.0-build43/card-item-registry.js',import.meta.url),'utf8');
const context=vm.createContext({});context.globalThis=context;
vm.runInContext(code,context);
const model=context.MonitorBoxCardItems;
const site={id:'broadleaf',objects:[
  {id:'a2',label:'Arrrrr2',kind:'host',state:'healthy',
    components:[{id:'host-cpu',label:'CPU',state:'healthy',metrics:{'cpu.usage':41,'cpu.temp':54},
      metric_units:{'cpu.usage':'%','cpu.temp':'°C'}},
      {id:'host-mem',label:'RAM',state:'healthy',metrics:{'memory.used_percent':62}}]},
  {id:'g',label:'Goliath',kind:'host',state:'healthy',
    components:[{id:'storage',label:'Pool',state:'healthy',metrics:{'pool.free_bytes':123456789}}]},
  {id:'aggregation',label:'Aggregation',kind:'network_device',state:'healthy',
    components:[{id:'snmp',label:'SNMP',state:'healthy',metrics:{'if.in_bps':9983}}]},
  {id:'ups1',label:'Rack UPS',kind:'ups',state:'degraded',
    components:[{id:'nut',label:'NUT',state:'degraded',metrics:{'battery.charge':85}}]},
  {id:'cam1',label:'Driveway',kind:'camera',state:'healthy',
    components:[{id:'scrypted',label:'Camera',state:'healthy',metrics:{}}]},
  {id:'monitor',label:'Monitor',kind:'appliance',state:'healthy',components:[]},
],cards:[
  {id:'internet',family:'internet',kind:'dashboard_card',label:'Internet',
    components:[{id:'wan-dns',owner_object_id:'monitor',state:'healthy',
      label:'Internet DNS',metrics:{'dns.latency_ms':32}}]},
]};
const before=JSON.stringify(site);
const catalog=model.catalog(site);
const names=catalog.groups.map(g=>g.id);
for(const group of ['hosts','network','power','cameras','internet'])
  assert(names.includes(group),group+': missing group');
const a2=catalog.groups.find(g=>g.id==='hosts').sources.find(s=>s.sourceId==='a2');
const cpu=a2.items.find(i=>i.metricKey==='cpu.usage');
assert(cpu&&cpu.type==='metric'&&cpu.unit==='%');
assert.equal(model.display(site,cpu.key,catalog.items).value,41);
const stateKey=model.makeKey('object','aggregation','status');
assert.equal(model.display(site,stateKey,catalog.items).state,'healthy');
const power=catalog.groups.find(g=>g.id==='power').sources[0];
const battery=power.items.find(i=>i.metricKey==='battery.charge');
assert.equal(model.display(site,battery.key,catalog.items).value,85);
const camera=catalog.groups.find(g=>g.id==='cameras').sources[0];
assert(camera.items.some(i=>i.type==='status'));
const internet=catalog.groups.find(g=>g.id==='internet').sources[0];
assert(internet.items.some(i=>i.metricKey==='dns.latency_ms'));
assert.equal(JSON.stringify(site),before,'Catalog building changed public health truth');
assert.equal(model.parseKey('garbage'),null);
assert.equal(model.parseKey('["object","a2","status"]'),null);
const missing=JSON.parse(JSON.stringify(site));
missing.objects=missing.objects.filter(o=>o.id!=='ups1');
const lost=model.display(missing,battery.key);
assert.equal(lost.available,false);
assert.equal(lost.state,'unknown');
const stale={...site,objects:site.objects.map(o=>o.id==='a2'?
  {...o,components:o.components.filter(c=>c.id!=='host-cpu')}:o)};
const absent=model.display(stale,cpu.key);
assert.equal(absent.available,false);
assert.equal(absent.state,'unknown');
assert.equal(catalog.items.size,new Set(catalog.items.keys()).size);
console.log('UI43 public registry: grouped host CPU/RAM/storage, network, camera, NUT, Internet, dedup, unavailable, immutable source: PASS');
