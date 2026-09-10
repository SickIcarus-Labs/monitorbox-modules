#!/usr/bin/env node
'use strict';
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import path from 'node:path';

const root=path.resolve(path.dirname(new URL(import.meta.url).pathname),'..');
const phase6=fs.readFileSync(path.join(root,'sources/ui/1.1.13-build21/phase6-convergence.js'),'utf8');
const physical=fs.readFileSync(path.join(root,'sources/ui/1.1.14-build22/phase6-physical-convergence.js'),'utf8');
const css=fs.readFileSync(path.join(root,'sources/ui/1.1.14-build22/phase6-physical-convergence.css'),'utf8');
const builder=fs.readFileSync(path.join(root,'tools/build_first_party_ui_build22.py'),'utf8');

const context={console,Map,Set,URL,queueMicrotask,setTimeout,clearTimeout};
context.globalThis=context;
context.working={sites:[{id:'broadleaf',objects:[
  {id:'monitor',label:'MonitorBox',kind:'host'},
  {id:'arrrrr2',label:'Arrrrr2',kind:'host'},
  {id:'network_ups',label:'Network UPS',kind:'ups'},
  {id:'server_ups',label:'Server UPS',kind:'ups',depends_on:['arrrrr2']},
]}]};
context.siteId='broadleaf';
vm.runInNewContext(phase6,context,{filename:'phase6-convergence.js'});
vm.runInNewContext(physical,context,{filename:'phase6-physical-convergence.js'});
const helper=context.MonitorBoxPhase6Physical;
assert(helper,'physical helper exported');

const model={
  systems:[
    {id:'monitor',label:'MonitorBox',kind:'host'},
    {id:'arrrrr2',label:'Arrrrr2',kind:'host'},
  ],
  connections:[
    {id:'nut_local',label:'NUT · MonitorBox',adapter:'nut',endpoint:'192.168.3.5:3493',parent_ids:['monitor'],exposes_object_ids:['network_ups']},
    {id:'nut_server',label:'NUT · Arrrrr2',adapter:'nut',endpoint:'192.168.3.9:3493',parent_ids:['arrrrr2'],exposes_object_ids:['server_ups']},
  ],
  objects:[
    {id:'network_ups',label:'Network UPS',kind:'ups',depends_on:[]},
    {id:'server_ups',label:'Server UPS',kind:'ups',depends_on:['arrrrr2']},
  ],
};
const summary=helper.advancedSummary(model);
assert.match(summary,/Connections 2/);
assert.match(summary,/UPS 2/);
const markup=helper.buildAdvancedMarkup(model,'');
assert.match(markup,/Objects · UPS \(2\)/);
assert.match(markup,/Network UPS/);
assert.match(markup,/Server UPS/);
assert.match(markup,/NUT · MonitorBox/);
assert.match(markup,/NUT · Arrrrr2/);
assert.match(markup,/data-phase6-system="arrrrr2"[\s\S]*NUT · Arrrrr2[\s\S]*Server UPS/);
assert.match(markup,/data-phase6-system="monitor"[\s\S]*NUT · MonitorBox[\s\S]*Network UPS/);

const generic={state:'healthy',components:[{enabled:true,metadata:{maintenance:{provider:'synthetic',kind:'database_reindex',state:'Rebuilding',health_neutral:true}}}]};
const maintenance=context.MonitorBoxPhase6Convergence.maintenanceMarkup(generic);
assert.match(maintenance,/Maintenance/);
assert.match(maintenance,/database reindex: Rebuilding/);
assert.equal(context.MonitorBoxPhase6Convergence.maintenanceMarkup({...generic,state:'failed'}),'');
assert.equal(context.MonitorBoxPhase6Convergence.maintenanceMarkup({state:'healthy',components:[{metadata:{maintenance:{kind:'database_reindex',state:'Rebuilding',health_neutral:false}}}]}),'' );
assert.doesNotMatch(physical,/QNAP|SNMP|Goliath|Scrubbing/i);
assert.match(css,/\.parity-card > \.phase6-maintenance/);
assert.match(css,/@media \(pointer: coarse\)/);
assert.match(builder,/UI_VERSION="1\.1\.14"/);
assert.match(builder,/UI_BUILD=22/);
assert.match(builder,/build_first_party_ui_build21 as previous/);
assert.match(builder,/_PHASE6_PHYSICAL_SCRIPT/);
assert.match(builder,/phase6-physical-convergence\.js/);
console.log('UI Phase-6 build-22 acceptance: PASS (real Advanced index + parity-card maintenance seams)');
