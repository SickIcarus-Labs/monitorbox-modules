'use strict';

// UI 1.1.7 build 15 — second Broad Leaf physical-acceptance repair pass.
//
// #164: Advanced Configuration must validate from the operator's intended edits,
// not from passive render-time mutations in unrelated providers. Provider boxes
// are tagged with stable canonical identity and any provider that the operator
// actually edits is marked touched. Immediately before the normal transactional
// Validate handler runs, untouched providers are restored byte-for-byte from the
// loaded canonical baseline. This preserves real edits while removing passive UI
// normalization noise such as the Web Admin HTTP provider no-op diff.
//
// #206: a canonical safe browser URL may live either in presentation_url or in
// an explicit canonical provider configuration (for example config.url or
// config.base_url). Such URLs are authority; Portainer TCP endpoint evidence is
// correlation-only and can never synthesize a browser URL.

(()=>{
  const prior=globalThis.MonitorBoxUiPhase2Physical||{};

  function deepClone(value){
    return JSON.parse(JSON.stringify(value));
  }

  function safeHttpUrl(value){
    if(typeof prior.safeHttpUrl==='function')return prior.safeHttpUrl(value);
    const text=String(value||'').trim();
    if(!text)return null;
    try{
      const parsed=new URL(text);
      return parsed.protocol==='http:'||parsed.protocol==='https:'?parsed.href:null;
    }catch(_error){return null;}
  }

  function canonicalPresentationUrl(object){
    const direct=safeHttpUrl(object?.presentation_url);
    if(direct)return direct;

    // These are explicit URL-bearing canonical provider fields. We accept only
    // independently configured HTTP(S) values and require one unique authority.
    // No host/port/protocol inference occurs here.
    const keys=['url','base_url','presentation_url','management_url','endpoint_url'];
    const urls=new Set();
    for(const capability of object?.capabilities||[]){
      for(const provider of capability?.providers||[]){
        const config=provider?.config&&typeof provider.config==='object'?provider.config:{};
        for(const key of keys){
          const safe=safeHttpUrl(config[key]);
          if(safe)urls.add(safe);
        }
      }
    }
    return urls.size===1?[...urls][0]:null;
  }

  function presentationEndpoint(value){
    const safe=safeHttpUrl(value);
    if(!safe)return null;
    try{
      const parsed=new URL(safe);
      const host=String(parsed.hostname||'').trim().toLowerCase().replace(/^\[|\]$/g,'');
      const port=Number(parsed.port||(parsed.protocol==='https:'?443:80));
      return host&&Number.isInteger(port)&&port>0&&port<=65535?{host,port}:null;
    }catch(_error){return null;}
  }

  function directWorkloadIdentity(canonical,providerObject){
    const wanted=String(providerObject?._provider_workload?.identity||'').trim();
    if(!wanted)return false;
    for(const component of canonical?.components||[]){
      const metadata=component?.metadata&&typeof component.metadata==='object'?component.metadata:{};
      const provider=String(metadata.provider||component?.adapter||'').trim().toLowerCase();
      if(provider!=='portainer')continue;
      const identity=String(metadata.identity||metadata.workload_identity||'').trim();
      if(identity&&identity===wanted)return true;
    }
    return false;
  }

  function exactEndpointMatch(canonical,providerObject){
    const endpoint=presentationEndpoint(canonicalPresentationUrl(canonical));
    if(!endpoint)return false;
    const workload=providerObject?._provider_workload||{};
    const rows=[...(workload.service_endpoints||[]),...(workload.backend_monitoring_endpoints||[])];
    for(const item of rows){
      if(!item||typeof item!=='object')continue;
      const host=String(item.host||'').trim().toLowerCase().replace(/^\[|\]$/g,'');
      const port=Number(item.public_port||item.port);
      if(host===endpoint.host&&port===endpoint.port)return true;
    }
    return false;
  }

  function sharesOwner(canonical,providerObject){
    const providerOwners=new Set(providerObject?.depends_on||[]);
    return(canonical?.depends_on||[]).some(owner=>providerOwners.has(owner));
  }

  function keysOverlap(left,right){
    for(const item of left)if(right.has(item))return true;
    return false;
  }

  function reconciliationScore(canonical,providerObject){
    if(!canonicalPresentationUrl(canonical))return 0;
    const direct=directWorkloadIdentity(canonical,providerObject);
    const endpoint=exactEndpointMatch(canonical,providerObject);
    const owner=sharesOwner(canonical,providerObject);
    const semantic=typeof prior.canonicalKeys==='function'&&typeof prior.workloadKeys==='function'
      ?keysOverlap(prior.canonicalKeys(canonical),prior.workloadKeys(providerObject))
      :false;
    if(direct)return 500;
    if(endpoint&&owner)return 450;
    if(endpoint&&semantic)return 425;
    if(endpoint)return 400;
    if(owner&&semantic)return 300;
    return 0;
  }

  function reconcilePresentationServices(site,model){
    const services=Array.isArray(model?.services)?[...model.services]:[];
    const providerRows=services.filter(row=>row?.kind==='provider_workload'&&row?._provider_workload);
    if(!providerRows.length)return model;
    const authorities=(site?.objects||[]).filter(object=>
      object&&object.retired!==true&&!object._provider_workload&&canonicalPresentationUrl(object)
    );

    const proposals=[];
    for(const providerObject of providerRows){
      const ranked=authorities
        .map(canonical=>({canonical,score:reconciliationScore(canonical,providerObject)}))
        .filter(row=>row.score>0)
        .sort((a,b)=>b.score-a.score);
      if(!ranked.length)continue;
      const best=ranked[0].score;
      const winners=ranked.filter(row=>row.score===best);
      if(winners.length!==1)continue;
      proposals.push({providerObject,canonical:winners[0].canonical});
    }

    const canonicalCounts=new Map();
    for(const proposal of proposals){
      const id=String(proposal.canonical.id||'');
      canonicalCounts.set(id,(canonicalCounts.get(id)||0)+1);
    }

    const replacements=new Map();
    const consumedCanonical=new Set();
    for(const proposal of proposals){
      const canonicalId=String(proposal.canonical.id||'');
      if(!canonicalId||canonicalCounts.get(canonicalId)!==1)continue;
      const url=canonicalPresentationUrl(proposal.canonical);
      if(!url)continue;
      replacements.set(proposal.providerObject.id,{
        ...proposal.canonical,
        presentation_url:url,
        _provider_workload:proposal.providerObject._provider_workload,
      });
      consumedCanonical.add(canonicalId);
    }
    if(!replacements.size)return model;

    return{
      ...model,
      services:services.flatMap(service=>{
        const replacement=replacements.get(service?.id);
        if(replacement)return[replacement];
        if(consumedCanonical.has(String(service?.id||'')))return[];
        return[service];
      }),
    };
  }

  function providerKey(siteId,obj,cap,provider){
    return[
      String(siteId||''),
      String(obj?.id||''),
      String(cap?.id||''),
      String(provider?.id||''),
    ].join('/');
  }

  function providerRows(document){
    const rows=new Map();
    for(const site of document?.sites||[]){
      for(const object of site?.objects||[]){
        for(const capability of object?.capabilities||[]){
          for(let index=0;index<(capability?.providers||[]).length;index++){
            const provider=capability.providers[index];
            rows.set(providerKey(site.id,object,capability,provider),{
              site,object,capability,provider,index,
            });
          }
        }
      }
    }
    return rows;
  }

  function restoreUntouchedProviderBaselines(currentDocument,workingDocument,touchedKeys){
    if(!currentDocument||!workingDocument)return 0;
    const touched=touchedKeys instanceof Set?touchedKeys:new Set(touchedKeys||[]);
    const baseline=providerRows(currentDocument);
    const pending=providerRows(workingDocument);
    let restored=0;
    for(const [key,currentRow] of baseline){
      if(touched.has(key))continue;
      const workingRow=pending.get(key);
      if(!workingRow)continue;
      const before=JSON.stringify(workingRow.provider);
      const canonical=JSON.stringify(currentRow.provider);
      if(before===canonical)continue;
      workingRow.capability.providers[workingRow.index]=deepClone(currentRow.provider);
      restored++;
    }
    return restored;
  }

  globalThis.MonitorBoxUiPhase2Physical2=Object.freeze({
    canonicalPresentationUrl,
    exactEndpointMatch,
    providerKey,
    reconcilePresentationServices,
    reconciliationScore,
    restoreUntouchedProviderBaselines,
    safeHttpUrl,
  });

  if(typeof providerPresentationModel==='function'){
    const baseProviderPresentationModel=providerPresentationModel;
    providerPresentationModel=function(site){
      return reconcilePresentationServices(site,baseProviderPresentationModel(site));
    };
  }

  if(typeof document!=='undefined'&&typeof renderProvider==='function'){
    const touchedProviders=new Set();
    const baseRenderProvider=renderProvider;
    renderProvider=function(obj,cap,provider){
      const box=baseRenderProvider(obj,cap,provider);
      const activeSite=typeof siteId!=='undefined'?siteId:'';
      box.dataset.phase2ProviderKey=providerKey(activeSite,obj,cap,provider);
      return box;
    };

    document.addEventListener('change',event=>{
      const target=event.target instanceof Element?event.target:null;
      const box=target?.closest?.('.provider[data-phase2-provider-key]');
      const key=box?.dataset?.phase2ProviderKey;
      if(key)touchedProviders.add(key);
    },true);

    const validateButton=document.getElementById('validate');
    validateButton?.addEventListener('click',()=>{
      if(typeof current==='undefined'||typeof working==='undefined')return;
      restoreUntouchedProviderBaselines(current,working,touchedProviders);
    },true);

    if(typeof load==='function'){
      const baseLoad=load;
      load=async function(...args){
        touchedProviders.clear();
        return await baseLoad(...args);
      };
    }
  }
})();
