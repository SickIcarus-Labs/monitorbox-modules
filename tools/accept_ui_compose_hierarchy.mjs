#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(
  new URL('../sources/ui/1.0.0-build5/service-presentation.js', import.meta.url),
  'utf8',
);

const stateRanks = new Map([
  ['healthy', 0],
  ['planned', 0],
  ['unknown', 1],
  ['degraded', 2],
  ['failed', 3],
]);

const context = vm.createContext({
  renderSite: () => '',
  findObject: () => ({ site: undefined, object: undefined }),
  renderDrawer: () => undefined,
  stateRank: state => stateRanks.get(String(state)) ?? 1,
  esc: value => String(value),
  pill: state => `<span class="state-pill ${state}">${state}</span>`,
  app: { state: { sites: [] }, selected: null },
  openDrawer: () => undefined,
  document: { querySelectorAll: () => [], querySelector: () => null },
  $: () => null,
  console,
});
vm.runInContext(source, context, { filename: 'service-presentation.js' });

const {
  serviceComposeProvenance,
  servicePresentationEntries,
  serviceStackRow,
  serviceGroupObject,
} = context;
for (const [name, value] of Object.entries({
  serviceComposeProvenance,
  servicePresentationEntries,
  serviceStackRow,
  serviceGroupObject,
})) {
  assert.equal(typeof value, 'function', `${name} must remain executable`);
}

function service({
  id,
  label,
  state = 'healthy',
  environmentKey,
  environmentName,
  project,
  composeService,
  deployment = 'compose',
  provider = 'portainer',
  providerContainerId = `${id}-container-1`,
}) {
  const metadata = provider
    ? {
        provider,
        environment_key: environmentKey,
        environment_name: environmentName,
        compose_project: project,
        compose_service: composeService,
        deployment_kind: deployment,
        container_provider_id: providerContainerId,
      }
    : {};
  return {
    id,
    label,
    kind: 'service',
    state,
    summary: `${label} ${state}`,
    retired: false,
    components: [
      {
        enabled: true,
        state,
        adapter: provider,
        summary: `${label} runtime ${state}`,
        metadata,
      },
    ],
    depends_on: [],
  };
}

const ombiWeb = service({
  id: 'svc-ombi-web',
  label: 'Ombi',
  environmentKey: 'goliath',
  environmentName: 'Goliath',
  project: 'ombi',
  composeService: 'ombi',
});
const ombiDb = service({
  id: 'svc-ombi-db',
  label: 'MariaDB',
  environmentKey: 'goliath',
  environmentName: 'Goliath',
  project: 'ombi',
  composeService: 'mariadb',
});
const standalone = service({
  id: 'svc-standalone',
  label: 'Standalone',
  environmentKey: 'goliath',
  environmentName: 'Goliath',
  project: '',
  composeService: '',
  deployment: 'standalone',
});
const singleton = service({
  id: 'svc-single-compose',
  label: 'Single Compose Service',
  environmentKey: 'goliath',
  environmentName: 'Goliath',
  project: 'single-project',
  composeService: 'only-service',
});

let entries = servicePresentationEntries([
  ombiWeb,
  ombiDb,
  standalone,
  singleton,
]);
assert.equal(entries.filter(entry => entry.kind === 'stack').length, 1);
const goliathOmbi = entries.find(entry => entry.kind === 'stack');
assert.ok(goliathOmbi);
assert.equal(goliathOmbi.group.key, 'goliath\u0000ombi');
assert.equal(goliathOmbi.group.services.length, 2);
assert.deepEqual(
  new Set(goliathOmbi.group.services.map(item => item.id)),
  new Set(['svc-ombi-web', 'svc-ombi-db']),
);
assert.equal(
  entries.find(entry => entry.kind === 'service' && entry.service.id === 'svc-standalone')?.service,
  standalone,
  'standalone service must remain the canonical child object',
);
assert.equal(
  entries.find(entry => entry.kind === 'service' && entry.service.id === 'svc-single-compose')?.service,
  singleton,
  'single-member Compose project must not add pointless parent indirection',
);

const arrWeb = service({
  id: 'svc-arr-web',
  label: 'Ombi',
  environmentKey: 'arrrrr2',
  environmentName: 'Arrrrr2',
  project: 'ombi',
  composeService: 'ombi',
});
const arrDb = service({
  id: 'svc-arr-db',
  label: 'MariaDB',
  environmentKey: 'arrrrr2',
  environmentName: 'Arrrrr2',
  project: 'ombi',
  composeService: 'mariadb',
});
entries = servicePresentationEntries([ombiWeb, ombiDb, arrWeb, arrDb]);
const stacks = entries.filter(entry => entry.kind === 'stack');
assert.equal(stacks.length, 2);
assert.deepEqual(
  new Set(stacks.map(entry => entry.group.key)),
  new Set(['goliath\u0000ombi', 'arrrrr2\u0000ombi']),
  'same project name on different environments must never collapse together',
);
assert.deepEqual(
  new Set(stacks.map(entry => entry.label)),
  new Set(['ombi · Goliath', 'ombi · Arrrrr2']),
  'duplicate project names must be visibly disambiguated by environment',
);

const beforeRecreate = serviceComposeProvenance(ombiWeb);
const recreated = service({
  id: ombiWeb.id,
  label: ombiWeb.label,
  environmentKey: 'goliath',
  environmentName: 'Goliath',
  project: 'ombi',
  composeService: 'ombi',
  providerContainerId: 'entirely-new-container-id',
});
const afterRecreate = serviceComposeProvenance(recreated);
assert.equal(beforeRecreate.key, afterRecreate.key);
assert.equal(beforeRecreate.project, afterRecreate.project);

const healthyEntry = servicePresentationEntries([ombiWeb, ombiDb]).find(
  entry => entry.kind === 'stack',
);
const healthyHtml = serviceStackRow({}, healthyEntry, '__services__');
assert.match(healthyHtml, /<details class="service-compose-group healthy"/);
assert.doesNotMatch(
  healthyHtml,
  /<details class="service-compose-group healthy"[^>]* open/,
  'healthy stack must default collapsed',
);
assert.match(healthyHtml, /data-service-object="svc-ombi-web"/);
assert.match(healthyHtml, /data-service-object="svc-ombi-db"/);

const failedDb = service({
  id: 'svc-ombi-db',
  label: 'MariaDB',
  state: 'failed',
  environmentKey: 'goliath',
  environmentName: 'Goliath',
  project: 'ombi',
  composeService: 'mariadb',
});
const failedEntry = servicePresentationEntries([ombiWeb, failedDb]).find(
  entry => entry.kind === 'stack',
);
assert.equal(failedEntry.state, 'failed');
const failedHtml = serviceStackRow({}, failedEntry, '__services__');
assert.match(
  failedHtml,
  /<details class="service-compose-group failed"[^>]* open/,
  'non-healthy child must make the parent visible and auto-expanded',
);
assert.match(failedHtml, /data-service-object="svc-ombi-db"/);

const site = {
  id: 'broadleaf',
  objects: [ombiWeb, failedDb, standalone],
};
const directory = serviceGroupObject(site);
assert.equal(directory.health_participant, false);
assert.equal(directory.state, 'failed');
assert.equal(directory.services[0], ombiWeb);
assert.ok(
  directory.services.includes(failedDb) && directory.services.includes(standalone),
  'presentation grouping must not replace or discard canonical service objects',
);

console.log(
  'UI build-5 Compose hierarchy acceptance: PASS ' +
    '(stable environment+project grouping + same-name disambiguation + ' +
    'canonical children + singleton/standalone preservation + attention auto-expand)',
);
