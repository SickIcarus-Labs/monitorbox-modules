#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const sourcePath=path.join(root,'sources','ui','1.1.12-build20','phase3-local-control.js');
const cssPath=path.join(root,'sources','ui','1.1.12-build20','phase3-local-control.css');
const dashboardPath=path.join(root,'sources','ui','1.1.3-build11','base','dashboard.js');
const debugPath=path.join(root,'sources','ui','1.1.3-build11','base','global-debug.js');
const builderPath=path.join(root,'tools','build_first_party_ui_build20.py');

const source=fs.readFileSync(sourcePath,'utf8');
const css=fs.readFileSync(cssPath,'utf8');
const dashboard=fs.readFileSync(dashboardPath,'utf8');
const debug=fs.readFileSync(debugPath,'utf8');
const builder=fs.readFileSync(builderPath,'utf8');

const storage=new Map();
const context={
  console,
  URL,
  Date,
  location:{href:'https://monitor.sickicarus.com/',origin:'https://monitor.sickicarus.com'},
  window:{
    localStorage:{
      getItem(key){return storage.get(key)??null;},
      setItem(key,value){storage.set(key,String(value));},
      removeItem(key){storage.delete(key);},
    },
  },
};
context.window.window=context.window;
context.window.location=context.location;
context.globalThis=context;
vm.createContext(context);
vm.runInContext(source,context,{filename:sourcePath});
const api=context.window.MonitorBoxUiPhase3LocalControl;
assert.ok(api,'Phase-3 local-control helper must be exported');
assert.equal(api.safeHttpUrl('http://192.168.3.5:8080/path?q=1#x'),'http://192.168.3.5:8080');
assert.equal(api.safeHttpUrl('javascript:alert(1)'),'');
assert.equal(api.staleAgeText(1_000_000,1_045_000),'45s ago');
assert.equal(api.staleAgeText(1_000_000,1_125_000),'2m ago');

assert.match(source,/\/api\/v2\/config\/local-access/);
assert.match(source,/descriptor\?\.available===true\?safeHttpUrl\(descriptor\.local_url\)/);
assert.match(source,/Connection path unavailable/);
assert.match(source,/controller health is not proven failed/);
assert.match(source,/Last canonical state was/);
assert.match(source,/recoveryBanner\(cachedLocalUrl\(\)\)/);
assert.match(source,/window\.isSecureContext&&navigator\.clipboard\?\.writeText/);
assert.match(source,/const snapshot=String\(log\.textContent\|\|''\)/);
assert.match(source,/Frozen debug snapshot/);
assert.match(source,/This snapshot will not refresh while you copy it/);

// Recovery is navigation only: the cached local origin must never become an API
// fetch target. Cross-origin failover would introduce CORS/mixed-content/security
// authority that #253 explicitly does not own.
assert.doesNotMatch(source,/fetch\s*\(\s*cachedLocalUrl/);
assert.doesNotMatch(source,/fetch\s*\(\s*url\s*\+/);
assert.doesNotMatch(source,/location\.(?:assign|replace)\s*\(/);

// The old base wording is intentionally overridden rather than deleted from
// historical assets; cards/state remain in the DOM while transport is unknown.
assert.match(dashboard,/MonitorBox is unreachable/);
assert.match(source,/renderOffline=renderPathUnavailable/);
assert.doesNotMatch(source,/app\.state\s*=\s*null/);

// Insecure Clipboard fallback must not retain the old live-DOM selection race.
assert.match(debug,/range\.selectNodeContents\(log\)/);
assert.doesNotMatch(source,/selectNodeContents\s*\(\s*log\s*\)/);
assert.match(css,/\.debug-copy-fallback textarea/);
assert.match(css,/min-height:\s*44px/);
assert.match(css,/\.mb-local-recovery/);

// Build 20 must load after build-19 dashboard repair and carry its CSS only on
// the normal dashboard surface.
assert.match(builder,/previous\._build19_assets/);
assert.match(builder,/_PHASE3_LOCAL_SCRIPT/);
assert.match(builder,/request\.path == "\/"/);

console.log(
  'UI Phase-3 build-20 acceptance: PASS '+
  '(path-loss semantics + stale state + navigation-only recovery + frozen copy fallback)'
);
