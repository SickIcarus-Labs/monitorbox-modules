#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const site = {
  id: "broadleaf",
  objects: [
    {id:"monitor", label:"MonitorBox", kind:"host", state:"healthy"},
    {id:"arrrrr2", label:"Arrrrr2", kind:"host", state:"healthy"},
    {id:"goliath", label:"Goliath", kind:"host", state:"healthy"},
    {id:"switch-a", label:"Switch", kind:"network_device", state:"healthy"},
    {id:"portainer", label:"Docker via Portainer", kind:"integration", state:"healthy"},
  ],
  cards: [
    {id:"internet", family:"internet", kind:"dashboard_card", label:"Internet", state:"healthy"},
    {id:"network", family:"network", kind:"dashboard_card", label:"Network", state:"healthy"},
    {id:"cameras", family:"cameras", kind:"dashboard_card", label:"Cameras", state:"healthy"},
    {id:"power", family:"power", kind:"dashboard_card", label:"Power", state:"healthy"},
    {id:"services", family:"services", kind:"dashboard_card", label:"Services", state:"healthy"},
  ],
};

const context = {
  console,
  app: {state: {sites: [site]}},
  parityObjects: value => value?.objects || [],
  findObject: (siteId, objectId) => {
    const foundSite = siteId === site.id ? site : undefined;
    return {site: foundSite, object: foundSite?.objects?.find(item => item.id === objectId)};
  },
  renderActions: (_site, object) => `actions:${object.id}`,
  parityCoreObjects: value => value?.objects || [],
};
context.globalThis = context;

const source = fs.readFileSync(
  new URL("../sources/ui/1.4.0-build38/card-projection.js", import.meta.url),
  "utf8",
);
vm.runInNewContext(source, context, {filename:"card-projection.js"});

const api = context.MonitorBoxCardProjection;
assert.ok(api, "card projection API exported");

const core = Array.from(api.projectedCoreObjects(site), item => item.id);
assert.deepEqual(
  core,
  ["arrrrr2", "goliath", "internet", "network", "cameras", "power"],
);
assert.ok(!core.includes("switch-a"), "network devices do not become default host cards");
assert.ok(!core.includes("portainer"), "integration objects do not become infrastructure cards");
assert.ok(!core.includes("services"), "Services retains its dedicated summary surface");

const projected = context.findObject("broadleaf", "network");
assert.equal(projected.object?.kind, "dashboard_card");
assert.equal(projected.object?.id, "network");

const host = context.findObject("broadleaf", "arrrrr2");
assert.equal(host.object?.kind, "host");

assert.equal(context.renderActions(site, projected.object), "");
assert.equal(context.renderActions(site, host.object), "actions:arrrrr2");

const sourceLower = source.toLowerCase();
for (const forbidden of ["unifi", "scrypted", "portainer", "nut", "docker"]) {
  assert.ok(!sourceLower.includes(forbidden), `provider/product coupling: ${forbidden}`);
}

console.log("UI build38 projected-card acceptance: PASS");
