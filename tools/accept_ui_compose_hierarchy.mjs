#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = [
  '../sources/ui/1.0.0-build5/service-presentation.js',
  '../sources/ui/1.0.1-build6/provider-service-hierarchy.js',
  '../sources/ui/1.0.1-build6/provider-service-labels.js',
].map(path => fs.readFileSync(new URL(path, import.meta.url), 'utf8')).join('\n');

const stateRanks = new Map([
  ['healthy', 0], ['planned', 0], ['unknown', 1], ['degraded', 2], ['failed', 3],
]);
const context = vm.createContext({
  renderSite: () => '',
  findObject: () => ({ site: undefined, object: undefined }),
  renderDrawer: () => undefined,
  stateRank: state => stateRanks.get(String(state)) ?? 1,
  stateLabel: state => String(state),
  esc: value => String(value),
  pill: state => `<span class="state-pill ${state}">${state}</span>`,
  app: { state: { sites: [] }, selected: null },
  openDrawer: () => undefined,
  document: { querySelectorAll: () => [], querySelector: () => null },
  $: () => null,
  URL,
  console,
});
vm.runInContext(source, context, { filename: 'service-presentation-build6.js' });

for (const name of [
  'providerPresentationModel', 'providerEnvironmentOwners', 'providerWorkloadRuntime',
  'providerStackDisplayBase', 'servicesForSite', 'servicePresentationEntries',
  'serviceStackRow', 'serviceGroupObject',
]) {
  assert.equal(typeof context[name], 'function', `${name} must remain executable`);
}

function canonicalService(id, label, hostId, extra = {}) {
  return {
    id, label, kind: 'service', state: extra.state || 'healthy',
    summary: `${label} ${extra.state || 'healthy'}`, retired: false,
    address: extra.address || '', presentation_url: extra.presentation_url || null,
    icon: extra.icon || null, depends_on: hostId ? [hostId] : [],
    components: extra.components || [{ enabled: true, state: extra.state || 'healthy', adapter: 'http', summary: `${label} HTTP healthy`, metadata: {} }],
  };
}

function workload({ envKey, envName, envUrl, project = '', service = '', name, state = 'running', health = null, endpoints = [], actionable = true, suppression = null }) {
  const identity = project ? `compose:${envKey}:${project}:${service}` : `container:${envKey}:${name}`;
  return {
    identity,
    label: name || service,
    environment_key: envKey,
    environment: envName,
    environment_url: envUrl,
    compose_project: project,
    compose_service: service,
    discovery_actionable: actionable,
    discovery_suppression_reason: suppression,
    ignored: false,
    service_endpoints: endpoints,
    containers: [{ provider_id: `${identity}-container`, name: name || service, state, health }],
  };
}

const goliath = { id: 'goliath', label: 'Goliath', kind: 'host', address: '192.168.3.13', depends_on: [] };
const arrrrr2 = { id: 'arrrrr2', label: 'Arrrrr2', kind: 'host', address: '192.168.3.9', depends_on: [] };
const monitor = { id: 'monitor', label: 'Monitor', kind: 'appliance', address: '192.168.3.5', depends_on: [] };
const turnberry = { id: 'turnberry', label: 'Turnberry', kind: 'remote_site', address: '192.168.1.0/24', depends_on: [] };

const workloads = [
  workload({ envKey: 'broad_leaf_-_goliath', envName: 'Broad Leaf - Goliath', envUrl: 'unix:///var/run/docker.sock', project: 'ombi_mysql', service: 'ombi', name: 'ombi', endpoints: [{ host: '192.168.3.13', public_port: 3579 }] }),
  workload({ envKey: 'broad_leaf_-_goliath', envName: 'Broad Leaf - Goliath', envUrl: 'unix:///var/run/docker.sock', project: 'ombi_mysql', service: 'mariadb', name: 'mariadb' }),
  workload({ envKey: 'broad_leaf_-_goliath', envName: 'Broad Leaf - Goliath', envUrl: 'unix:///var/run/docker.sock', project: 'ombi_mysql', service: 'phpmyadmin', name: 'phpmyadmin', endpoints: [{ host: '192.168.3.13', public_port: 8081 }] }),
  workload({ envKey: 'broad_leaf_-_goliath', envName: 'Broad Leaf - Goliath', envUrl: 'unix:///var/run/docker.sock', name: 'portainer', actionable: false, suppression: 'authenticated_portainer_controller' }),
  workload({ envKey: 'broad_leaf_-_goliath', envName: 'Broad Leaf - Goliath', envUrl: 'unix:///var/run/docker.sock', name: 'watchtower' }),
  workload({ envKey: 'broad_leaf_-_arrrrr2', envName: 'Broad Leaf - Arrrrr2', envUrl: 'tcp://192.168.3.9:9001', project: 'scrob', service: 'scrob', name: 'scrob', endpoints: [{ host: '192.168.3.9', public_port: 7575 }] }),
  workload({ envKey: 'broad_leaf_-_arrrrr2', envName: 'Broad Leaf - Arrrrr2', envUrl: 'tcp://192.168.3.9:9001', project: 'scrob', service: 'scrob-db', name: 'scrob-db' }),
  workload({ envKey: 'broad_leaf_-_monitor', envName: 'Broad Leaf - Monitor', envUrl: 'tcp://192.168.3.5:9001', project: 'monitorbox', service: 'controller', name: 'controller' }),
  workload({ envKey: 'broad_leaf_-_monitor', envName: 'Broad Leaf - Monitor', envUrl: 'tcp://192.168.3.5:9001', project: 'monitorbox', service: 'agent', name: 'agent' }),
  workload({ envKey: 'turnberry_-_apollo', envName: 'Turnberry - Apollo', envUrl: 'tcp://192.168.1.9:9001', project: 'foreign', service: 'app', name: 'app', endpoints: [{ host: '192.168.1.9', public_port: 8080 }] }),
  workload({ envKey: 'turnberry_-_apollo', envName: 'Turnberry - Apollo', envUrl: 'tcp://192.168.1.9:9001', project: 'foreign', service: 'db', name: 'db' }),
];

const inventoryMetadata = { provider: 'portainer', authoritative: true, workloads };
const portainer = canonicalService('goliath_portainer', 'Portainer', 'goliath', {
  components: [{ enabled: true, state: 'healthy', adapter: 'portainer', summary: 'Portainer inventory healthy', metadata: inventoryMetadata }],
});
const ombi = canonicalService('goliath_ombi', 'Ombi', 'goliath');
const scrob = canonicalService('arrrrr2_scrob', 'Scrob', 'arrrrr2');
const cockpit = canonicalService('arrrrr2_cockpit', 'Cockpit', 'arrrrr2');

const site = {
  id: 'broadleaf', label: 'Broad Leaf',
  objects: [goliath, arrrrr2, monitor, turnberry, portainer, ombi, scrob, cockpit],
};
context.app.state.sites = [site];

const model = context.providerPresentationModel(site);
assert.equal(model.inventory.length, 11, 'raw authoritative inventory remains complete');
assert.deepEqual(
  new Set([...model.owners.keys()]),
  new Set(['broad_leaf_-_goliath', 'broad_leaf_-_arrrrr2', 'broad_leaf_-_monitor']),
  'only exact canonical host/appliance environments may enter the Service Directory',
);
assert.equal(model.owners.has('turnberry_-_apollo'), false, 'remote Site/CIDR reachability must not establish local service ownership');

const visible = context.servicesForSite(site);
assert.ok(visible.length > 4, 'provider workload children must extend the canonical service-only directory');
assert.equal(visible.some(item => String(item._provider_workload?.environment_key) === 'turnberry_-_apollo'), false, 'foreign Apollo workloads must not leak into Broad Leaf Services');
assert.equal(visible.some(item => item._provider_workload?.discovery_suppression_reason === 'authenticated_portainer_controller'), false, 'controller-self provenance must stay non-actionable');
assert.equal(visible.filter(item => item.id === 'goliath_ombi').length, 1, 'canonical Ombi service must not be duplicated by provider evidence');
assert.ok(visible.some(item => item.label === 'mariadb' && item.kind === 'provider_workload'));
assert.ok(visible.some(item => item.label === 'phpmyadmin' && item.kind === 'provider_workload'));
assert.ok(visible.some(item => item.label === 'scrob-db' && item.kind === 'provider_workload'));
assert.ok(visible.some(item => item.label === 'watchtower' && item.kind === 'provider_workload'), 'local standalone provider workload must remain standalone');

let entries = context.servicePresentationEntries(visible);
const ombiStack = entries.find(entry => entry.kind === 'stack' && entry.group.project === 'ombi_mysql');
assert.ok(ombiStack, 'Ombi provider project must materialize as a stack parent');
assert.equal(ombiStack.label, 'Ombi', 'canonical application label should present the provider stack');
assert.equal(ombiStack.group.environmentLabel, 'Broad Leaf - Goliath', 'real Portainer environment field should drive parent provenance');
assert.equal(ombiStack.group.services.length, 3);
assert.deepEqual(
  new Set(ombiStack.group.services.map(item => item.label)),
  new Set(['Ombi', 'mariadb', 'phpmyadmin']),
  'canonical application plus provider-only DB/admin members must share one parent',
);
assert.equal(ombiStack.group.services.find(item => item.label === 'Ombi').id, 'goliath_ombi', 'canonical child identity must be preserved');
const scrobStack = entries.find(entry => entry.kind === 'stack' && entry.group.project === 'scrob');
assert.equal(scrobStack?.label, 'Scrob', 'canonical Scrob label should present its Compose parent');
let html = context.serviceStackRow(site, ombiStack, '__services__');
assert.match(html, /<details class="service-compose-group healthy"/);
assert.doesNotMatch(html, /service-compose-group healthy"[^>]* open/, 'healthy stack defaults collapsed');
assert.match(html, /data-service-object="goliath_ombi"/);
assert.match(html, /__provider_workload__:/, 'provider-only child must retain direct detail navigation');

const providerChild = ombiStack.group.services.find(item => item.kind === 'provider_workload');
const resolved = context.findObject('broadleaf', providerChild.id);
assert.equal(resolved.object.kind, 'provider_workload');
assert.equal(resolved.object._provider_workload.identity, providerChild._provider_workload.identity);

const failedWorkloads = workloads.map(row => row.compose_service === 'mariadb'
  ? { ...row, containers: row.containers.map(container => ({ ...container, health: 'unhealthy' })) }
  : row);
portainer.components[0].metadata = { provider: 'portainer', authoritative: true, workloads: failedWorkloads };
entries = context.servicePresentationEntries(context.servicesForSite(site));
const failedStack = entries.find(entry => entry.kind === 'stack' && entry.group.project === 'ombi_mysql');
assert.equal(failedStack.state, 'failed', 'confirmed provider child runtime failure must propagate to parent');
html = context.serviceStackRow(site, failedStack, '__services__');
assert.match(html, /service-compose-group failed"[^>]* open/, 'failed child must auto-expand parent');

const stoppedWorkloads = failedWorkloads.map(row => row.compose_service === 'mariadb'
  ? { ...row, containers: row.containers.map(container => ({ ...container, health: null, state: 'exited' })) }
  : row);
portainer.components[0].metadata = { provider: 'portainer', authoritative: true, workloads: stoppedWorkloads };
entries = context.servicePresentationEntries(context.servicesForSite(site));
const neutralStack = entries.find(entry => entry.kind === 'stack' && entry.group.project === 'ombi_mysql');
assert.equal(neutralStack.state, 'healthy', 'policy-neutral stopped provider member must not falsely fail a healthy canonical application');
assert.equal(neutralStack.group.services.find(item => item.label === 'mariadb').state, 'unknown', 'child still exposes unknown expected-state truth');

const duplicateEntries = context.servicePresentationEntries([
  canonicalService('a_ombi', 'Ombi', 'a', { components: [{ enabled: true, state: 'healthy', adapter: 'portainer', summary: 'healthy', metadata: { provider: 'portainer', compose_project: 'ombi_mysql', compose_service: 'ombi', environment_key: 'env-a', environment_name: 'Environment A', deployment_kind: 'compose' } }] }),
  { id: 'a_db', label: 'db', kind: 'provider_workload', state: 'healthy', components: [], _provider_workload: { compose_project: 'ombi_mysql', compose_service: 'db', environment_key: 'env-a', environment: 'Environment A' } },
  canonicalService('b_ombi', 'Ombi', 'b', { components: [{ enabled: true, state: 'healthy', adapter: 'portainer', summary: 'healthy', metadata: { provider: 'portainer', compose_project: 'ombi_mysql', compose_service: 'ombi', environment_key: 'env-b', environment_name: 'Environment B', deployment_kind: 'compose' } }] }),
  { id: 'b_db', label: 'db', kind: 'provider_workload', state: 'healthy', components: [], _provider_workload: { compose_project: 'ombi_mysql', compose_service: 'db', environment_key: 'env-b', environment: 'Environment B' } },
]);
assert.deepEqual(
  new Set(duplicateEntries.filter(entry => entry.kind === 'stack').map(entry => entry.label)),
  new Set(['Ombi · Environment A', 'Ombi · Environment B']),
  'same application label in different environments must remain disambiguated',
);

const directory = context.serviceGroupObject(site);
assert.equal(directory.health_participant, false);
assert.ok(directory.services.length > 4);

console.log(
  'UI 1.0.1 build 6 provider-backed Compose hierarchy acceptance: PASS ' +
  '(authoritative inventory + canonical dedupe + provider-only children + local environment ownership + foreign exclusion + canonical parent labels + environment disambiguation + direct detail + worst-child anomaly propagation)',
);
