#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = [
  '../sources/ui/1.0.0-build5/service-presentation.js',
  '../sources/ui/1.0.1-build6/provider-service-hierarchy.js',
  '../sources/ui/1.0.1-build6/provider-service-labels.js',
  '../sources/ui/1.1.1-build9/service-hierarchy-interactions.js',
].map(path => fs.readFileSync(new URL(path, import.meta.url), 'utf8')).join('\n');

const stateRanks = new Map([
  ['healthy', 0], ['planned', 0], ['unknown', 1], ['degraded', 2], ['failed', 3], ['offline', 4],
]);
let closeHandler = null;
let detailNodes = [];
let linkNodes = [];
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
  console,
});
vm.runInContext(source, context, { filename: 'ui-build9-service-interactions.js' });

function canonicalService(id, label, hostId, presentationUrl) {
  return {
    id, label, kind: 'service', state: 'healthy', summary: `${label} healthy`, retired: false,
    address: '', presentation_url: presentationUrl, icon: null, depends_on: [hostId],
    components: [{ enabled: true, state: 'healthy', adapter: 'http', summary: `${label} HTTP healthy`, metadata: {} }],
  };
}
function workload(service, endpoints = []) {
  return {
    identity: `compose:env:stack:${service}`,
    label: service,
    environment_key: 'env',
    environment: 'Local Docker',
    environment_url: 'tcp://10.0.0.10:9001',
    compose_project: 'stack',
    compose_service: service,
    discovery_actionable: true,
    ignored: false,
    service_endpoints: endpoints,
    containers: [{ provider_id: `${service}-1`, name: service, state: 'running', health: 'healthy' }],
  };
}

const host = { id: 'host', label: 'Host', kind: 'host', address: '10.0.0.10', depends_on: [] };
const workloads = [
  workload('app'),
  workload('admin', [{ presentation_url: 'https://10.0.0.10:8443/' }]),
  workload('db'),
];
const inventory = canonicalService('host_portainer', 'Portainer', 'host', null);
inventory.components = [{
  enabled: true, state: 'healthy', adapter: 'portainer', summary: 'inventory healthy',
  metadata: { provider: 'portainer', authoritative: true, workloads },
}];
const appService = canonicalService('host_app', 'App', 'host', 'http://10.0.0.10:8080/');
const site = { id: 'site', label: 'Site', objects: [host, inventory, appService] };
context.app.state.sites = [site];

const services = context.servicesForSite(site);
const entries = context.servicePresentationEntries(services);
const stack = entries.find(entry => entry.kind === 'stack' && entry.group.project === 'stack');
assert.ok(stack, 'provider-backed Compose stack must exist');
const canonical = stack.group.services.find(service => service.id === 'host_app');
const admin = stack.group.services.find(service => service.label === 'admin');
const db = stack.group.services.find(service => service.label === 'db');
assert.equal(canonical.presentation_url, 'http://10.0.0.10:8080/');
assert.equal(admin.presentation_url, 'https://10.0.0.10:8443/');
assert.equal(db.presentation_url, null, 'provider-only child without explicit HTTP(S) evidence must not gain a link');
assert.equal(context.uiBuild9EndpointUrl({ scheme: 'tcp', host: '10.0.0.10', public_port: 9999 }), null, 'generic TCP publication must not be guessed as HTTP');
assert.match(context.serviceRow(site, canonical, '__services__'), /href="http:\/\/10\.0\.0\.10:8080\/"/);
assert.match(context.serviceRow(site, admin, '__services__'), /href="https:\/\/10\.0\.0\.10:8443\/"/);
assert.doesNotMatch(context.serviceRow(site, db, '__services__'), /href=/);

let html = context.serviceStackRow(site, stack, '__services__');
assert.doesNotMatch(html, /^<details\b[^>]*\sopen(?:\s|>)/, 'healthy stack starts collapsed');
context.app.serviceStackExpansion[stack.group.key] = true;
html = context.serviceStackRow(site, stack, '__services__');
assert.match(html, /^<details open\b/, 'explicit expanded state survives rerender');
context.app.serviceStackExpansion[stack.group.key] = false;
html = context.serviceStackRow(site, stack, '__services__');
assert.doesNotMatch(html, /^<details\b[^>]*\sopen(?:\s|>)/, 'explicit collapsed state survives rerender');
const failed = { ...stack, state: 'failed', group: { ...stack.group, state: 'failed' } };
html = context.serviceStackRow(site, failed, '__services__');
assert.match(html, /<details class="service-compose-group failed"[^>]* open/, 'failing child state still forces parent open');

let toggleHandler = null;
const detailNode = {
  open: false,
  dataset: { composeStack: stack.group.key },
  classList: ['healthy'],
  addEventListener: (name, handler) => { if (name === 'toggle') toggleHandler = handler; },
};
let linkHandler = null;
const linkNode = {
  dataset: {},
  addEventListener: (name, handler) => { if (name === 'click') linkHandler = handler; },
};
detailNodes = [detailNode];
linkNodes = [linkNode];
context.bindServiceNavigation(site);
assert.equal(typeof toggleHandler, 'function');
assert.equal(typeof linkHandler, 'function');
detailNode.open = true;
toggleHandler();
assert.equal(context.app.serviceStackExpansion[stack.group.key], true, 'operator toggle is remembered by durable stack key');
let stopped = false;
linkHandler({ stopPropagation: () => { stopped = true; } });
assert.equal(stopped, true, 'nested management link must not bubble into parent disclosure navigation');

assert.equal(typeof closeHandler, 'function');
closeHandler();
assert.equal(Object.keys(context.app.serviceStackExpansion).length, 0, 'closing drawer scopes expansion state to the current visit');

console.log('UI 1.1.1 build 9 hierarchy interaction acceptance: PASS (#206 nested management links + #207 refresh-stable stack disclosure)');
