#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = [
  '../sources/ui/1.0.0-build5/service-presentation.js',
  '../sources/ui/1.0.1-build6/provider-service-hierarchy.js',
  '../sources/ui/1.0.1-build6/provider-service-labels.js',
  '../sources/ui/1.1.1-build9/service-hierarchy-interactions.js',
  '../sources/ui/1.1.2-build10/service-hierarchy-physical-fixes.js',
].map(path => fs.readFileSync(new URL(path, import.meta.url), 'utf8')).join('\n');

const stateRanks = new Map([
  ['healthy', 0], ['planned', 0], ['unknown', 1], ['degraded', 2], ['failed', 3], ['offline', 4],
]);
let detailNodes = [];
let linkNodes = [];
let closeHandler = null;
const drawer = { addEventListener: (name, handler) => { if (name === 'close') closeHandler = handler; } };
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
  document: {
    querySelectorAll: selector => {
      if (selector === 'details[data-compose-stack]') return detailNodes;
      if (selector.includes('a.icon-outbound')) return linkNodes;
      return [];
    },
    querySelector: () => null,
  },
  $: selector => selector === '#drawer' ? drawer : null,
  URL,
  encodeURIComponent,
  console,
});
vm.runInContext(source, context, { filename: 'ui-build10-physical.js' });

function canonicalService(id, label, hostId, presentationUrl = null) {
  return {
    id, label, kind: 'service', state: 'healthy', summary: `${label} healthy`, retired: false,
    address: '', presentation_url: presentationUrl, icon: null, depends_on: [hostId],
    components: [{ enabled: true, state: 'healthy', adapter: 'http', summary: `${label} HTTP healthy`, metadata: {} }],
  };
}

function workload({ envKey = 'env', envName = 'Broad Leaf - Host', project, service, endpoints = [], state = 'running', health = 'healthy' }) {
  return {
    identity: `compose:${envKey}:${project}:${service}`,
    label: service,
    environment_key: envKey,
    environment: envName,
    environment_url: 'tcp://10.0.0.10:9001',
    compose_project: project,
    compose_service: service,
    discovery_actionable: true,
    ignored: false,
    service_endpoints: endpoints,
    containers: [{ provider_id: `${project}-${service}-1`, name: service, state, health }],
  };
}

const host = { id: 'host', label: 'Host', kind: 'host', address: '10.0.0.10', depends_on: [] };
const workloads = [
  workload({ project: 'ombi_mysql', service: 'ombi', endpoints: [{ host: '10.0.0.10', private_port: 3579, public_port: 3579, protocol: 'tcp' }] }),
  workload({ project: 'ombi_mysql', service: 'mariadb' }),
  workload({ project: 'ombi_mysql', service: 'phpmyadmin', endpoints: [{ host: '10.0.0.10', private_port: 80, public_port: 8081, protocol: 'tcp' }] }),
  workload({ project: 'scrob', service: 'scrob', endpoints: [{ host: '10.0.0.10', private_port: 7575, public_port: 7575, protocol: 'tcp' }] }),
  workload({ project: 'scrob', service: 'scrob-db' }),
];
const inventory = canonicalService('host_portainer', 'Portainer', 'host');
inventory.components = [{
  enabled: true, state: 'healthy', adapter: 'portainer', summary: 'inventory healthy',
  metadata: { provider: 'portainer', authoritative: true, workloads },
}];

// Deliberately use an ID suffix that the build-6 one-key matcher cannot reconcile.
// Exact normalized label + same owner + direct presentation endpoint are all true.
const ombi = canonicalService('host_ombi_frontend', 'Ombi', 'host', 'http://10.0.0.10:3579/');
const scrob = canonicalService('host_scrob', 'Scrob', 'host', 'http://10.0.0.10:7575/');
const site = { id: 'broadleaf', label: 'Broad Leaf', objects: [host, inventory, ombi, scrob] };
context.app.state.sites = [site];

let model = context.providerPresentationModel(site);
const mergedOmbi = model.services.find(service => service.id === 'host_ombi_frontend');
assert.ok(mergedOmbi?._provider_workload, 'build 10 must reconcile the canonical Ombi service to provider workload evidence');
assert.equal(mergedOmbi._provider_workload.compose_service, 'ombi');
assert.equal(mergedOmbi.presentation_url, 'http://10.0.0.10:3579/');
assert.equal(model.services.filter(service => service._provider_workload?.compose_service === 'ombi').length, 1, 'provider-only Ombi duplicate must be consumed by canonical reconciliation');

let entries = context.servicePresentationEntries(model.services);
let ombiStack = entries.find(entry => entry.kind === 'stack' && entry.group.project === 'ombi_mysql');
assert.ok(ombiStack);
assert.equal(ombiStack.label, 'Ombi', 'reconciled canonical application label must own the physical stack presentation');
const ombiChild = ombiStack.group.services.find(service => service.id === 'host_ombi_frontend');
const phpmyadmin = ombiStack.group.services.find(service => service.label === 'phpmyadmin');
assert.match(context.serviceRow(site, ombiChild, '__services__'), /href="http:\/\/10\.0\.0\.10:3579\/"/);
assert.equal(phpmyadmin.presentation_url, null, 'naked provider TCP endpoint must not be guessed as a browser URL');
assert.doesNotMatch(context.serviceRow(site, phpmyadmin, '__services__'), /href=/);

// The hierarchy's durable key intentionally contains a NUL separator. Build 10
// must never emit that raw value into HTML, because browsers normalize NUL.
assert.match(ombiStack.group.key, /\u0000/);
let html = context.serviceStackRow(site, ombiStack, '__services__');
const attribute = html.match(/data-compose-stack="([^"]+)"/)?.[1];
assert.ok(attribute, 'stack row must expose a disclosure key');
assert.equal(attribute.includes('\u0000'), false, 'rendered disclosure key must be HTML-safe');
assert.equal(attribute, context.uiBuild10StackKey(ombiStack));
assert.doesNotMatch(html, /^<details\b[^>]*\sopen(?:\s|>)/, 'healthy stack starts collapsed');

let toggleHandler = null;
const detailNode = {
  open: false,
  dataset: { composeStack: attribute },
  classList: ['healthy'],
  addEventListener: (name, handler) => { if (name === 'toggle') toggleHandler = handler; },
};
detailNodes = [detailNode];
context.bindServiceNavigation(site);
assert.equal(typeof toggleHandler, 'function');
detailNode.open = true;
toggleHandler();
assert.equal(context.app.serviceStackExpansion[attribute], true, 'operator expansion must be remembered under the encoded durable key');

// Recompute the provider model/entries to emulate a live state rerender rather
// than reusing the same object instance.
ombi.summary = 'Ombi healthy · refreshed';
model = context.providerPresentationModel(site);
entries = context.servicePresentationEntries(model.services);
ombiStack = entries.find(entry => entry.kind === 'stack' && entry.group.project === 'ombi_mysql');
html = context.serviceStackRow(site, ombiStack, '__services__');
assert.match(html, /^<details open\b/, 'explicit expansion survives a full provider/state rerender');

context.app.serviceStackExpansion[attribute] = false;
html = context.serviceStackRow(site, ombiStack, '__services__');
assert.doesNotMatch(html, /^<details\b[^>]*\sopen(?:\s|>)/, 'explicit collapse survives rerender');

const failed = { ...ombiStack, state: 'failed', group: { ...ombiStack.group, state: 'failed' } };
html = context.serviceStackRow(site, failed, '__services__');
assert.match(html, /<details[^>]*\sopen(?:\s|>)/, 'failing stack still forces open regardless of remembered collapse');

assert.equal(typeof closeHandler, 'function');
closeHandler();
assert.equal(Object.keys(context.app.serviceStackExpansion).length, 0, 'drawer close still resets visit-scoped disclosure state');

console.log('UI 1.1.2 build 10 physical acceptance: PASS (#206 bounded canonical/provider link reconciliation + #207 HTML-safe refresh-stable disclosure key)');
