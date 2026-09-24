#!/usr/bin/env node
// UI41 policy & real UI40-overlay integration, including a mixed-kind 30-node
// discovery storm and snapshot/future-schema safety.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const source=read('sources/ui/1.5.0-build41/card-layout-policy.js');
const overlay=read('sources/ui/1.5.0-build41/card-layout.js');
const predecessor=read('sources/ui/1.4.1-build40/card-projection.js');
const devices=Array.from({length:30},(_,i)=>({
  id:'edge-'+String(i+1).padStart(2,'0'),
  label:i%2?'Synthetic AP '+i:'Synthetic switch '+i,
  kind:i%3?'host':'network_device',
  homepage_origin:i%2?'module':'discovered',
  front_page:true, // deliberately false-positive legacy signal
  state:'healthy',
}));
const home={
  id:'broadleaf',
  objects:[
    {id:'monitor',kind:'host',homepage_origin:'operator'},
    {id:'arrrrr2',label:'Arrrrr2',kind:'host',homepage_origin:'operator'},
    {id:'goliath',label:'Goliath',kind:'host',homepage_origin:'operator',front_page:true},
    {id:'wan-router',label:'WAN router',kind:'network_device',
      homepage_origin:'discovered',system_role:'site_gateway',
      front_page:false}, // derived suppression by a historical Network aggregate
    {id:'no-tile',kind:'host',homepage_origin:'operator',explicit_front_page:false},
    {id:'legacy-derived-hidden',kind:'host',homepage_origin:'operator',front_page:false},
    {id:'not-explicit',kind:'host',homepage_origin:'module',front_page:true},
    ...devices,
  ],
  cards:['internet','network','cameras','power','services','solar','zigbee'].map(family=>({
    id:family,kind:'dashboard_card',family,label:family,state:'unknown',
  })),
};
const status={textContent:'',hidden:true};
const grid={innerHTML:'',parentElement:{insertBefore(){}}};
const selectors={'#core-grid':grid,'#card-layout-status':status,'#card-layout-edit':{}};
let preferences=null,serverError=null,fetchCount=0,bound=0,overview=0;
const context={
  console,
  app:{state:{sites:[home]}},
  parityObjects:site=>site.objects||[],
  parityCoreObjects:site=>site.objects||[],
  parityCoreMarkup:()=>context.parityCoreObjects(home).map(row=>row.id).join(','),
  findObject:(siteId,objectId)=>({
    site:home,object:home.objects.find(item=>item.id===objectId),
  }),
  renderActions:(_site,object)=>object?.id||'',
  renderLiveOverview:()=>{overview++;},
  bindCards:()=>{bound++;},
  document:{
    querySelector:selector=>selectors[selector]??null,
    addEventListener(){},
    hidden:false,
  },
  fetch:async()=>{
    fetchCount++;
    return serverError
      ?{ok:false,status:503}
      :{ok:true,json:async()=>({configured:true,ui_preferences:preferences})};
  },
};
context.globalThis=context;
vm.runInNewContext(source,context,{filename:'card-layout-policy.js'});
const policy=context.MonitorBoxCardPolicy;
assert.ok(policy);
const available=policy.availableEntries(home,home.objects);
const defaults=policy.defaults(home,home.objects);
assert.equal(available.filter(item=>item.kind==='host').length,36);
assert.deepEqual(Array.from(defaults,row=>row.id),[
  'host:arrrrr2','host:goliath','host:wan-router','host:legacy-derived-hidden',
  'family:internet','family:network','family:cameras','family:power',
  'family:solar','family:zigbee',
]);
assert.equal(defaults.some(row=>row.id.startsWith('host:edge-')),false);
assert.equal(defaults.some(row=>row.id==='family:services'),false);
for(const node of devices)assert.equal(policy.eligibleHost(node),false,node.id);

const exact={
  schema_version:1,data:{sites:{broadleaf:{mode:'custom',cards:[
    {id:'family:network',visible:true},
    {id:'host:edge-01',visible:true},
    {id:'host:arrrrr2',visible:false},
    {id:'family:solar',visible:true},
  ]}}},
};
assert.deepEqual(Array.from(policy.visible(home,home.objects,exact),row=>row.id),[
  'family:network','host:edge-01','family:solar',
]);
const newlyAvailable={...home,cards:[
  ...home.cards,{kind:'dashboard_card',family:'battery',id:'battery',label:'Battery'},
]};
assert.deepEqual(Array.from(policy.visible(newlyAvailable,newlyAvailable.objects,exact),r=>r.id),[
  'family:network','host:edge-01','family:solar',
]);
assert.ok(policy.availableEntries(newlyAvailable,newlyAvailable.objects)
  .some(row=>row.id==='family:battery'));
assert.ok(policy.defaults(newlyAvailable,newlyAvailable.objects)
  .some(row=>row.id==='family:battery'));
assert.throws(()=>policy.validate({schema_version:2,data:{sites:{}}}),/Unsupported/);
assert.throws(()=>policy.validate({schema_version:1,data:{
  sites:{broadleaf:{mode:'custom',cards:[
    {id:'family:internet',visible:true},{id:'family:internet',visible:true},
  ]}},
}}),/duplicate/);

vm.runInNewContext(predecessor,context,{filename:'card-projection.js'});
vm.runInNewContext(overlay,context,{filename:'card-layout.js'});
const ui=context.MonitorBoxCardLayout;
assert.ok(ui);
assert.equal(context.parityCoreObjects(home).length,0,
  'must not show a fabricated homepage before reading the saved layout');
await ui.load();
assert.deepEqual(Array.from(ui.project(home),row=>row.id),[
  'arrrrr2','goliath','wan-router','legacy-derived-hidden',
  'internet','network','cameras','power',
  'solar','zigbee',
]);
assert.ok(grid.innerHTML.includes('arrrrr2'));
assert.ok(bound>0);
context.renderLiveOverview();
assert.equal(overview,1);
assert.ok(grid.innerHTML.includes('network'));

preferences=exact;
await ui.load();
assert.deepEqual(Array.from(ui.project(home),row=>row.id),['network','edge-01','solar']);
assert.ok(!grid.innerHTML.includes('goliath'));
serverError=true;
await ui.load();
assert.deepEqual(Array.from(ui.project(home),row=>row.id),['network','edge-01','solar'],
  'transient transport loss retains the last verified preference');
assert.ok(status.textContent.includes('503'));
serverError=false;
preferences={schema_version:2,data:{sites:{broadleaf:{mode:'custom',cards:[]}}}};
await ui.load();
assert.equal(ui.state().blocked,true);
assert.equal(ui.project(home).length,0,
  'unknown future schema must not silently reinterpret old saved layout');
assert.ok(status.textContent.includes('Unsupported'));
preferences=exact;
await ui.load();
assert.equal(ui.state().blocked,false);
assert.deepEqual(Array.from(ui.project(home),row=>row.id),['network','edge-01','solar']);
assert.ok(fetchCount>=5);
for(const token of ['unifi','scrypted','portainer','meraki','eero']){
  assert.ok(!source.toLowerCase().includes(token),token+' coupled into shared policy');
  assert.ok(!overlay.toLowerCase().includes(token),token+' coupled into render policy');
}
console.log('UI41 mixed-kind 30-device policy, snapshot and UI40-overlay acceptance: PASS');
