'use strict';

// UI 1.1.5 build 13 — September 7 P1 Phase 2 presentation corrections.
//
// #160: Quick Add Review counts only genuinely added Systems as staged while
// still showing existing owning Systems as reference context.
// #159: provider-derived labels become readable display/default labels without
// mutating provider identities, canonical IDs, discovery keys, or dedupe keys.
// #170: generic provider policy_hint truth is rendered as Recommended/Optional;
// optional discovery candidates are not preselected during setup.
// #206 is intentionally not solved here by guessing URLs. Existing build-9/10
// hierarchy code remains the authority for independently evidenced HTTP(S)
// presentation links; Phase-2 acceptance locks that behavior down.

(()=>{
  const PRODUCT_NAMES=new Map([
    ['bazarr','Bazarr'],
    ['home-assistant','Home Assistant'],
    ['homeassistant','Home Assistant'],
    ['homebridge','Homebridge'],
    ['lidarr','Lidarr'],
    ['ombi','Ombi'],
    ['pihole','Pi-hole'],
    ['plex','Plex'],
    ['portainer-ce','Portainer'],
    ['portainer-ee','Portainer'],
    ['prowlarr','Prowlarr'],
    ['qbittorrent','qBittorrent'],
    ['radarr','Radarr'],
    ['sabnzbd','SABnzbd'],
    ['scrypted','Scrypted'],
    ['seerr','Seerr'],
    ['sonarr','Sonarr'],
    ['tautulli','Tautulli'],
  ]);

  function imageProduct(value){
    let text=String(value||'').trim().toLowerCase();
    if(!text)return'';
    text=text.split('@',1)[0];
    const slash=text.lastIndexOf('/');
    const colon=text.lastIndexOf(':');
    if(colon>slash)text=text.slice(0,colon);
    const base=text.slice(text.lastIndexOf('/')+1);
    return PRODUCT_NAMES.get(base)||'';
  }

  function strongProductName(record){
    const directImages=Array.isArray(record?.images)?record.images:[];
    for(const image of directImages){
      const name=imageProduct(image);
      if(name)return name;
    }
    const evidence=Array.isArray(record?.evidence)?record.evidence:[];
    for(const item of evidence){
      const metadata=item?.metadata&&typeof item.metadata==='object'?item.metadata:{};
      for(const image of Array.isArray(metadata.images)?metadata.images:[]){
        const name=imageProduct(image);
        if(name)return name;
      }
    }
    return'';
  }

  function prettifyMachineLabel(value){
    const text=String(value||'')
      .replace(/[-_.]+/g,' ')
      .replace(/\s+/g,' ')
      .trim();
    if(!text)return'';
    return text.charAt(0).toUpperCase()+text.slice(1);
  }

  function providerDisplayLabel(record,fallback=''){
    const product=strongProductName(record);
    if(product)return product;
    const providerFriendly=String(
      record?.compose_service||record?.provider_label||record?.label||fallback||''
    ).trim();
    return prettifyMachineLabel(providerFriendly)||String(fallback||'').trim();
  }

  function discoveryDisplayLabel(item){
    const configured=String(item?.configured_label||'').trim();
    if(configured)return configured;
    return providerDisplayLabel(item,item?.label||'');
  }

  function discoveryPolicyPresentation(item){
    if(item?.configured_object_id)return null;
    if(!['new','recommended'].includes(String(item?.state||'')))return null;
    const policy=String(item?.policy_default||'').trim().toLowerCase();
    if(policy==='required')return{label:'Recommended',preselect:true};
    if(policy==='optional')return{label:'Optional',preselect:false};
    return null;
  }

  function reviewSystemSets(currentSession,connections,objects){
    const systems=Array.isArray(currentSession?.systems)?currentSession.systems:[];
    const addedIds=new Set(Array.isArray(currentSession?.added_system_ids)?currentSession.added_system_ids:[]);
    const referencedIds=new Set();
    for(const row of [...(connections||[]),...(objects||[])]){
      const systemId=String(row?.system_id||'').trim();
      if(systemId&&!addedIds.has(systemId))referencedIds.add(systemId);
    }
    return{
      added:systems.filter(row=>addedIds.has(row?.id)),
      referenced:systems.filter(row=>referencedIds.has(row?.id)),
    };
  }

  globalThis.MonitorBoxUiPhase2=Object.freeze({
    discoveryDisplayLabel,
    discoveryPolicyPresentation,
    prettifyMachineLabel,
    providerDisplayLabel,
    reviewSystemSets,
    strongProductName,
  });

  // Normal Discover/Setup Discover: keep provider/candidate identity untouched.
  // Only rendered/default label and generic provider recommendation presentation
  // change. Required remains subject to the page's existing safety mode; Optional
  // is always made non-preselected.
  if(typeof render==='function'&&typeof candidates!=='undefined'&&typeof document!=='undefined'){
    const baseRender=render;
    render=function(){
      const result=baseRender();
      for(const item of candidates||[]){
        const box=document.querySelector(`input[type=checkbox][data-id="${item.candidate_id}"]`);
        const row=box?.closest?.('.candidate');
        if(!row)continue;
        const strong=row.querySelector?.('strong');
        const badge=strong?.parentElement?.querySelector?.('.pill');
        const policy=discoveryPolicyPresentation(item);
        if(policy){
          if(badge)badge.textContent=policy.label;
          if(!policy.preselect&&box&&!box.disabled)box.checked=false;
        }
        if(item?.configured_label)continue;
        const friendly=discoveryDisplayLabel(item);
        if(!friendly)continue;
        if(strong)strong.textContent=friendly;
        const label=row.querySelector?.(`input[data-label-for="${item.candidate_id}"]`);
        if(label&&String(label.value||'')===String(item.label||''))label.value=friendly;
      }
      return result;
    };
  }

  // Quick Add Review: server/session state already distinguishes added Systems
  // from existing owner references. Present that truth rather than folding both
  // classes into the staged-System count.
  if(
    typeof mbReviewMode!=='undefined'&&mbReviewMode==='quick_add'&&
    typeof mbReviewSystems==='function'&&typeof mbReviewRender==='function'
  ){
    mbReviewSystems=function(connections,objects){
      return reviewSystemSets(session,connections,objects).added;
    };
    const baseReviewRender=mbReviewRender;
    mbReviewRender=function(){
      const result=baseReviewRender();
      const connections=mbReviewStagedConnections();
      const objects=mbReviewStagedObjects();
      const referenced=reviewSystemSets(session,connections,objects).referenced;
      const root=document.getElementById('mbReviewSystems');
      if(root&&referenced.length){
        const heading=document.createElement('h4');
        heading.textContent='Existing Systems referenced by staged additions';
        root.append(heading);
        for(const row of referenced){
          root.append(mbReviewRow(
            `${row.label||row.id||'System'}${row.self?' (This MonitorBox)':''}`,
            [row.address,'Existing System · reference only'].filter(Boolean).join(' · '),
          ));
        }
      }
      return result;
    };
  }

  // Dashboard provider-only workloads: operator-assigned canonical service labels
  // are untouched because this wrapper applies only when a provider workload
  // object is synthesized for presentation.
  if(typeof providerWorkloadObject==='function'){
    const baseProviderWorkloadObject=providerWorkloadObject;
    providerWorkloadObject=function(workload,host){
      const object=baseProviderWorkloadObject(workload,host);
      return{...object,label:providerDisplayLabel(workload,object?.label||'Docker workload')};
    };
  }
})();
