'use strict';

// UI 1.1.2 build 10: physical Broad Leaf corrections for provider-backed
// service navigation and refresh-stable Compose disclosure state.
//
// #206: reconcile an unmatched canonical service to a provider-only workload
// only when exact service identity plus bounded host/endpoint evidence yields a
// unique result. This preserves the canonical presentation URL without guessing
// that arbitrary published TCP ports are HTTP.
// #207: encode the durable environment+project key before putting it in HTML;
// the raw hierarchy key contains a NUL separator which browsers normalize.

const uiBuild10BaseProviderPresentationModel=providerPresentationModel;
const uiBuild10BaseServiceStackRow=serviceStackRow;

function uiBuild10CanonicalKeys(service){
  const keys=new Set();
  const label=providerNormalizeToken(service?.label);
  if(label)keys.add(label);
  const id=String(service?.id||'');
  for(const hostId of service?.depends_on||[]){
    const prefix=`${hostId}_`;
    if(id.startsWith(prefix)){
      const suffix=providerNormalizeToken(id.slice(prefix.length));
      if(suffix)keys.add(suffix);
    }
  }
  return keys;
}

function uiBuild10PresentationEndpoint(service){
  const safe=uiBuild9SafeHttpUrl(service?.presentation_url);
  if(!safe)return null;
  try{
    const parsed=new URL(safe);
    const host=String(parsed.hostname||'').trim().toLowerCase().replace(/^\[|\]$/g,'');
    const port=Number(parsed.port||(parsed.protocol==='https:'?443:80));
    return host&&Number.isInteger(port)?{host,port}:null;
  }catch(_error){return null;}
}

function uiBuild10WorkloadEndpointMatch(providerObject,endpoint){
  if(!endpoint)return false;
  for(const item of providerObject?._provider_workload?.service_endpoints||[]){
    const host=providerExactAddress(item?.host)||String(item?.host||'').trim().toLowerCase().replace(/^\[|\]$/g,'');
    const port=Number(item?.public_port||item?.port);
    if(host===endpoint.host&&port===endpoint.port)return true;
  }
  return false;
}

function uiBuild10SharesOwner(canonical,providerObject){
  const providerHosts=new Set(providerObject?.depends_on||[]);
  return(canonical?.depends_on||[]).some(hostId=>providerHosts.has(hostId));
}

function uiBuild10ReconcileCandidate(canonical,providerObject){
  if(providerObject?.kind!=='provider_workload')return null;
  const workloadKey=providerWorkloadKey(providerObject._provider_workload);
  if(!workloadKey||!uiBuild10CanonicalKeys(canonical).has(workloadKey))return null;
  const endpointMatch=uiBuild10WorkloadEndpointMatch(
    providerObject,
    uiBuild10PresentationEndpoint(canonical),
  );
  const sameOwner=uiBuild10SharesOwner(canonical,providerObject);
  if(!endpointMatch&&!sameOwner)return null;
  return{providerObject,endpointMatch,sameOwner};
}

providerPresentationModel=function(site){
  const model=uiBuild10BaseProviderPresentationModel(site);
  const services=[...(model.services||[])];
  const canonical=services.filter(service=>
    service?.kind==='service'&&service.retired!==true&&!service._provider_workload
  );
  const providerOnly=services.filter(service=>service?.kind==='provider_workload');
  const replacements=new Map();
  const consumedCanonical=new Set();
  const consumedProvider=new Set();

  for(const service of canonical){
    const candidates=providerOnly
      .filter(providerObject=>!consumedProvider.has(providerObject.id))
      .map(providerObject=>uiBuild10ReconcileCandidate(service,providerObject))
      .filter(Boolean);
    const endpointMatches=candidates.filter(candidate=>candidate.endpointMatch);
    const strongest=endpointMatches.length?endpointMatches:candidates.filter(candidate=>candidate.sameOwner);
    if(strongest.length!==1)continue;
    const providerObject=strongest[0].providerObject;
    replacements.set(providerObject.id,{
      ...service,
      _provider_workload:providerObject._provider_workload,
    });
    consumedCanonical.add(service.id);
    consumedProvider.add(providerObject.id);
  }

  if(!replacements.size)return model;
  return{
    ...model,
    services:services.flatMap(service=>{
      if(consumedCanonical.has(service.id))return[];
      const replacement=replacements.get(service.id);
      return replacement?[replacement]:[service];
    }),
  };
};

function uiBuild10StackKey(entry){
  const environment=String(entry?.group?.environmentKey||'');
  const project=String(entry?.group?.project||'');
  if(!environment||!project)return'';
  return`${encodeURIComponent(environment)}::${encodeURIComponent(project)}`;
}

serviceStackRow=function(site,entry,parent){
  let html=uiBuild10BaseServiceStackRow(site,entry,parent);
  const key=uiBuild10StackKey(entry);
  if(!key)return html;
  html=html.replace(
    /data-compose-stack="[^"]*"/,
    `data-compose-stack="${esc(key)}"`,
  );
  const forced=stateRank(entry?.state)>0;
  const remembered=Object.prototype.hasOwnProperty.call(app.serviceStackExpansion,key)
    ?app.serviceStackExpansion[key]
    :null;
  if(!forced&&remembered===true&&!/^<details\b[^>]*\sopen(?:\s|>)/.test(html)){
    html=html.replace(/^<details\b/,'<details open');
  }
  if(!forced&&remembered===false&&/^<details\b[^>]*\sopen(?:\s|>)/.test(html)){
    html=html.replace(/\sopen(?=\s|>)/,'');
  }
  return html;
};
