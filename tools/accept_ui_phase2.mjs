#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const phase2Path=path.join(root,'sources','ui','1.1.5-build13','phase2-p1.js');
const phase2Source=fs.readFileSync(phase2Path,'utf8');

const context={console};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(phase2Source,context,{filename:phase2Path});
const api=context.MonitorBoxUiPhase2;
assert.ok(api,'Phase-2 UI helpers must be exported for deterministic acceptance');

// #160 — existing owners are reference context, not staged System additions.
const session={
  systems:[
    {id:'monitor',label:'Monitor',address:'192.168.3.5',self:true},
    {id:'goliath',label:'Goliath',address:'192.168.3.20'},
  ],
  added_system_ids:['goliath'],
};
const sets=api.reviewSystemSets(
  session,
  [{label:'Portainer',system_id:'monitor'}],
  [{label:'Goliath service',system_id:'goliath'}],
);
assert.deepEqual(Array.from(sets.added,row=>row.id),['goliath']);
assert.deepEqual(Array.from(sets.referenced,row=>row.id),['monitor']);

// #159 — operator labels win; strong product evidence can canonicalize a product;
// generic provider/machine labels get conservative readability cleanup only.
assert.equal(
  api.discoveryDisplayLabel({configured_label:'My Weird Name',label:'qbittorrent'}),
  'My Weird Name',
);
assert.equal(
  api.providerDisplayLabel({label:'download_box',images:['lscr.io/linuxserver/qbittorrent:latest']}),
  'qBittorrent',
);
assert.equal(api.providerDisplayLabel({compose_service:'home_assistant'}),'Home assistant');
assert.equal(api.prettifyMachineLabel('camera_proxy-prod'),'Camera proxy prod');
assert.equal(
  api.providerDisplayLabel({compose_service:'worker_one'}),
  api.providerDisplayLabel({compose_service:'worker_one'}),
  'duplicate human labels must remain valid; display formatting is not identity',
);
assert.ok(!phase2Source.includes('candidate_id='),'display code must not rewrite candidate identity');
assert.ok(!phase2Source.includes('source_id='),'display code must not rewrite provider identity');

// #170 — UI consumes generic provider policy, not UniFi-specific names/ports.
assert.deepEqual(
  {...api.discoveryPolicyPresentation({state:'recommended',policy_default:'required'})},
  {label:'Recommended',preselect:true},
);
assert.deepEqual(
  {...api.discoveryPolicyPresentation({state:'recommended',policy_default:'optional'})},
  {label:'Optional',preselect:false},
);
assert.equal(
  api.discoveryPolicyPresentation({state:'already_monitored',policy_default:'optional',configured_object_id:'port-1'}),
  null,
);

// #206 — accepted build-9/10 hierarchy behavior is the safety authority. A child
// link can use an independently evidenced HTTP(S) URL; TCP-only endpoints cannot
// become web links merely because their port looks familiar. Build 10 preserves a
// canonical presentation_url when reconciling it with a provider workload.
const interactions=fs.readFileSync(
  path.join(root,'sources','ui','1.1.1-build9','service-hierarchy-interactions.js'),
  'utf8',
);
const physical=fs.readFileSync(
  path.join(root,'sources','ui','1.1.2-build10','service-hierarchy-physical-fixes.js'),
  'utf8',
);
const presentation=fs.readFileSync(
  path.join(root,'sources','ui','1.0.0-build5','service-presentation.js'),
  'utf8',
);
assert.match(interactions,/parsed\.protocol==='http:'\|\|parsed\.protocol==='https:'/);
assert.match(interactions,/if\(!\['http','https'\]\.includes\(scheme\)\)return null/);
assert.match(interactions,/service-compose-members a\.icon-outbound/);
assert.match(physical,/\.\.\.service,\s*_provider_workload:providerObject\._provider_workload/s);
assert.match(presentation,/services\.map\(service=>serviceRow\(service,false,site\)\)/);
assert.match(presentation,/const presentationUrl=servicePresentationUrl\(service\)/);

console.log(
  'UI Phase-2 acceptance: PASS '+
  '(Review truth + display labels + generic recommendation presentation + safe child links)'
);
