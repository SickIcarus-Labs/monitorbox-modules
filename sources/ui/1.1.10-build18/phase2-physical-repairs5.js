'use strict';

// UI 1.1.10 build 18 — fifth Broad Leaf physical-acceptance repair pass.
//
// #206: build 17 correctly found Ombi's independently authoritative browser URL,
// but it replaced the Portainer workload row with the canonical Service object.
// That transferred canonical ownership/topology into the provider presentation
// model and physically moved an Arrrrr2-hosted workload under Goliath.
//
// Build 18 makes the authority boundary explicit: provider inventory owns runtime
// placement, stack membership, workload identity and runtime state; canonical
// service state may contribute only presentation metadata (safe HTTP(S) URL, plus
// human label/icon) after a bounded unique reconciliation. TCP transport evidence
// remains correlation-only and can never manufacture a browser URL.

(()=>{
  function token(value){
    return String(value||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,'');
  }

  function safeHttpUrl(value){
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

  function imageKey(value){
    let text=String(value||'').trim().toLowerCase();
    if(!text)return'';
    text=text.split('@',1)[0];
    const slash=text.lastIndexOf('/');
    const colon=text.lastIndexOf(':');
    if(colon>slash)text=text.slice(0,colon);
    return token(text.slice(text.lastIndexOf('/')+1));
  }

  function canonicalKeys(object){
    const keys=new Set();
    for(const value of [object?.label,object?.icon]){
      const key=token(value);
      if(key)keys.add(key);
    }
    const id=String(object?.id||'');
    const idKey=token(id);
    if(idKey)keys.add(idKey);
    for(const hostId of object?.depends_on||[]){
      const prefix=`${hostId}_`;
      if(id.startsWith(prefix)){
        const suffix=token(id.slice(prefix.length));
        if(suffix)keys.add(suffix);
      }
    }
    return keys;
  }

  function workloadKeys(providerObject){
    const workload=providerObject?._provider_workload||{};
    const keys=new Set();
    for(const value of [workload.compose_service,workload.label,providerObject?.label]){
      const key=token(value);
      if(key)keys.add(key);
    }
    for(const image of workload.images||[]){
      const key=imageKey(image);
      if(key)keys.add(key);
    }
    return keys;
  }

  function keysOverlap(left,right){
    for(const item of left)if(right.has(item))return true;
    return false;
  }

  function sharesOwner(canonical,providerObject){
    const providerOwners=new Set(providerObject?.depends_on||[]);
    return(canonical?.depends_on||[]).some(owner=>providerOwners.has(owner));
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

  function reconciliationScore(canonical,providerObject){
    if(!canonicalPresentationUrl(canonical))return 0;
    const direct=directWorkloadIdentity(canonical,providerObject);
    const endpoint=exactEndpointMatch(canonical,providerObject);
    const owner=sharesOwner(canonical,providerObject);
    const semantic=keysOverlap(canonicalKeys(canonical),workloadKeys(providerObject));
    if(direct)return 500;
    if(endpoint&&owner)return 450;
    if(endpoint&&semantic)return 425;
    if(endpoint)return 400;
    if(owner&&semantic)return 300;
    return 0;
  }

  function providerFirstReplacement(providerObject,canonical,url){
    return{
      ...providerObject,
      label:String(canonical?.label||providerObject?.label||'').trim()||providerObject?.label,
      icon:canonical?.icon||providerObject?.icon,
      presentation_url:url,
      _provider_workload:providerObject._provider_workload,
      _canonical_presentation_authority:String(canonical?.id||''),
    };
  }

  function rankedProposals(authorities,providerRows){
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
    return proposals;
  }

  function uniqueSemanticProposals(authorities,providerRows,usedCanonical,usedProvider){
    const edges=[];
    const providerDegree=new Map();
    const canonicalDegree=new Map();
    for(const providerObject of providerRows){
      const providerId=String(providerObject?.id||'');
      if(!providerId||usedProvider.has(providerId))continue;
      for(const canonical of authorities){
        const canonicalId=String(canonical?.id||'');
        if(!canonicalId||usedCanonical.has(canonicalId))continue;
        if(!keysOverlap(canonicalKeys(canonical),workloadKeys(providerObject)))continue;
        edges.push({providerObject,canonical});
        providerDegree.set(providerId,(providerDegree.get(providerId)||0)+1);
        canonicalDegree.set(canonicalId,(canonicalDegree.get(canonicalId)||0)+1);
      }
    }
    return edges.filter(({providerObject,canonical})=>
      providerDegree.get(String(providerObject.id||''))===1&&
      canonicalDegree.get(String(canonical.id||''))===1
    );
  }

  function reconcilePresentationServices(site,model){
    const services=Array.isArray(model?.services)?[...model.services]:[];
    const providerRows=services.filter(row=>row?.kind==='provider_workload'&&row?._provider_workload);
    if(!providerRows.length)return model;

    const authorities=(site?.objects||[]).filter(object=>
      object&&object.retired!==true&&!object._provider_workload&&canonicalPresentationUrl(object)
    );
    if(!authorities.length)return model;

    const proposals=rankedProposals(authorities,providerRows);
    const canonicalCounts=new Map();
    for(const proposal of proposals){
      const canonicalId=String(proposal.canonical?.id||'');
      canonicalCounts.set(canonicalId,(canonicalCounts.get(canonicalId)||0)+1);
    }

    const accepted=[];
    const usedCanonical=new Set();
    const usedProvider=new Set();
    for(const proposal of proposals){
      const canonicalId=String(proposal.canonical?.id||'');
      const providerId=String(proposal.providerObject?.id||'');
      if(!canonicalId||!providerId||canonicalCounts.get(canonicalId)!==1)continue;
      accepted.push(proposal);
      usedCanonical.add(canonicalId);
      usedProvider.add(providerId);
    }

    // Final owner-mismatch bridge: semantic identity alone is allowed only when
    // the remaining canonical/workload relationship is one-to-one both ways.
    accepted.push(...uniqueSemanticProposals(authorities,providerRows,usedCanonical,usedProvider));

    const replacements=new Map();
    const consumedCanonical=new Set();
    for(const {providerObject,canonical} of accepted){
      const providerId=String(providerObject?.id||'');
      const canonicalId=String(canonical?.id||'');
      const url=canonicalPresentationUrl(canonical);
      if(!providerId||!canonicalId||!url)continue;
      replacements.set(providerId,providerFirstReplacement(providerObject,canonical,url));
      consumedCanonical.add(canonicalId);
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

  globalThis.MonitorBoxUiPhase2Physical5=Object.freeze({
    canonicalPresentationUrl,
    canonicalKeys,
    providerFirstReplacement,
    reconcilePresentationServices,
    reconciliationScore,
    safeHttpUrl,
    uniqueSemanticProposals,
    workloadKeys,
  });

  if(typeof providerPresentationModel==='function'){
    const baseProviderPresentationModel=providerPresentationModel;
    providerPresentationModel=function(site){
      return reconcilePresentationServices(site,baseProviderPresentationModel(site));
    };
  }
})();
