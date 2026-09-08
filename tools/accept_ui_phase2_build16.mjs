#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const source15Path=path.join(root,'sources','ui','1.1.7-build15','phase2-physical-repairs2.js');
const source16Path=path.join(root,'sources','ui','1.1.8-build16','phase2-physical-repairs3.js');
const source15=fs.readFileSync(source15Path,'utf8');
const source16=fs.readFileSync(source16Path,'utf8');

const context={console,URL};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(source15,context,{filename:source15Path});
vm.runInContext(source16,context,{filename:source16Path});

const prior=context.MonitorBoxUiPhase2Physical2;
const api=context.MonitorBoxUiPhase2Physical3;
assert.ok(prior,'UI build-15 provider restoration helper must be present');
assert.ok(api,'UI build-16 pre-serialization helper must be exported');

const current={
  sites:[{
    id:'broadleaf',
    objects:[
      {
        id:'web_admin_interface',
        capabilities:[{
          id:'http',
          providers:[{
            id:'http',adapter:'http',enabled:true,interval_seconds:30,timeout_seconds:5,
            config:{url:'https://192.168.3.13:443',method:'GET',statuses:[200],follow_redirects:true,verify_tls:false},
          }],
        }],
      },
      {
        id:'portainer',
        capabilities:[{
          id:'docker_inventory',
          providers:[{
            id:'portainer',adapter:'portainer',
            config:{base_url:'https://192.168.3.13:9443',operation:'inventory'},
          }],
        }],
      },
    ],
  }],
};

// Physical regression: no operator edit must restore the Web Admin provider to
// the canonical baseline before the frozen onclick serializes the candidate.
const noOp=JSON.parse(JSON.stringify(current));
noOp.sites[0].objects[0].capabilities[0].providers[0].config.__passive_ui_noise=true;
assert.equal(api.restoreBeforeNativeValidate(current,noOp,new Set()),1);
assert.deepEqual(noOp,current);

// #164: a Portainer environment-scope edit survives while unrelated Web Admin
// drift is removed. This must produce exactly the one intended provider delta.
const scoped=JSON.parse(JSON.stringify(current));
scoped.sites[0].objects[0].capabilities[0].providers[0].config.__passive_ui_noise=true;
scoped.sites[0].objects[1].capabilities[0].providers[0].config.environment_ids=[3,6,7];
const touched=new Set(['broadleaf/portainer/docker_inventory/portainer']);
assert.equal(api.restoreBeforeNativeValidate(current,scoped,touched),1);
assert.equal(
  '__passive_ui_noise' in scoped.sites[0].objects[0].capabilities[0].providers[0].config,
  false,
);
assert.deepEqual(
  Array.from(scoped.sites[0].objects[1].capabilities[0].providers[0].config.environment_ids),
  [3,6,7],
);

// Event-order contract: restoration must be installed on an ancestor capture
// listener. A target listener on #validate can run after the already-registered
// native onclick has begun serializing the working document.
assert.match(source16,/document\.addEventListener\('click',event=>\{/);
assert.match(source16,/target\?\.closest\?\.\('#validate'\)/);
assert.match(source16,/restoreBeforeNativeValidate\(current,working,touchedProviders\)/);
assert.match(source16,/\},true\);/);
assert.doesNotMatch(source16,/validateButton\?\.addEventListener\('click'/);
assert.match(source16,/document\.addEventListener\('change',event=>\{/);
assert.match(source16,/data-phase2-provider-key/);

console.log(
  'UI Phase-2 build-16 acceptance: PASS '+
  '(document-capture pre-serialization restore + provider-scoped operator intent)'
);
