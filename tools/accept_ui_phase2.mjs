#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const phase2Path=path.join(root,'sources','ui','1.1.5-build13','phase2-p1.js');
const physicalPath=path.join(root,'sources','ui','1.1.6-build14','phase2-physical-repairs.js');
const phase2Source=fs.readFileSync(phase2Path,'utf8');
const physicalSource=fs.readFileSync(physicalPath,'utf8');

const context={console,URL};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(phase2Source,context,{filename:phase2Path});
vm.runInContext(physicalSource,context,{filename:physicalPath});
const api=context.MonitorBoxUiPhase2;
const physical=context.MonitorBoxUiPhase2Physical;
assert.ok(api,'Phase-2 UI helpers must be exported for deterministic acceptance');
assert.ok(physical,'Physical-repair UI helpers must be exported for deterministic acceptance');

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

// #164 — environment scope is an explicit canonical provider selection, not an
// inventory filter. Empty/missing environment_ids means all authenticated
// environments; partial selection becomes durable explicit IDs. The supported UI
// refuses an impossible zero-environment selection rather than accidentally
// translating [] back to the provider's all-environments semantics.
const environments=physical.environmentRows({environments:[
  {provider_id:4,name:'Turnberry - Apollo',key:'turnberry_apollo'},
  {provider_id:1,name:'Broad Leaf - Goliath',key:'broad_leaf_goliath'},
  {provider_id:1,name:'duplicate should be ignored'},
]});
assert.deepEqual(Array.from(environments,row=>row.id),[1,4]);
const portainerConfig={};
assert.deepEqual(Array.from(physical.selectedEnvironmentIds(portainerConfig,environments)),[1,4]);
physical.applyEnvironmentSelection(portainerConfig,[1],[1,4]);
assert.deepEqual(Array.from(portainerConfig.environment_ids),[1]);
physical.applyEnvironmentSelection(portainerConfig,[1,4],[1,4]);
assert.equal('environment_ids' in portainerConfig,false);
assert.throws(
  ()=>physical.applyEnvironmentSelection(portainerConfig,[],[1,4]),
  /At least one Portainer environment/,
);
assert.match(physicalSource,/delete probe\.config\.environment_ids/);
assert.match(physicalSource,/Portainer environment scope/);
assert.match(physicalSource,/managed module/);

// #206 — accepted build-9/10 hierarchy behavior remains the safety authority. A
// child link may use an independently evidenced HTTP(S) URL; TCP-only endpoints
// can be used only to correlate a provider workload to that already-safe
// canonical authority. Build 14 broadens reconciliation beyond kind=service and
// remains fail-closed on ambiguity.
assert.equal(physical.safeHttpUrl('tcp://192.168.3.20:3579'),null);
assert.equal(physical.safeHttpUrl('javascript:alert(1)'),null);
assert.match(physical.safeHttpUrl('https://192.168.3.9:10443/'),/^https:/);

const goliath={id:'goliath',kind:'host',label:'Goliath',address:'192.168.3.20'};
const arrrrr2={id:'arrrrr2',kind:'host',label:'Arrrrr2',address:'192.168.3.9'};
const ombiCanonical={
  id:'goliath_ombi',kind:'service',label:'Ombi',depends_on:['goliath'],
  presentation_url:'http://192.168.3.20:3579/',state:'healthy',components:[],
};
const scryptedCanonical={
  id:'scrypted_authority',kind:'camera_system',label:'Scrypted',depends_on:['arrrrr2'],
  presentation_url:'https://192.168.3.9:10443/',state:'healthy',components:[],
};
const site={objects:[goliath,arrrrr2,ombiCanonical,scryptedCanonical]};
const ombiProvider={
  id:'provider-ombi',kind:'provider_workload',label:'Ombi',depends_on:['goliath'],
  _provider_workload:{
    identity:'compose:goliath:ombi_mysql:ombi',compose_service:'ombi',label:'ombi',
    images:['lscr.io/linuxserver/ombi:latest'],
    service_endpoints:[{host:'192.168.3.20',public_port:3579,protocol:'tcp'}],
  },
};
const scryptedProvider={
  id:'provider-scrypted',kind:'provider_workload',label:'Scrypted',depends_on:['arrrrr2'],
  _provider_workload:{
    identity:'compose:arrrrr2:scrypted:scrypted',compose_service:'scrypted',
    images:['koush/scrypted:latest'],
    service_endpoints:[{host:'192.168.3.9',public_port:10443,protocol:'tcp'}],
  },
};
const dbProvider={
  id:'provider-db',kind:'provider_workload',label:'db',depends_on:['goliath'],
  _provider_workload:{
    identity:'compose:goliath:ombi_mysql:db',compose_service:'db',images:['mariadb:latest'],
    service_endpoints:[{host:'192.168.3.20',public_port:3306,protocol:'tcp'}],
  },
};
const repaired=physical.reconcilePresentationServices(site,{
  services:[ombiCanonical,ombiProvider,scryptedProvider,dbProvider],
});
assert.equal(repaired.services.filter(row=>row.id==='goliath_ombi').length,1);
assert.equal(
  repaired.services.find(row=>row.id==='goliath_ombi')._provider_workload.identity,
  ombiProvider._provider_workload.identity,
);
assert.equal(
  repaired.services.find(row=>row.id==='scrypted_authority').presentation_url,
  'https://192.168.3.9:10443/',
);
assert.equal(repaired.services.find(row=>row.id==='provider-db').presentation_url,undefined);

const ambiguousSite={objects:[
  {id:'foo-one',kind:'service',label:'Foo',depends_on:['host'],presentation_url:'https://10.0.0.1:1001/'},
  {id:'foo-two',kind:'service',label:'Foo',depends_on:['host'],presentation_url:'https://10.0.0.1:1002/'},
]};
const ambiguousProvider={
  id:'provider-foo',kind:'provider_workload',label:'Foo',depends_on:['host'],
  _provider_workload:{identity:'compose:host:foo:foo',compose_service:'foo',images:[]},
};
const ambiguous=physical.reconcilePresentationServices(ambiguousSite,{services:[ambiguousProvider]});
assert.equal(ambiguous.services[0].id,'provider-foo');

const interactions=fs.readFileSync(
  path.join(root,'sources','ui','1.1.1-build9','service-hierarchy-interactions.js'),
  'utf8',
);
const physical10=fs.readFileSync(
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
assert.match(physical10,/\.\.\.service,\s*_provider_workload:providerObject\._provider_workload/s);
assert.match(presentation,/function serviceRow\(site,service,parent\)/);
assert.match(presentation,/\$\{serviceIcon\(service\)\}/);
assert.match(presentation,/orderedServices\(services\)\.map\(service=>serviceRow\(site,service,parent\)\)/);
assert.match(presentation,/serviceRows\(site,group\.services,parent\)/);
assert.match(presentation,/servicePresentationRows\(site,hosted,host\.id\)/);
assert.match(presentation,/if\(service\.presentation_url\)return`<a class="service-icon icon-outbound"/);

console.log(
  'UI Phase-2 acceptance: PASS '+
  '(Review truth + display labels + generic recommendation presentation + '+
  'Portainer environment scope + safe canonical/provider child links)'
);
