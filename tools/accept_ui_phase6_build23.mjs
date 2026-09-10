#!/usr/bin/env node
'use strict';
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import path from 'node:path';

const root=path.resolve(path.dirname(new URL(import.meta.url).pathname),'..');
const phase6=fs.readFileSync(path.join(root,'sources/ui/1.1.13-build23/phase6-convergence.js'),'utf8');
const physical=fs.readFileSync(path.join(root,'sources/ui/1.1.13-build23/phase6-physical-convergence.js'),'utf8');
const builder=fs.readFileSync(path.join(root,'tools/build_first_party_ui_build23.py'),'utf8');
const stager=fs.readFileSync(path.join(root,'tools/stage_phase6_ui_build23.py'),'utf8');

const context={console,Map,Set,URL,queueMicrotask,setTimeout,clearTimeout};
context.globalThis=context;
context.working={sites:[{id:'broadleaf',objects:[
  {id:'monitor',label:'MonitorBox',kind:'appliance',address:'192.168.3.5'},
  {id:'arrrrr2',label:'Arrrrr2',kind:'host',address:'192.168.3.9'},
  {id:'network_ups',label:'Network UPS',kind:'ups'},
  {id:'server_ups',label:'Server UPS',kind:'ups',depends_on:['arrrrr2']},
]}]};
context.siteId='broadleaf';
vm.runInNewContext(phase6,context,{filename:'phase6-convergence.js'});
vm.runInNewContext(physical,context,{filename:'phase6-physical-convergence.js'});

const graphHelper=context.MonitorBoxPhase6Convergence;
const physicalHelper=context.MonitorBoxPhase6Physical;
assert(graphHelper,'convergence helper exported');
assert(physicalHelper,'physical helper exported');

const model={
  systems:[
    {id:'monitor',label:'MonitorBox',kind:'appliance',address:'192.168.3.5'},
    {id:'arrrrr2',label:'Arrrrr2',kind:'host',address:'192.168.3.9'},
  ],
  connections:[
    {id:'nut_local',label:'NUT',adapter:'nut',endpoint:'192.168.3.5:3493',parent_ids:['network_ups'],exposes_object_ids:['network_ups']},
    {id:'nut_server',label:'NUT',adapter:'nut',endpoint:'192.168.3.9:3493',parent_ids:['server_ups'],exposes_object_ids:['server_ups']},
  ],
  objects:[
    {id:'network_ups',label:'Network UPS',kind:'ups',depends_on:[]},
    {id:'server_ups',label:'Server UPS',kind:'ups',depends_on:['arrrrr2']},
  ],
};

const graph=graphHelper.workspaceRelationships(model);
assert.equal(graph.bySystem.get('monitor').length,1);
assert.equal(graph.bySystem.get('monitor')[0].connection.id,'nut_local');
assert.equal(graph.bySystem.get('arrrrr2').length,1);
assert.equal(graph.bySystem.get('arrrrr2')[0].connection.id,'nut_server');
assert.equal(graph.systemsByConnection.get('nut_local')[0].label,'MonitorBox');
assert.equal(graph.systemsByConnection.get('nut_server')[0].label,'Arrrrr2');

const markup=physicalHelper.buildAdvancedMarkup(model,'');
assert.match(markup,/Objects · UPS \(2\)/);
assert.match(markup,/data-phase6-system="monitor"[\s\S]*NUT · MonitorBox[\s\S]*Network UPS/);
assert.match(markup,/data-phase6-system="arrrrr2"[\s\S]*NUT · Arrrrr2[\s\S]*Server UPS/);
assert.match(markup,/data-phase6-category="connections"[\s\S]*NUT · MonitorBox/);
assert.match(markup,/data-phase6-category="connections"[\s\S]*NUT · Arrrrr2/);

const ambiguous={
  systems:[
    {id:'one',label:'One',kind:'host',address:'10.0.0.1'},
    {id:'two',label:'Two',kind:'host',address:'10.0.0.1'},
  ],
  connections:[{id:'shared',label:'HTTP(S)',adapter:'http',endpoint:'http://10.0.0.1:8080/',parent_ids:['service'],exposes_object_ids:['service']}],
  objects:[{id:'service',label:'Service',kind:'service',depends_on:[]}],
};
const ambiguousGraph=graphHelper.workspaceRelationships(ambiguous);
assert.equal(ambiguousGraph.bySystem.get('one').length,0);
assert.equal(ambiguousGraph.bySystem.get('two').length,0);
assert.equal(ambiguousGraph.systemsByConnection.get('shared').length,0);

const generic={state:'healthy',components:[{enabled:true,metadata:{maintenance:{
  provider:'synthetic-provider',kind:'database_reindex',state:'Rebuilding',health_neutral:true,fields:['database_index_status']
}}}]};
assert.equal(JSON.stringify(graphHelper.maintenanceFacts(generic)),JSON.stringify(['Database index rebuilding']));
assert.match(graphHelper.maintenanceMarkup(generic),/>Database index rebuilding<\/span>/);
assert.doesNotMatch(graphHelper.maintenanceMarkup(generic),/>Maintenance</);

const poolLike={state:'healthy',components:[{enabled:true,metadata:{maintenance:{
  provider:'synthetic-provider',kind:'storage_task',state:'Scrubbing',health_neutral:true,fields:['pool2_status']
}}}]};
assert.equal(JSON.stringify(graphHelper.maintenanceFacts(poolLike)),JSON.stringify(['Pool 2 scrubbing']));
assert.equal(graphHelper.maintenanceMarkup({...generic,state:'failed'}),'');
assert.equal(graphHelper.maintenanceMarkup({state:'healthy',components:[{metadata:{maintenance:{
  kind:'database_reindex',state:'Rebuilding',health_neutral:false,fields:['database_index_status']
}}}]}),'');

assert.equal(graphHelper.endpointHost('https://EXAMPLE.test:9443/path'),'example.test');
assert.equal(graphHelper.endpointHost('192.168.3.5:3493'),'192.168.3.5');
assert.doesNotMatch(phase6,/QNAP|Goliath|qutshero/i);
assert.doesNotMatch(physical,/QNAP|Goliath|qutshero/i);
assert.match(builder,/UI_VERSION="1\.1\.13"/);
assert.match(builder,/UI_BUILD=23/);
assert.match(builder,/build20\.RELEASE20,RELEASE23/);
assert.doesNotMatch(builder,/RELEASE22,RELEASE23/);
assert.match(stager,/PREDECESSOR=\("com\.sickicarus\.monitorbox\.ui","1\.1\.12",20\)/);
assert.match(stager,/RELEASE=\("com\.sickicarus\.monitorbox\.ui","1\.1\.13",23\)/);
console.log('UI Phase-6 build-23 acceptance: PASS (unique endpoint ownership + qualified Connections + compact maintenance)');
