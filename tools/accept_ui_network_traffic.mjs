#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const patch = fs.readFileSync(new URL('../sources/ui/1.1.1-build9/network-traffic-presentation.js', import.meta.url), 'utf8');
assert.doesNotMatch(patch, /uiBuild9BusiestCounterSeries|renderLiveOverview\s*=|liveChart\s*=/,
  'build 9 must not coerce busiest telemetry or replace the accepted baseline chart renderer');

let renderCount = 0;
const context = vm.createContext({
  trafficAttributionHtml: payload => payload?.flows?.length ? 'BASE_FLOWS' : 'BASE_EMPTY_GATEWAY',
  trafficSeriesIdentity: series => series?.subject || null,
  selectedTrafficSeries: () => ({ subject: { ip: '10.0.0.20' } }),
  trafficIdentityKey: identity => identity?.ip || '',
  renderTrafficDrawer: () => { renderCount += 1; },
  api: async () => { throw new Error('traffic-details capability unavailable'); },
  app: {
    liveTrafficSelection: null,
    liveTrafficRequest: 0,
    liveTrafficPayload: null,
  },
  esc: value => String(value),
  encodeURIComponent,
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

const selection = { siteId: 'broadleaf', subject: 'host', lastFetchAt: 0 };
context.app.liveTrafficSelection = selection;
await context.refreshTrafficAttribution(selection);
assert.equal(context.app.liveTrafficPayload.attribution_available, false);
assert.match(context.app.liveTrafficPayload.error, /traffic-details capability unavailable/);
assert.equal(renderCount, 1, 'provider failure updates attribution presentation without invalidating counter telemetry');

console.log('UI 1.1.1 build 9 traffic acceptance: PASS (#156 counter/flow/provider separation; baseline chart renderer preserved)');
