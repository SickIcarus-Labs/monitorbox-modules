#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'sources', 'ui', '1.1.4-build12', 'modules-render.js');
const source = fs.readFileSync(sourcePath, 'utf8');

assert.equal(source.includes('com.sickicarus.monitorbox.'), false, 'renderer must stay module-ID agnostic');
assert.match(source, /Array\.isArray\(module\.actions\)/, 'lifecycle actions must come from Core authority');
assert.doesNotMatch(source, /semver|localeCompare|split\(['"]\.['"]\)/i, 'UI must not reimplement semantic precedence');

const sandbox = {
  text(value, fallback = '—') {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
  },
};
vm.createContext(sandbox);
vm.runInContext(
  source + '\nthis.__helpers = { semanticRelease, exactRelease, runtimeApiLabel, supportFingerprint, candidateStatus, updatePresentation };',
  sandbox,
  { filename: sourcePath },
);
const h = sandbox.__helpers;

function moduleState(installed, available, previous = null) {
  return {
    module_id: 'com.example.module',
    installed,
    available,
    previous,
    actions: available && available.update_available && available.compatible !== false ? ['update'] : [],
  };
}

const historical = { version: '1.0.0', build: 5, requires_runtime_api: '>=1 <2' };
assert.equal(h.semanticRelease(historical), 'v1.0.0');
assert.equal(h.exactRelease(historical), 'v1.0.0 · build 5');
assert.equal(h.runtimeApiLabel(historical.requires_runtime_api), '1');
assert.equal(h.runtimeApiLabel('>=2 <4'), '>=2 <4');
assert.equal(h.supportFingerprint(moduleState(historical, null)), 'com.example.module=1.0.0+5');

const patch = moduleState(
  { version: '1.0.0', build: 5 },
  { version: '1.0.1', build: 6, compatible: true, update_available: true },
);
assert.equal(h.updatePresentation(patch), 'v1.0.0 → v1.0.1');
assert.equal(h.candidateStatus(patch), 'Compatible');

const feature = moduleState(
  { version: '1.0.1', build: 6 },
  { version: '1.1.0', build: 7, compatible: true, update_available: true },
);
assert.equal(h.updatePresentation(feature), 'v1.0.1 → v1.1.0');

const rebuild = moduleState(
  { version: '1.1.0', build: 7 },
  { version: '1.1.0', build: 8, compatible: true, update_available: true },
);
assert.equal(
  h.updatePresentation(rebuild),
  'Packaging/rebuild · v1.1.0 · build 7 → build 8',
);

const blocked = moduleState(
  { version: '1.1.0', build: 8 },
  {
    version: '2.0.0',
    build: 9,
    compatible: false,
    reason: 'module requires Core >=3.0.0',
    update_available: false,
  },
);
assert.equal(h.candidateStatus(blocked), 'Blocked · module requires Core >=3.0.0');
assert.equal(
  h.updatePresentation(blocked),
  'Blocked v2.0.0 · build 9 · module requires Core >=3.0.0',
);
assert.deepEqual(blocked.actions, [], 'blocked candidate must not acquire an update action in the UI');

const rollback = moduleState(
  { version: '1.1.0', build: 8 },
  null,
  { version: '1.0.1', build: 6, artifact_identity: 'sha256:previous' },
);
assert.equal(h.exactRelease(rollback.previous), 'v1.0.1 · build 6');
assert.equal(h.supportFingerprint(rollback), 'com.example.module=1.1.0+8');

console.log('UI semantic release identity acceptance: PASS');
