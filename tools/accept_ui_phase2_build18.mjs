#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const sourcePath=path.join(root,'sources','ui','1.1.10-build18','phase2-physical-repairs5.js');
const source=fs.readFileSync(sourcePath,'utf8');

const context={console,URL};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(source,context,{filename:sourcePath});

const api=context.MonitorBoxUiPhase2Physical5;
assert.ok(api,'UI build-18 reconciliation helper must be exported');

const ombi={
  id:'goliath_ombi',kind:'service',label:'Ombi',icon:'ombi',depends_on:['goliath'],
  capabilities:[{
    id:'http',providers:[{
      id:'http',adapter:'http',config:{url:'https://ombi.sickicarus.com'},
    }],
  }],
};
const ombiProvider={
  id:'provider-ombi',kind:'provider_workload',label:'ombi',depends_on:['arrrrr2'],
  state:'healthy',underlying_state:'healthy',
  _provider_workload:{
    identity:'compose:arrrrr2:ombi_mysql:ombi',
    compose_service:'ombi',
    label:'ombi',
    project:'ombi_mysql',
    images:['lscr.io/linuxserver/ombi:latest'],
    service_endpoints:[{host:'192.168.3.9',public_port:3579,protocol:'tcp'}],
  },
};
const dbProvider={
  id:'provider-db',kind:'provider_workload',label:'MariaDB',depends_on:['arrrrr2'],
  state:'healthy',
  _provider_workload:{
    identity:'compose:arrrrr2:ombi_mysql:mariadb',
    compose_service:'mariadb',label:'mariadb',project:'ombi_mysql',
    images:['mariadb:12.3'],
    service_endpoints:[{host:'192.168.3.9',public_port:3306,protocol:'tcp'}],
  },
};
const scrypted={
  id:'scrypted',kind:'camera_system',label:'Scrypted',depends_on:['arrrrr2'],
  capabilities:[{
    id:'scrypted',providers:[{
      id:'scrypted',adapter:'scrypted',config:{host:'192.168.3.9',port:10443},
    }],
  }],
};
const scryptedProvider={
  id:'provider-scrypted',kind:'provider_workload',label:'Scrypted',depends_on:['arrrrr2'],
  state:'healthy',
  _provider_workload:{
    identity:'compose:arrrrr2:scrypted:scrypted',
    compose_service:'scrypted',label:'scrypted',project:'scrypted',
    images:['koush/scrypted:latest'],
    service_endpoints:[{host:'192.168.3.9',public_port:10443,protocol:'tcp'}],
  },
};

const repaired=api.reconcilePresentationServices(
  {objects:[ombi,scrypted]},
  {services:[ombi,ombiProvider,scryptedProvider,dbProvider]},
);
const repairedOmbi=repaired.services.find(row=>row.id==='provider-ombi');
assert.ok(repairedOmbi,'Ombi provider workload must remain the rendered row');
assert.equal(repairedOmbi.kind,'provider_workload');
assert.deepEqual(Array.from(repairedOmbi.depends_on),['arrrrr2']);
assert.equal(repairedOmbi._provider_workload.project,'ombi_mysql');
assert.equal(repairedOmbi.presentation_url,'https://ombi.sickicarus.com/');
assert.equal(repairedOmbi.label,'Ombi');
assert.equal(repairedOmbi._canonical_presentation_authority,'goliath_ombi');
assert.equal(repaired.services.some(row=>row.id==='goliath_ombi'),false);
assert.equal(repaired.services.find(row=>row.id==='provider-scrypted')?.presentation_url,undefined);
assert.equal(repaired.services.find(row=>row.id==='provider-db')?.presentation_url,undefined);

const duplicateProvider={
  ...ombiProvider,
  id:'provider-ombi-shadow',
  _provider_workload:{...ombiProvider._provider_workload,identity:'compose:other:ombi'},
};
const providerAmbiguous=api.reconcilePresentationServices(
  {objects:[ombi]},
  {services:[ombiProvider,duplicateProvider]},
);
assert.equal(providerAmbiguous.services.some(row=>row.presentation_url),false);
assert.equal(providerAmbiguous.services.length,2);

const duplicateCanonical={
  ...ombi,
  id:'other_ombi',
  capabilities:[{
    id:'http',providers:[{
      id:'http',adapter:'http',config:{url:'https://other-ombi.example.test'},
    }],
  }],
};
const canonicalAmbiguous=api.reconcilePresentationServices(
  {objects:[ombi,duplicateCanonical]},
  {services:[ombiProvider]},
);
assert.equal(canonicalAmbiguous.services[0].id,'provider-ombi');
assert.equal(canonicalAmbiguous.services[0].presentation_url,undefined);

const directCanonical={
  id:'friendly_service',kind:'service',label:'Friendly Service',depends_on:['elsewhere'],
  presentation_url:'https://friendly.example.test',
  components:[{
    adapter:'portainer',
    metadata:{provider:'portainer',identity:'compose:arrrrr2:stack:friendly'},
  }],
};
const directProvider={
  id:'provider-friendly',kind:'provider_workload',label:'opaque',depends_on:['arrrrr2'],
  _provider_workload:{
    identity:'compose:arrrrr2:stack:friendly',compose_service:'opaque',label:'opaque',images:[],
  },
};
const direct=api.reconcilePresentationServices(
  {objects:[directCanonical]},
  {services:[directProvider]},
);
assert.equal(direct.services[0].id,'provider-friendly');
assert.deepEqual(Array.from(direct.services[0].depends_on),['arrrrr2']);
assert.equal(direct.services[0].presentation_url,'https://friendly.example.test/');

assert.equal(api.canonicalPresentationUrl(scrypted),null);
assert.match(source,/provider inventory owns runtime/);
assert.match(source,/\.\.\.providerObject/);
assert.doesNotMatch(source,/\.\.\.canonical,\s*presentation_url/);

console.log(
  'UI Phase-2 build-18 acceptance: PASS '+
  '(provider topology preserved + bounded canonical presentation authority + fail-closed ambiguity)'
);
