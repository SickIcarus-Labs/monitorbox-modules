#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const source14Path=path.join(root,'sources','ui','1.1.6-build14','phase2-physical-repairs.js');
const source15Path=path.join(root,'sources','ui','1.1.7-build15','phase2-physical-repairs2.js');
const source17Path=path.join(root,'sources','ui','1.1.9-build17','phase2-physical-repairs4.js');
const source14=fs.readFileSync(source14Path,'utf8');
const source15=fs.readFileSync(source15Path,'utf8');
const source17=fs.readFileSync(source17Path,'utf8');

const context={console,URL};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(source14,context,{filename:source14Path});
vm.runInContext(source15,context,{filename:source15Path});
vm.runInContext(source17,context,{filename:source17Path});

const api=context.MonitorBoxUiPhase2Physical4;
assert.ok(api,'UI build-17 semantic reconciliation helper must be exported');

const ombi={
  id:'goliath_ombi',kind:'service',label:'Ombi',depends_on:['goliath'],
  capabilities:[{
    id:'http',providers:[{
      id:'http',adapter:'http',
      config:{url:'http://192.168.3.13:3579',method:'GET',statuses:[200]},
    }],
  }],
};
const ombiProvider={
  id:'provider-ombi',kind:'provider_workload',label:'Ombi',depends_on:['arrrrr2'],
  _provider_workload:{
    identity:'compose:arrrrr2:ombi_mysql:ombi',
    compose_service:'ombi',
    label:'ombi',
    images:['lscr.io/linuxserver/ombi:latest'],
    service_endpoints:[{host:'192.168.3.13',public_port:3579,protocol:'tcp'}],
  },
};
const dbProvider={
  id:'provider-db',kind:'provider_workload',label:'MariaDB',depends_on:['arrrrr2'],
  _provider_workload:{
    identity:'compose:arrrrr2:ombi_mysql:mariadb',
    compose_service:'mariadb',
    label:'mariadb',
    images:['mariadb:latest'],
    service_endpoints:[{host:'192.168.3.13',public_port:3306,protocol:'tcp'}],
  },
};
const scrypted={
  id:'scrypted',kind:'camera_system',label:'Scrypted',depends_on:['arrrrr2'],
  capabilities:[{
    id:'scrypted',providers:[{
      id:'scrypted',adapter:'scrypted',
      config:{host:'192.168.3.9',port:10443},
    }],
  }],
};
const scryptedProvider={
  id:'provider-scrypted',kind:'provider_workload',label:'Scrypted',depends_on:['arrrrr2'],
  _provider_workload:{
    identity:'compose:arrrrr2:scrypted:scrypted',
    compose_service:'scrypted',
    label:'scrypted',
    images:['koush/scrypted:latest'],
    service_endpoints:[{host:'192.168.3.9',public_port:10443,protocol:'tcp'}],
  },
};

const repaired=api.reconcileUniqueSemanticAuthorities(
  {objects:[ombi,scrypted]},
  {services:[ombiProvider,scryptedProvider,dbProvider]},
);
const repairedOmbi=repaired.services.find(row=>row.id==='goliath_ombi');
assert.ok(repairedOmbi,'Ombi must reconcile to its canonical logical Service');
assert.equal(repairedOmbi.presentation_url,'http://192.168.3.13:3579/');
assert.equal(repaired.services.find(row=>row.id==='provider-scrypted')?.presentation_url,undefined);
assert.equal(repaired.services.find(row=>row.id==='provider-db')?.presentation_url,undefined);

const duplicateProvider={
  ...ombiProvider,
  id:'provider-ombi-shadow',
  _provider_workload:{...ombiProvider._provider_workload,identity:'compose:other:ombi'},
};
const providerAmbiguous=api.reconcileUniqueSemanticAuthorities(
  {objects:[ombi]},
  {services:[ombiProvider,duplicateProvider]},
);
assert.equal(providerAmbiguous.services.some(row=>row.id==='goliath_ombi'),false);
assert.equal(providerAmbiguous.services.length,2);

const duplicateCanonical={
  ...ombi,
  id:'other_ombi',
  capabilities:[{
    id:'http',providers:[{
      id:'http',adapter:'http',config:{url:'https://ombi.example.test'},
    }],
  }],
};
const canonicalAmbiguous=api.reconcileUniqueSemanticAuthorities(
  {objects:[ombi,duplicateCanonical]},
  {services:[ombiProvider]},
);
assert.equal(canonicalAmbiguous.services[0].id,'provider-ombi');
assert.equal(canonicalAmbiguous.services[0].presentation_url,undefined);

assert.equal(context.MonitorBoxUiPhase2Physical2.canonicalPresentationUrl(scrypted),null);
assert.match(source17,/one-to-one in both directions/);

console.log(
  'UI Phase-2 build-17 acceptance: PASS '+
  '(unique semantic canonical/workload reconciliation + fail-closed URL authority)'
);
