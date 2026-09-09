#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const sourcePath=path.join(root,'sources','ui','1.1.11-build19','phase3-p1.js');
const cssPath=path.join(root,'sources','ui','1.1.11-build19','phase3-p1.css');
const dashboardPath=path.join(root,'sources','ui','1.1.3-build11','base','dashboard.js');
const source=fs.readFileSync(sourcePath,'utf8');
const css=fs.readFileSync(cssPath,'utf8');
const dashboard=fs.readFileSync(dashboardPath,'utf8');

function button(checkId){
  const attributes={};
  return {
    dataset:{runCheck:checkId},
    title:'',
    setAttribute(name,value){attributes[name]=value;},
    getAttribute(name){return attributes[name];},
  };
}

const derived=button('broadleaf_unifi_inventory:unifi_vpn_turnberry');
const direct=button('goliath_http');
const components=[
  {
    id:'broadleaf_unifi_inventory:unifi_vpn_turnberry',
    label:'Turnberry VPN',
    metadata:{source_check_id:'broadleaf_unifi_inventory'},
  },
  {
    id:'goliath_http',
    label:'Goliath HTTP',
    metadata:{},
  },
];
let drawerRenders=0;
const context={
  console,
  app:{
    selected:{siteId:'broadleaf',objectId:'turnberry_vpn'},
    state:{sites:[]},
  },
  findObject(){return {object:{components}};},
  renderDrawer(){drawerRenders++;},
  document:{
    readyState:'complete',
    querySelectorAll(selector){
      assert.equal(selector,'#drawer-body [data-run-check]');
      return [derived,direct];
    },
  },
};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(source,context,{filename:sourcePath});

const api=context.MonitorBoxUiPhase3P1;
assert.ok(api,'UI Phase-3 helper must be exported');
assert.equal(api.sourceCheckId(components[0]),'broadleaf_unifi_inventory');
assert.equal(api.sourceCheckId(components[1]),'');
assert.equal(derived.dataset.runCheck,'broadleaf_unifi_inventory');
assert.equal(derived.dataset.derivedCheck,'true');
assert.equal(derived.title,'Refresh owning provider check');
assert.equal(derived.getAttribute('aria-label'),'Check Turnberry VPN now');
assert.equal(direct.dataset.runCheck,'goliath_http','direct runnable checks must remain unchanged');

// The installed wrapper must repeat the provenance repair after every drawer
// re-render, because loadState() re-projects current state after the operation.
derived.dataset.runCheck='broadleaf_unifi_inventory:unifi_vpn_turnberry';
context.renderDrawer();
assert.equal(drawerRenders,1);
assert.equal(derived.dataset.runCheck,'broadleaf_unifi_inventory');

assert.doesNotMatch(source,/split\s*\(\s*['"]:/,'synthetic ids must not be parsed for execution provenance');
assert.match(dashboard,/node\.dataset\.runCheck/,'base click handler must resolve the patched dataset at click time');
assert.match(dashboard,/await loadState\(\{quiet:true\}\)/,'fresh operation completion must reload/re-project controller state');
assert.match(css,/discovery-coverage-section > summary::before/);
assert.match(css,/discovery-coverage-section\[open\] > summary::before/);
assert.match(css,/prefers-reduced-motion/);

console.log(
  'UI Phase-3 build-19 acceptance: PASS '+
  '(derived action provenance + direct-check preservation + disclosure-state CSS)'
);
