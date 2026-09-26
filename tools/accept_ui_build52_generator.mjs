#!/usr/bin/env node
// UI52 clean-card engine: no stored Broad Leaf featured rows, no v1 renderer.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {spawnSync} from 'node:child_process';
const asset=name=>fs.readFileSync(
  new URL('../sources/ui/1.16.0-build52/'+name,import.meta.url),'utf8');
for(const path of ['card-item-registry.js','card-generation.js','card-layout-policy.js'])
  vm.runInThisContext(asset(path),{filename:path});
const registry=globalThis.MonitorBoxCardItems,engine=globalThis.MonitorBoxCardGeneration,
  policy=globalThis.MonitorBoxCardPolicy;
const check=(id,metrics={})=>({id,label:id,state:'healthy',metrics});
const obj=(id,kind,extra={})=>({id,kind,label:extra.label||id,state:'healthy',
  homepage_origin:extra.homepage_origin||'discovered',
  ...extra,components:extra.components||[check(id+'-health')]});
const host=obj('a2','host',{homepage_origin:'operator',components:[
  check('hostcpu',{cpu_idle_percent:83,memory_total_kib:100,
    memory_available_kib:61})]});
const g=obj('g','host',{homepage_origin:'operator',components:[
  check('g-cpu',{cpu_idle_percent:97,memory_total_kib:100,
    memory_available_kib:59,pool_free_bytes:12345678})]});
const other=obj('unfeatured','host',{homepage_origin:'module',
  front_page:true,explicit_front_page:undefined});
const network=Array.from({length:12},(_,i)=>obj('switch'+i,'network_device',{
  label:'Switch '+String(i).padStart(2,'0'),
  components:[check('switch'+i,{})]}));
const ups=[obj('networkups','ups',{components:[check('nut-net',{
  'battery.charge':97,'battery.runtime':740,'ups.load':34,
  'input.voltage':120})]}),
  obj('serverups','ups',{components:[check('nut-server',{
  'battery.charge':98,'battery.runtime':650,'ups.load':20})]})];
const cameras=Array.from({length:8},(_,i)=>obj('cam'+i,'camera'));
const remote=obj('turnberry','remote_site',{front_page:true});
const site={id:'lab',label:'Arbitrary new site',objects:[
  host,g,other,...network,remote,...ups,...cameras],
  cards:['internet','network','cameras','power','zigbee'].map(f=>({
    id:f,family:f,kind:'dashboard_card',label:f,
    member_object_ids:f==='zigbee'?['switch7']:undefined,
    state:'healthy',summary:'Site health'}))};
const live=[
  {site_id:'lab',object_id:'a2',check_id:'hostcpu',
    id:'cpu_usage',label:'CPU utilization',kind:'gauge',unit:'%'},
  {site_id:'lab',object_id:'a2',check_id:'hostcpu',
    id:'memory_used',label:'Memory used bytes',kind:'gauge',unit:'B'},
  {site_id:'lab',object_id:'g',check_id:'g-cpu',
    id:'cpu_usage',label:'CPU utilization',kind:'gauge',unit:'%'},
  {site_id:'lab',object_id:'g',check_id:'g-cpu',
    id:'memory_used',label:'Memory used bytes',kind:'gauge',unit:'B'},
  {site_id:'lab',object_id:'a2',check_id:'hostcpu',id:'nic_rates',
    label:'Ethernet',kind:'counter_pair',unit:'bit/s'},
  {site_id:'lab',object_id:'switch0',check_id:'wan',
    id:'wan_rates',label:'WAN',kind:'counter_pair',unit:'bit/s',
    traffic_subject:'wan'},
];
registry.setLiveSeries({series:live});
const fresh=policy.defaults(site,site.objects);
const saved=JSON.parse(JSON.stringify(fresh));
const idList=fresh.map(r=>r.id);
assert.deepEqual(idList.slice(0,2),['host:a2','host:g']);
assert.equal(idList.includes('host:unfeatured'),false);
assert.equal(idList.includes('family:zigbee'),true);
const n=fresh.find(r=>r.id==='family:network');
assert.deepEqual(n.presentation.member_ids,network.map(o=>o.id));
assert.equal(n.presentation.member_ids.includes('turnberry'),false);
assert.equal(n.presentation.native_sections.join(','),'members');
const p=fresh.find(r=>r.id==='family:power');
assert.deepEqual(p.presentation.member_ids,['networkups','serverups']);
assert.equal(p.presentation.items.length,0);
const internet=fresh.find(r=>r.id==='family:internet');
assert.deepEqual(internet.presentation.native_sections,['diagnosis']);
assert.equal(internet.presentation.items.length,1);
assert.equal(JSON.parse(internet.presentation.items[0].key)[4],'wan_rates');
const camera=fresh.find(r=>r.id==='family:cameras');
assert.equal(camera.presentation.member_ids.length,8);
assert.deepEqual(camera.presentation.native_sections,['camera_counts','members']);
const a2=fresh.find(r=>r.id==='host:a2');
assert.deepEqual(a2.presentation.items.map(x=>JSON.parse(x.key)[2]),
  ['live','live','live']);
const gp=fresh.find(r=>r.id==='host:g');
assert.equal(gp.presentation.items.length,3);
assert.deepEqual(gp.presentation.items.map(x=>JSON.parse(x.key)[2]),
  ['live','live','metric']);
assert.equal(JSON.parse(gp.presentation.items[2].key)[4],'pool_free_bytes');

// The Python Core startup initializer and JS reset must serialize exactly
// the same normalized cards for identical *current* site and live metadata.
const bootstrapPython=String.raw`import sys,json,importlib.util
from pathlib import Path
payload=json.load(sys.stdin)
file=Path("sources/ui/1.16.0-build52/bootstrap.py")
spec=importlib.util.spec_from_file_location("ui52_bootstrap",file)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
site=payload["site"]
live=payload["live"]
app={"monitorbox.public_state_snapshot":lambda:{"sites":[site]},
     "monitorbox.ui_live_series_snapshot":lambda:live}
document={"sites":[{"id":site["id"]}]}
rows=module.generate(site,live)
entry=module.automatic_layout_snapshot(app,document,None)
old={"schema_version":4,"data":{"sites":{"lab":{
    "mode":"custom","cards":[{"id":"host:a2","visible":True}]}}}}
assert module.automatic_layout_snapshot(app,document,old) is old
print(json.dumps({"rows":rows,"initial":entry},separators=(",",":")))
`;
function comparePython(site,liveRows,jsCards,label){
  const run=spawnSync('python',['-c',bootstrapPython],{
    input:JSON.stringify({site,live:liveRows}),encoding:'utf8'
  });
  assert.equal(run.status,0,label+' Python startup error:\n'+run.stderr);
  const result=JSON.parse(run.stdout);
  assert.deepEqual(result.rows,JSON.parse(JSON.stringify(jsCards)),
    label+' JS/Python first-bootstrap versus Reset differ');
  assert.deepEqual(result.initial,{
    schema_version:5,data:{sites:{[site.id]:{
      mode:'auto',cards:JSON.parse(JSON.stringify(jsCards))
    }}}
  },label+' Core startup preference schema mismatch');
}
comparePython(site,live,fresh,'LIVE available at first readiness');
// Mutating the old v1 featured flags may NEVER change a generated card.
for(const o of network)o.components[0].metadata={front_page:false};
network[0].front_page=false;
remote.front_page=false;
const cleanReset=policy.defaults(site,site.objects);
comparePython(site,live,cleanReset,'v1 presentation hints changed');
assert.deepEqual(JSON.parse(JSON.stringify(cleanReset)),saved);
const freshEntry={schema_version:5,data:{sites:{lab:{
  mode:'auto',cards:JSON.parse(JSON.stringify(fresh))}}}};
policy.validate(freshEntry);
freshEntry.data.sites.lab.cards.find(r=>r.id==='family:network')
  .presentation.member_ids.pop();
assert.equal(policy.siteRows(freshEntry,site,site.objects)
  .find(r=>r.id==='family:network').presentation.member_ids.length,11);
assert.equal(policy.defaults(site,site.objects).find(r=>r.id==='family:network')
  .presentation.member_ids.length,12);
// Restored v4 bytes must remain read-only and must not adopt v5 native rows.
const legacy={schema_version:4,data:{sites:{lab:{mode:'auto',cards:[
  {id:'family:network',visible:true,presentation:{
    schema_version:2,items:[],hidden_member_ids:['switch1']}}
]}}}};
policy.validate(legacy);
assert.equal(policy.siteRows(legacy,site,site.objects)[0].presentation.schema_version,2);
registry.setLiveSeries({series:[]});
comparePython(site,[],policy.defaults(site,site.objects),
  'startup before ephemeral LIVE metadata is advertised');
console.log('UI52 clean generation: 12 local Network, 2 UPS, 8 cameras, WAN LIVE, 2 hosts LIVE, third-party family, v4 exact recovery and v5 reset parity PASS');
