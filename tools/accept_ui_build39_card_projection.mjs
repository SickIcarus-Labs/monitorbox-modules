#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const broadleaf = {
  id:'broadleaf',
  objects:[
    {id:'monitor',label:'MonitorBox',kind:'host',front_page:true,state:'healthy'},
    {id:'arrrrr2',label:'Arrrrr2',kind:'host',state:'healthy'},
    {id:'goliath',label:'Goliath',kind:'host',state:'healthy'},
    {id:'switch-a',label:'Switch',kind:'network_device',state:'healthy'},
    {id:'portainer',label:'Workload inventory',kind:'integration',state:'healthy'},
    {id:'network',label:'Historical aggregate',kind:'integration',state:'healthy'},
  ],
  cards:[
    {id:'internet',family:'internet',kind:'dashboard_card',state:'healthy'},
    {id:'network',family:'network',kind:'dashboard_card',state:'unknown',
     summary:'Configured monitoring source unavailable'},
    {id:'cameras',family:'cameras',kind:'dashboard_card',state:'healthy'},
    {id:'power',family:'power',kind:'dashboard_card',state:'healthy'},
    {id:'services',family:'services',kind:'dashboard_card',state:'healthy'},
  ],
};

const calls={bind:0,overview:0};
const grid={innerHTML:''};
const context={
  console,
  app:{state:{sites:[broadleaf]}},
  parityObjects:site=>site?.objects??[],
  parityCoreObjects:site=>site?.objects??[],
  parityCoreMarkup:()=>'<article id="projected-card">Projected</article>',
  findObject:(siteId,objectId)=>{
    const site=siteId===broadleaf.id?broadleaf:undefined;
    return {site,object:site?.objects.find(item=>item.id===objectId)};
  },
  renderActions:(_site,object)=>`actions:${object.id}`,
  renderLiveOverview:()=>{calls.overview++;},
  bindCards:()=>{calls.bind++;},
  document:{querySelector:selector=>selector==='#core-grid'?grid:null},
};
context.globalThis=context;

const source=fs.readFileSync(
  new URL('../sources/ui/1.4.0-build39/card-projection.js',import.meta.url),
  'utf8',
);
vm.runInNewContext(source,context,{filename:'card-projection.js'});
const ui=context.MonitorBoxCardProjection;
assert.ok(ui);

assert.deepEqual(
  Array.from(ui.projectedCoreObjects(broadleaf),item=>item.id),
  ['arrrrr2','goliath','internet','network','cameras','power'],
);
assert.equal(ui.projectedCards(broadleaf).find(item=>item.id==='network').state,'unknown');
assert.equal(ui.projectedHosts(broadleaf).length,2);
assert.equal(context.findObject('broadleaf','network').object.kind,'dashboard_card',
  'projected family must override historical same-ID canonical owner');
assert.equal(context.findObject('broadleaf','arrrrr2').object.kind,'host');
assert.equal(context.renderActions(broadleaf,context.findObject('broadleaf','network').object),'');
assert.equal(context.renderActions(broadleaf,broadleaf.objects[1]),'actions:arrrrr2');

context.renderLiveOverview();
assert.equal(calls.overview,1);
assert.equal(calls.bind,1);
assert.match(grid.innerHTML,/projected-card/);

const minimal={
  id:'blank',objects:[],
  cards:[{id:'internet',family:'internet',kind:'dashboard_card',state:'unknown'}],
};
assert.deepEqual(Array.from(ui.projectedCoreObjects(minimal),x=>x.id),['internet']);

const custom={...minimal,cards:[
  {id:'z_extra',family:'z_extra',kind:'dashboard_card'},
  {id:'internet',family:'internet',kind:'dashboard_card'},
  {id:'a_extra',family:'a_extra',kind:'dashboard_card'},
  {id:'services',family:'services',kind:'dashboard_card'},
]};
assert.deepEqual(
  Array.from(ui.projectedCoreObjects(custom),x=>x.id),
  ['internet','a_extra','z_extra'],
);
assert.ok(!source.includes('card_layout'),'#219 UI composition is not part of this slice');
assert.ok(!source.includes('dashboardConfiguration'));
for(const provider of ['unifi','scrypted','portainer','nut','docker']){
  assert.ok(!source.toLowerCase().includes(provider),`provider coupling: ${provider}`);
}
console.log('UI build39 projected-card behavior: PASS');
