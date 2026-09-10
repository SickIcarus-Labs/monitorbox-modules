#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const repairPath=path.join(root,'sources','ui','1.1.10-build18','phase2-physical-repairs5.js');
const servicePath=path.join(root,'sources','ui','1.0.0-build5','service-presentation.js');
const providerPath=path.join(root,'sources','ui','1.0.1-build6','provider-service-hierarchy.js');
const repairSource=fs.readFileSync(repairPath,'utf8');
const serviceSource=fs.readFileSync(servicePath,'utf8');
const providerSource=fs.readFileSync(providerPath,'utf8');

const context={console,URL};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(repairSource,context,{filename:repairPath});
const api=context.MonitorBoxUiPhase2Physical5;
assert.ok(api,'build-18 provider-authority helper must be exported');

// #165 — provider runtime state is authoritative for a provider workload row.
// Canonical service evidence may contribute safe presentation metadata, but it
// must not overwrite Portainer's degraded runtime truth with Unknown/Healthy.
const canonical={
  id:'goliath_ombi',
  kind:'service',
  label:'Ombi',
  icon:'ombi',
  depends_on:['goliath'],
  state:'unknown',
  underlying_state:'unknown',
  summary:'Canonical HTTP observation unavailable',
  presentation_url:'https://ombi.example.test/',
  components:[],
};
const provider={
  id:'provider-ombi',
  kind:'provider_workload',
  label:'ombi',
  depends_on:['goliath'],
  state:'degraded',
  underlying_state:'degraded',
  summary:'Docker workload is starting',
  _provider_workload:{
    identity:'compose:goliath:ombi_mysql:ombi',
    compose_project:'ombi_mysql',
    compose_service:'ombi',
    label:'ombi',
    images:['lscr.io/linuxserver/ombi:latest'],
    service_endpoints:[],
  },
};
const model=api.reconcilePresentationServices(
  {objects:[canonical]},
  {services:[canonical,provider]},
);
assert.equal(model.services.length,1,'reconciled presentation must consume the duplicate canonical row');
const rendered=model.services[0];
assert.equal(rendered.id,'provider-ombi');
assert.equal(rendered.kind,'provider_workload');
assert.equal(rendered.state,'degraded','canonical Unknown must not replace provider degraded state');
assert.equal(rendered.underlying_state,'degraded');
assert.equal(rendered.summary,'Docker workload is starting');
assert.equal(rendered.presentation_url,'https://ombi.example.test/');
assert.equal(rendered.label,'Ombi');
assert.equal(rendered._canonical_presentation_authority,'goliath_ombi');

// Pin the inherited display chain: service rows feed the retained object state
// directly into the common pill renderer; provider runtime explicitly emits
// degraded for transitional/startup conditions. Later UI releases compose over
// these accepted layers rather than creating a second provider-health model.
assert.match(repairSource,/\.\.\.providerObject/);
assert.match(repairSource,/provider inventory owns runtime/i);
assert.doesNotMatch(repairSource,/state\s*:\s*canonical(?:\.|\?\.)state/);
assert.match(serviceSource,/\$\{pill\(service\.state\)\}/);
assert.match(providerSource,/if\(starting\)return\{state:'degraded'/);

console.log(
  'Phase-7B UI observer-truth acceptance: PASS '+
  '(provider degraded runtime state survives canonical presentation reconciliation)'
);
