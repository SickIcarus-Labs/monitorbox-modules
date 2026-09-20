#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const rank = state => ({healthy:0,planned:0,disabled:0,unknown:1,degraded:2,failed:3})[state] ?? 1;
const context = {
  console,
  stateRank: rank,
  parityObjects: site => site?.objects || [],
};
context.globalThis = context;

const aggregateSource = fs.readFileSync(
  new URL("../sources/ui/1.3.2-build36/aggregate-evidence.js", import.meta.url),
  "utf8",
);
vm.runInNewContext(aggregateSource, context, {filename:"aggregate-evidence.js"});
const api = context.MonitorBoxAggregateEvidence;
assert.ok(api, "aggregate evidence API exported");

const healthyAggregate = {
  id: "semantic-fabric",
  kind: "semantic_aggregate",
  state: "healthy",
  summary: "Healthy",
  components: Array.from({length:6}, (_, index) => ({
    id: `check-${index + 1}`,
    enabled: true,
    state: "healthy",
  })),
};
assert.equal(api.directEvidence(healthyAggregate).length, 6);
assert.equal(api.evidenceSummary(healthyAggregate), "6 checks · 6 healthy");

const mixedAggregate = {
  id: "semantic-anything",
  kind: "logical_group",
  state: "degraded",
  components: [
    {id:"a", enabled:true, state:"healthy"},
    {id:"b", enabled:true, state:"healthy"},
    {id:"c", enabled:true, state:"degraded"},
    {id:"ignored", enabled:false, state:"failed"},
  ],
};
assert.equal(api.directEvidence(mixedAggregate).length, 3);
assert.equal(api.evidenceSummary(mixedAggregate), "3 checks · 2 healthy · 1 need attention");

// The legacy Network compatibility seam must select semantic network-device
// children without consulting provider/adapter metadata.
const networkSource = fs.readFileSync(
  new URL("../sources/ui/1.3.2-build36/network-children.js", import.meta.url),
  "utf8",
);
vm.runInNewContext(networkSource, context, {filename:"network-children.js"});
const children = context.parityNetworkChildren({
  objects: [
    {id:"switch-a", label:"A", kind:"network_device", state:"healthy", components:[{adapter:"alpha"}]},
    {id:"switch-b", label:"B", kind:"network_device", state:"degraded", components:[]},
    {id:"retired", label:"C", kind:"network_device", state:"failed", retired:true},
    {id:"remote", label:"D", kind:"remote_site", state:"failed"},
  ],
});
assert.deepEqual(Array.from(children, item => item.id), ["switch-b", "switch-a"]);

console.log("UI build36 provider-blind aggregate fixtures: PASS");
