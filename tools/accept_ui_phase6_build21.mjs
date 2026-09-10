#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const sourcePath=path.join(root,'sources','ui','1.1.13-build21','phase6-convergence.js');
const cssPath=path.join(root,'sources','ui','1.1.13-build21','phase6-convergence.css');
const builderPath=path.join(root,'tools','build_first_party_ui_build21.py');
const source=fs.readFileSync(sourcePath,'utf8');
const css=fs.readFileSync(cssPath,'utf8');
const builder=fs.readFileSync(builderPath,'utf8');
const context={console,setTimeout,clearTimeout}; context.globalThis=context;
vm.createContext(context); vm.runInContext(source,context,{filename:sourcePath});
const api=context.MonitorBoxPhase6Convergence;
assert.ok(api,'Phase-6 convergence helper must export');

const model={
  systems:[{id:'monitor',label:'MonitorBox'},{id:'arrrrr2',label:'Arrrrr2'}],
  connections:[
    {id:'nut-monitor',label:'NUT · MonitorBox',adapter:'nut',parent_ids:['monitor_ups'],exposes_object_ids:['monitor_ups']},
    {id:'nut-a2',label:'NUT · Arrrrr2',adapter:'nut',parent_ids:['server_ups'],exposes_object_ids:['server_ups']},
  ],
  objects:[
    {id:'monitor_ups',label:'Network UPS',kind:'ups',depends_on:['monitor']},
    {id:'server_ups',label:'Server UPS',kind:'ups',depends_on:['arrrrr2']},
  ]
};
const relationships=api.workspaceRelationships(model);
assert.deepEqual([...relationships.bySystem.keys()],['monitor','arrrrr2']);
assert.equal(relationships.bySystem.get('monitor').length,1);
assert.equal(relationships.bySystem.get('monitor')[0].objects[0].id,'monitor_ups');
assert.equal(relationships.bySystem.get('arrrrr2')[0].connection.id,'nut-a2');
assert.equal(relationships.bySystem.get('arrrrr2')[0].objects[0].id,'server_ups');
assert.deepEqual(model.objects.map(item=>item.id),['monitor_ups','server_ups'],'relationship projection must not remove category/index objects');
assert.equal(api.categoryLabel('ups'),'Power / UPS');

const healthy={state:'healthy',components:[{enabled:true,metadata:{maintenance:{provider:'synthetic',kind:'database_reindex',state:'Reindexing',health_neutral:true}}}]};
assert.equal(JSON.stringify(api.maintenanceFacts(healthy)),JSON.stringify(['database reindex: Reindexing']));
assert.match(api.maintenanceMarkup(healthy),/Maintenance/);
assert.match(api.maintenanceMarkup(healthy),/data-maintenance-health-neutral="true"/);
assert.equal(api.maintenanceMarkup({...healthy,state:'failed'}),'','fault state remains primary');
assert.equal(api.maintenanceMarkup({state:'healthy',components:[{metadata:{maintenance:{kind:'work',state:'Busy',health_neutral:false}}}]}), '');

assert.match(builder,/UI_VERSION = "1\.1\.13"/);
assert.match(builder,/UI_BUILD = 21/);
assert.match(builder,/previous\._build20_assets/);
assert.match(builder,/maintenanceMarkup/);
assert.match(builder,/decorateWorkspace/);
assert.match(builder,/request\.path == "\/settings\/advanced"/);
assert.match(css,/min-height:\s*44px/);
assert.doesNotMatch(source,/QNAP|SNMP|Goliath|Scrubbing/i,'UI convergence must remain provider-neutral');
console.log('UI Phase-6 build-21 acceptance: PASS (relationship discoverability + health-neutral maintenance)');
