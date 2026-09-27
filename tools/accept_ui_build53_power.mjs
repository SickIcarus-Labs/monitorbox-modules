#!/usr/bin/env node
// UI53: one semantic UPS adapter; native card and picker must agree.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const asset=n=>fs.readFileSync(new URL(
  '../sources/ui/1.17.0-build53/'+n,import.meta.url),'utf8');
vm.runInThisContext(asset('card-item-registry.js'),{filename:'card-item-registry.js'});
const reg=globalThis.MonitorBoxCardItems;
const component=(metrics,metadata={},units={})=>({id:'ups.check',label:'UPS check',
  state:'healthy',metrics,metadata,metric_units:units});
const nut={id:'networkups',label:'Network UPS',kind:'ups',state:'healthy',
  components:[component({
    'battery.charge':100,'battery.runtime':1500,'ups.load':28,
    'input.voltage':116,'battery.voltage':26.8,'output.voltage':117,
    'driver.parameter.pollfreq':5,'driver.parameter.pollinterval':2,
    'driver.parameter.productid':1234,'driver.parameter.vendorid':99,
    'driver.version.internal':2,'ups.delay.shutdown':30,
    'ups.delay.start':30,'ups.productid':324,'ups.realpower.nominal':1500,
    'battery.charge.low':15,'battery.charge.warning':22,
    'battery.runtime.low':180,'battery.voltage.nominal':24,
    'input.voltage.nominal':120,'output.voltage.nominal':120,
    'driver.debug':0,'device.serial':3,'device.mfr':5,
    'ups.load.warning':90,'ups.load.low':3,'ups.vendorid':42,
  },{power_source:'utility','ups.status':'OL'})]};
const vendor={id:'vendor',label:'Second UPS',kind:'ups',state:'healthy',
  components:[component({
    battery_soc_percent:86,battery_runtime_minutes:23,
    output_load_percent:37,input_voltage_v:121,
  })]};
const declared={id:'mapped',label:'Third-party UPS',kind:'ups',state:'healthy',
  components:[component({socValue:94,estimatedMinutes:19,drawRatio:16,
    lineVolts:118,unidentifiedTelemetry:4},{
    dashboard_metric_roles:{
      charge:{metric:'socValue',unit:'%'},
      runtime:{metric:'estimatedMinutes',unit:'minutes'},
      load:{metric:'drawRatio',unit:'%'},
      inputVoltage:{metric:'lineVolts',unit:'V'},
    },
  })]};
const unsafe={id:'unsafe',label:'Ambiguous UPS',kind:'ups',
  components:[component({estimated_runtime:37,chargeValue:15,
    'battery.charge.warning':20,input_voltage_v:-12,
    battery_runtime_seconds:-1,ups_load_percent:135})]};
const site={id:'arbitrary-site',objects:[nut,vendor,declared,unsafe],cards:[]};
const roles=reg.powerCapabilities(nut);
assert.deepEqual([roles.charge?.value,roles.runtime?.value,
  roles.load?.value,roles.inputVoltage?.value],[100,1500,28,116]);
assert.deepEqual([roles.charge?.unit,roles.runtime?.unit,
  roles.load?.unit,roles.inputVoltage?.unit],['%','s','%','V']);
assert.deepEqual(Object.keys(reg.powerCapabilities(vendor)),
  ['charge','runtime','load','inputVoltage']);
assert.equal(reg.powerCapabilities(vendor).runtime.value,1380);
assert.equal(reg.powerCapabilities(declared).charge.value,94);
assert.equal(reg.powerCapabilities(declared).runtime.value,1140);
assert.equal(reg.powerCapabilities(declared).load.value,16);
assert.equal(reg.powerCapabilities(declared).inputVoltage.value,118);
assert.deepEqual(Object.keys(reg.powerCapabilities(unsafe)),[],
  'Do not invent units, accept out-of-range percentages or choose thresholds');
const catalog=reg.catalog(site);
const power=catalog.groups.find(g=>g.id==='power');
assert.equal(power.sources.length,4);
const src=power.sources.find(s=>s.sourceId==='networkups');
assert.equal(src.items.filter(i=>i.powerTier==='recommended').length,4);
assert.equal(src.items.filter(i=>i.powerTier==='advanced').length>=16,true,
  'Raw driver/config/threshold telemetry should be Advanced');
for(const role of ['charge','runtime','load','inputVoltage']){
  const item=src.items.find(x=>x.powerRole===role);
  assert.ok(item,role+' missing from recommended picker');
  assert.equal(item.key,roles[role].key);
  assert.equal(reg.display(site,item.key,catalog.items).available,true);
}
const vendorRuntime=reg.display(site,
  reg.powerCapabilities(vendor).runtime.key,catalog.items);
assert.equal(vendorRuntime.value,1380,
  'A selected vendor runtime in minutes must display standardized seconds');
assert.equal(vendorRuntime.unit,'s');
const raw=src.items.find(i=>i.metricKey==='driver.parameter.pollfreq');
assert.equal(raw.powerTier,'advanced');
assert.equal(reg.display(site,raw.key,catalog.items).value,5,
  'Advanced is a visual filter, never removal of a raw monitored metric');
const other=src.items.find(i=>i.metricKey==='battery.voltage');
assert.equal(other.powerTier,'other','Genuine secondary readings remain selectable');
const favorite=reg.makeKey('object','networkups','metric','ups.check','battery.charge');
assert.equal(reg.display(site,favorite,catalog.items).label,'Battery charge');
const unknown={id:'none',label:'Offline UPS',kind:'ups',components:[{
  id:'ups.check',state:'unknown',metrics:{},
}]};
assert.deepEqual(reg.powerCapabilities(unknown),{},
  'No synthetic values when an UPS has not reported numeric readings');
console.log('UI53 Power: 27 raw UPS metrics preserved, 4 honest native/recommended roles, '
  +'third-party names/units, Advanced gating metadata and saved raw references PASS');
