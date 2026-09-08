#!/usr/bin/env node

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const physical14Path=path.join(root,'sources','ui','1.1.6-build14','phase2-physical-repairs.js');
const physical15Path=path.join(root,'sources','ui','1.1.7-build15','phase2-physical-repairs2.js');
const source14=fs.readFileSync(physical14Path,'utf8');
const source15=fs.readFileSync(physical15Path,'utf8');

const context={console,URL};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(source14,context,{filename:physical14Path});
vm.runInContext(source15,context,{filename:physical15Path});

const api=context.MonitorBoxUiPhase2Physical2;
assert.ok(api,'UI build-15 physical-repair helpers must be exported');

// #206: explicit canonical provider URLs are independently evidenced browser
// authority even when the object's top-level presentation_url is blank.
const ombi={
  id:'goliath_ombi',kind:'service',label:'Ombi',depends_on:['goliath'],
  capabilities:[{
    id:'http',providers:[{
      id:'http',adapter:'http',
      config:{url:'http://192.168.3.13:3579',method:'GET',statuses:[200]},
    }],
  }],
};
assert.equal(api.canonicalPresentationUrl(ombi),'http://192.168.3.13:3579/');

const scrypted={
  id:'scrypted',kind:'camera_system',label:'Scrypted',depends_on:['arrrrr2'],
  capabilities:[{
    id:'scrypted',providers:[{
      id:'scrypted',adapter:'scrypted',
      config:{base_url:'https://192.168.3.9:10443'},
    }],
  }],
};
assert.equal(api.canonicalPresentationUrl(scrypted),'https://192.168.3.9:10443/');

const ambiguousAuthority={
  id:'ambiguous',kind:'service',label:'Ambiguous',
  capabilities:[{
    id:'http',providers:[
      {id:'one',adapter:'http',config:{url:'https://10.0.0.1:1001'}},
      {id:'two',adapter:'http',config:{url:'https://10.0.0.1:1002'}},
    ],
  }],
};
assert.equal(api.canonicalPresentationUrl(ambiguousAuthority),null);

const ombiProvider={
  id:'provider-ombi',kind:'provider_workload',label:'Ombi',depends_on:['goliath'],
  _provider_workload:{
    identity:'compose:goliath:ombi_mysql:ombi',
    compose_service:'ombi',
    label:'ombi',
    images:['lscr.io/linuxserver/ombi:latest'],
    service_endpoints:[{host:'192.168.3.13',public_port:3579,protocol:'tcp'}],
  },
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
const dbProvider={
  id:'provider-db',kind:'provider_workload',label:'db',depends_on:['goliath'],
  _provider_workload:{
    identity:'compose:goliath:ombi_mysql:db',
    compose_service:'db',
    images:['mariadb:latest'],
    service_endpoints:[{host:'192.168.3.13',public_port:3306,protocol:'tcp'}],
  },
};
const repaired=api.reconcilePresentationServices(
  {objects:[ombi,scrypted]},
  {services:[ombiProvider,scryptedProvider,dbProvider]},
);
assert.equal(
  repaired.services.find(row=>row.id==='goliath_ombi').presentation_url,
  'http://192.168.3.13:3579/',
);
assert.equal(
  repaired.services.find(row=>row.id==='scrypted').presentation_url,
  'https://192.168.3.9:10443/',
);
assert.equal(repaired.services.find(row=>row.id==='provider-db').presentation_url,undefined);
assert.equal(api.safeHttpUrl('tcp://192.168.3.13:3306'),null);

// #164: passive rendering may not contaminate a transaction. An untouched HTTP
// provider is restored from canonical baseline while the explicitly touched
// Portainer provider retains its environment_ids edit.
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
const working=JSON.parse(JSON.stringify(current));
working.sites[0].objects[0].capabilities[0].providers[0].config.__passive_ui_noise=true;
working.sites[0].objects[1].capabilities[0].providers[0].config.environment_ids=[3,6,7];

const touched=new Set(['broadleaf/portainer/docker_inventory/portainer']);
assert.equal(api.restoreUntouchedProviderBaselines(current,working,touched),1);
assert.equal(
  '__passive_ui_noise' in working.sites[0].objects[0].capabilities[0].providers[0].config,
  false,
);
assert.deepEqual(
  Array.from(working.sites[0].objects[1].capabilities[0].providers[0].config.environment_ids),
  [3,6,7],
);

// A real operator edit to the HTTP provider is never silently reverted.
const workingTouched=JSON.parse(JSON.stringify(current));
workingTouched.sites[0].objects[0].capabilities[0].providers[0].timeout_seconds=9;
assert.equal(
  api.restoreUntouchedProviderBaselines(
    current,
    workingTouched,
    new Set(['broadleaf/web_admin_interface/http/http']),
  ),
  0,
);
assert.equal(
  workingTouched.sites[0].objects[0].capabilities[0].providers[0].timeout_seconds,
  9,
);

assert.match(source15,/addEventListener\('click',\(\)=>\{/);
assert.match(source15,/restoreUntouchedProviderBaselines\(current,working,touchedProviders\)/);
assert.match(source15,/config\[key\]/);
assert.ok(!source15.includes('http://host:port'));
assert.ok(!source15.includes('https://host:port'));

console.log(
  'UI Phase-2 build-15 acceptance: PASS '+
  '(Advanced provider transaction isolation + explicit canonical provider URL reconciliation)'
);
