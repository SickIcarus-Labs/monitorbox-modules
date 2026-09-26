#!/usr/bin/env node
'use strict';
// Synthetic, deterministic migration/packing tests. No appliance/API access.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const root=require('node:path').resolve(__dirname,'../sources/ui/1.13.0-build49');
const site={id:'home',objects:[
  {id:'a2',label:'Arrrrr2',kind:'host',homepage_origin:'operator'},
  {id:'g',label:'Goliath',kind:'host',homepage_origin:'operator'},
],cards:[
  {id:'network',kind:'dashboard_card',family:'network',label:'Network'},
  {id:'power',kind:'dashboard_card',family:'power',label:'Power'},
  {id:'cameras',kind:'dashboard_card',family:'cameras',label:'Cameras'},
]};
const registry={parseKey(key){try{const parsed=JSON.parse(key);
  return Array.isArray(parsed)?parsed:null;}catch{return null;}},setLiveSeries(){}};
const sandbox={MonitorBoxCardItems:registry,console,document:{
  hidden:false,addEventListener(){},querySelectorAll(){return [];}},setInterval(){},
  window:{matchMedia() {return {matches:false};},addEventListener(){}},
  app:{state:{sites:[site]},liveTelemetry:{series:[]}},
  esc(s){return String(s);},
  openDrawer(){},
  parityCoreCard(_s,o){return '<button class="parity-card">'+o.label+'</button>';},
  parityCoreObjects(s){return s.objects;},parityCoreMarkup(){return '';},
};
sandbox.globalThis=sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(root+'/card-layout-policy.js','utf8'),sandbox);
const policy=sandbox.MonitorBoxCardPolicy;
function rows(){
  return ['host:a2','host:g','family:network','family:cameras','family:power']
    .map(id=>({id,visible:true}));
}
function entry(v,cards=rows(),siteExtra={}){
  return {schema_version:v,data:{sites:{home:{mode:'custom',cards,...siteExtra}}}};
}
for(const version of [1,2,3])assert.equal(policy.validate(entry(version)).schema_version,version);
assert.throws(()=>policy.validate(entry(5)),/Unsupported/);
assert.throws(()=>policy.validate(entry(3,rows().map(row=>({...row,
  placement:{column:0}})))),/placement/);
const legacy=entry(3);
const unchanged=JSON.stringify(legacy);
policy.siteRows(legacy,site,site.objects);
assert.equal(JSON.stringify(legacy),unchanged,'legacy reads never migrate');
const placed=rows().map((row,i)=>({...row,placement:{column:i%3}}));
const spatial=entry(4,placed,{arranged:true});
assert.equal(policy.validate(spatial),spatial);
for(const bad of [-1,3,0.5,NaN]){
  const clone=structuredClone(spatial);
  clone.data.sites.home.cards[0].placement.column=bad;
  assert.throws(()=>policy.validate(clone),/placement/);
}
const missing=structuredClone(spatial);
delete missing.data.sites.home.cards[0].placement;
assert.throws(()=>policy.validate(missing),/missing its placement/);
const hide=structuredClone(spatial);
hide.data.sites.home.cards.find(r=>r.id==='host:a2').visible=false;
assert.equal(policy.visible(site,site.objects,hide).length,4,
  'hidden cards never disable or delete underlying monitored sources');
const ordered=[
  {id:'host:a2',column:0,object:{id:'a2',label:'Arrrrr2',kind:'host'}},
  {id:'family:cameras',column:2,object:{id:'cameras',label:'Cameras',kind:'dashboard_card'}},
  {id:'family:power',column:0,object:{id:'power',label:'Power',kind:'dashboard_card'}},
  {id:'host:g',column:1,object:{id:'g',label:'Goliath',kind:'host'}},
];
let width=1300,active=ordered;
sandbox.window.matchMedia=query=>({matches:query.includes('650')?width<=650:width<=980});
sandbox.MonitorBoxCardLayout={
  displayFor(){return null;},
  spatialFor(){return active;},
  refreshGrid(){},
};
vm.runInContext(fs.readFileSync(root+'/card-composer-renderer.js','utf8'),sandbox);
function columns(){
  const markup=sandbox.parityCoreMarkup();
  return [...markup.matchAll(/data-mb-column="(\d+)">([\s\S]*?)<\/div>/g)]
    .map(hit=>({column:Number(hit[1]),labels:
      [...hit[2].matchAll(/class="parity-card">([^<]+)/g)].map(m=>m[1])}));
}
assert.deepEqual(columns(),[
  {column:0,labels:['Arrrrr2','Power']},
  {column:1,labels:['Goliath']},
  {column:2,labels:['Cameras']},
],'one spatial move can put Power under Arrrrr2');
width=820;
assert.deepEqual(columns(),[
  {column:0,labels:['Arrrrr2','Power']},
  {column:1,labels:['Goliath','Cameras']},
], 'portrait merges middle/right deterministically');
width=500;
assert.deepEqual(columns(),[
  {column:0,labels:['Arrrrr2','Power','Goliath','Cameras']},
], 'narrow screens have stable lane-major focus/reading order');
width=1300;
active=ordered.map(row=>({...row})); // twenty-four metric rows grow Arrrrr2 only.
active[0].object={...active[0].object,presentation:{items:Array(24).fill({})}};
assert.deepEqual(columns()[0].labels,['Arrrrr2','Power'],
  'height changes never reshuffle an intentionally arranged card');
console.log('UI49: v1/v2/v3 migration, strict v4, visibility, and responsive 3/2/1 packing PASS');
