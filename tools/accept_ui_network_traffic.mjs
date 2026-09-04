#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const patch = fs.readFileSync(new URL('../sources/ui/1.1.1-build9/network-traffic-presentation.js', import.meta.url), 'utf8');
let boundGrid = null;
let renderCount = 0;
const section = { classList: { add(){}, remove(){} } };
const grid = { innerHTML: '' };
const context = vm.createContext({
  liveChart: series => `<chart kind="${series.kind}" subject="${series.traffic_subject||''}"></chart>`,
  trafficAttributionHtml: payload => payload?.flows?.length ? 'BASE_FLOWS' : 'BASE_EMPTY_GATEWAY',
  liveOverviewRank: series => series.traffic_subject === 'busiest' ? 20000 : 100,
  bindTrafficCards: node => { boundGrid = node; },
  trafficSeriesIdentity: series => series?.subject || null,
  selectedTrafficSeries: () => ({ subject: { ip: '10.0.0.20' } }),
  trafficIdentityKey: identity => identity?.ip || '',
  renderTrafficDrawer: () => { renderCount += 1; },
  api: async () => { throw new Error('traffic-details capability unavailable'); },
  app: {
    liveTelemetry: { series: [] },
    liveTrafficSelection: null,
    liveTrafficRequest: 0,
    liveTrafficPayload: null,
  },
  document: {
    querySelector: selector => selector === '#live-overview' ? section : selector === '#live-overview-grid' ? grid : null,
  },
  esc: value => String(value),
  encodeURIComponent,
  Number,
  String,
  Date,
  console,
});
vm.runInContext(patch, context, { filename: 'network-traffic-presentation.js' });

const validEmpty = context.trafficAttributionHtml({
  attribution_available: true,
  flows: [],
  scope: 'Gateway-visible routed traffic only',
});
assert.equal(validEmpty, 'BASE_EMPTY_GATEWAY', 'valid zero-flow evidence remains an empty gateway-flow result');
const unavailable = context.trafficAttributionHtml({
  attribution_available: false,
  error: 'unifi_network:traffic-details unavailable',
});
assert.match(unavailable, /traffic-detail provider or its configuration is unavailable/);
assert.match(unavailable, /Throughput above remains valid from counter telemetry/);
assert.match(unavailable, /Provider\/configuration error:/);
assert.doesNotMatch(unavailable, /BASE_EMPTY_GATEWAY/, 'provider failure must not masquerade as valid empty flow evidence');

context.app.liveTelemetry.series = [
  {
    id: 'host-throughput', label: 'Host', kind: 'counter_pair', traffic_subject: 'host',
    points: [{ valid: true, rx: 100, tx: 200 }],
  },
  {
    id: 'busiest', label: 'Busiest client', kind: 'legacy_pair', traffic_subject: 'busiest',
    points: [{ valid: true, rx: 300, tx: 400 }],
  },
];
context.renderLiveOverview();
assert.match(grid.innerHTML, /subject="host"/);
assert.match(grid.innerHTML, /subject="busiest"/, 'valid busiest-client RX/TX series must be presented');
assert.equal(boundGrid, grid);

const selection = { siteId: 'broadleaf', subject: 'host', lastFetchAt: 0 };
context.app.liveTrafficSelection = selection;
await context.refreshTrafficAttribution(selection);
assert.equal(context.app.liveTrafficPayload.attribution_available, false);
assert.match(context.app.liveTrafficPayload.error, /traffic-details capability unavailable/);
assert.equal(renderCount, 1, 'provider failure updates attribution presentation without invalidating the counter series');

console.log('UI 1.1.1 build 9 traffic acceptance: PASS (#156 counter/flow/provider separation + busiest-client presentation)');
