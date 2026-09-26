#!/usr/bin/env node
// UI51 provider-neutral capability curation and read-only legacy snapshot gates.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const context={};
context.globalThis=context;
context.MonitorBoxCardItems={parseKey:key=>{
  try {const v=JSON.parse(key);return Array.isArray(v)&&v.length===5?v:null;}
  catch{return null;}
}};
vm.runInNewContext(fs.readFileSync(
  new URL('../sources/ui/1.15.0-build51/card-layout-policy.js',import.meta.url),'utf8'),
  context);
const p=context.MonitorBoxCardPolicy;
const host=(id,origin='operator',metrics={})=>({
  id,label:id,kind:'host',homepage_origin:origin,components:[
    {id:'host-check',label:'Host health',state:'healthy',metrics}]});
const normal={
  cpu_idle_percent:88,memory_total_kib:32768000,memory_available_kib:16384000,
  storage_used_percent:62,ethernet_utilization_percent:15,
  rx_bytes:999999,interface_speed_mbps:10000,network_health:1};
const explicit={
  ...normal,cpu_usage_percent:12,memory_used_percent:50};
const site={
  id:'lab',cards:['internet','network','cameras','power'].map(f=>({
    id:f,family:f,label:f,kind:'dashboard_card'}))};
const discovered=Array.from({length:30},(_,i)=>host('edge'+i,
  i%2?'discovered':'module',{cpu_usage_percent:95}));
const objects=[host('arr',{not:'relevant'}),host('arrrrr2','operator',normal),
  host('goliath','operator',explicit),host('empty','operator',{}),
  ...discovered,{id:'gateway',kind:'network_device',system_role:'site_gateway',
    homepage_origin:'discovered',label:'Router',components:[]}];
objects.shift();
const baseline=p.defaults(site,objects);
const ids=baseline.map(row=>row.id);
assert.deepEqual(ids,[
  'host:arrrrr2','host:goliath','host:empty','host:gateway',
  'family:internet','family:network','family:cameras','family:power']);
const a2=baseline[0].presentation.items;
assert.equal(a2.length,4);
assert.deepEqual(a2.map(item=>JSON.parse(item.key).at(-1)),[
  '@derived.cpu_used_percent','@derived.memory_used_percent',
  'storage_used_percent','ethernet_utilization_percent']);
assert.deepEqual(baseline[1].presentation.items.map(x=>JSON.parse(x.key).at(-1)),[
  'cpu_usage_percent','memory_used_percent','storage_used_percent',
  'ethernet_utilization_percent']);
assert.equal(baseline[2].presentation,undefined);
assert.equal(baseline[3].presentation,undefined);
assert.equal(p.defaults(site,objects).length,8);
assert.equal(JSON.stringify(p.defaults(site,objects)),JSON.stringify(baseline));
assert.equal(baseline.some(row=>row.id.startsWith('host:edge')),false);
// An absent numeric metric must not create a guessed reading. Byte counters
// and reported link speeds are NOT actual current NIC utilization.
const unknown=p.autoHostItems(host('no-guess','operator',{
  cpu_idle_percent:130,memory_total_kib:100,memory_available_kib:120,
  storage_used_percent:900,rx_bytes:99999,interface_speed_mbps:10000,
  network_health:1}));
assert.equal(unknown.length,0);
// Prior signed UI50 schema-4 auto layouts are protected against unattended
// upgrade/regeneration. Explicit operator Regenerate replaces them instead.
const prior={schema_version:4,data:{sites:{lab:{
  mode:'auto',cards:[{id:'host:arrrrr2',visible:true}]}}}};
assert.equal(p.siteRows(prior,site,objects)[0].presentation,undefined);
assert.equal(p.siteRows(prior,site,objects).length,1);
const fresh={schema_version:3,data:{sites:{lab:{
  mode:'auto',cards:[{id:'host:arrrrr2',visible:true}]}}}};
assert.equal(p.siteRows(fresh,site,objects).length,baseline.length);
assert.equal(p.siteRows(fresh,site,objects)[0].presentation.items.length,4);
const custom={schema_version:4,data:{sites:{lab:{
  mode:'custom',cards:[{id:'host:arrrrr2',visible:true,
    presentation:{schema_version:2,items:[],title:'Operator card'}}]}}}};
assert.equal(p.siteRows(custom,site,objects)[0].presentation.title,'Operator card');
console.log('UI51 observed CPU/memory/storage/NIC defaults, grouped discovery, bounded 4 rows, protected v4 snapshots PASS');
