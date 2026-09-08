'use strict';

// UI 1.1.9 build 17 — fourth Broad Leaf physical-acceptance repair pass.
//
// #206: earlier reconciliation correctly required an independently authoritative
// canonical HTTP(S) URL, but its remaining semantic fallback also required shared
// owner identity. Physical Broad Leaf exposes a legitimate migrated mismatch:
// canonical Ombi belongs to Goliath while Portainer currently groups its workload
// under Arrrrr2. Build 17 adds one final provider-neutral reconciliation tier:
// a URL-bearing canonical object and a provider workload may reconcile by semantic
// identity only when the relationship is one-to-one in both directions.
//
// This is deliberately fail closed. TCP ports never become browser URLs, missing
// canonical URL authority remains non-linking, and duplicate/ambiguous semantic
// matches remain separate for operator review.

(()=>{
  const urlApi=globalThis.MonitorBoxUiPhase2Physical2||{};
  const keyApi=globalThis.MonitorBoxUiPhase2Physical||{};

  function canonicalUrl(object){
    return typeof urlApi.canonicalPresentationUrl==='function'
      ?urlApi.canonicalPresentationUrl(object)
      :null;
  }

  function semanticOverlap(canonical,providerObject){
    if(typeof keyApi.canonicalKeys!=='function'||typeof keyApi.workloadKeys!=='function')return false;
    const left=keyApi.canonicalKeys(canonical);
    const right=keyApi.workloadKeys(providerObject);
    for(const key of left)if(right.has(key))return true;
    return false;
  }

  function uniqueSemanticPairs(authorities,providerRows){
    const edges=[];
    const providerDegree=new Map();
    const canonicalDegree=new Map();

    for(const providerObject of providerRows||[]){
      if(!providerObject?._provider_workload)continue;
      for(const canonical of authorities||[]){
        if(!canonicalUrl(canonical)||!semanticOverlap(canonical,providerObject))continue;
        edges.push({providerObject,canonical});
        providerDegree.set(
          String(providerObject.id||''),
          (providerDegree.get(String(providerObject.id||''))||0)+1,
        );
        canonicalDegree.set(
          String(canonical.id||''),
          (canonicalDegree.get(String(canonical.id||''))||0)+1,
        );
      }
    }

    return edges.filter(({providerObject,canonical})=>{
      const providerId=String(providerObject.id||'');
      const canonicalId=String(canonical.id||'');
      return providerId&&canonicalId&&providerDegree.get(providerId)===1&&canonicalDegree.get(canonicalId)===1;
    });
  }

  function reconcileUniqueSemanticAuthorities(site,model){
    const services=Array.isArray(model?.services)?[...model.services]:[];
    const providerRows=services.filter(row=>row?.kind==='provider_workload'&&row?._provider_workload);
    if(!providerRows.length)return model;

    const authorities=(site?.objects||[]).filter(object=>
      object&&object.retired!==true&&!object._provider_workload&&canonicalUrl(object)
    );
    if(!authorities.length)return model;

    const pairs=uniqueSemanticPairs(authorities,providerRows);
    if(!pairs.length)return model;

    const replacements=new Map();
    const consumedCanonical=new Set();
    for(const {providerObject,canonical} of pairs){
      const url=canonicalUrl(canonical);
      if(!url)continue;
      replacements.set(String(providerObject.id||''),{
        ...canonical,
        presentation_url:url,
        _provider_workload:providerObject._provider_workload,
      });
      consumedCanonical.add(String(canonical.id||''));
    }
    if(!replacements.size)return model;

    return{
      ...model,
      services:services.flatMap(service=>{
        const replacement=replacements.get(String(service?.id||''));
        if(replacement)return[replacement];
        if(consumedCanonical.has(String(service?.id||'')))return[];
        return[service];
      }),
    };
  }

  globalThis.MonitorBoxUiPhase2Physical4=Object.freeze({
    reconcileUniqueSemanticAuthorities,
    semanticOverlap,
    uniqueSemanticPairs,
  });

  if(typeof providerPresentationModel==='function'){
    const baseProviderPresentationModel=providerPresentationModel;
    providerPresentationModel=function(site){
      return reconcileUniqueSemanticAuthorities(site,baseProviderPresentationModel(site));
    };
  }
})();
