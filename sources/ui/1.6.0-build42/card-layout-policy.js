'use strict';

// UI-owned, provider-neutral homepage selection. Canonical objects are never
// changed by hiding, ordering or promoting a card.
(()=>{
  const MODULE_ID='com.sickicarus.monitorbox.ui';
  const SCHEMA=2; // v1 is readable; first edit migrates to v2.
  const BUILTIN=Object.freeze(['internet','network','cameras','power']);
  const RESERVED=new Set(['monitor','monitorbox']);
  const ID=/^(?:host:[a-z][a-z0-9_-]{0,63}|family:[a-z][a-z0-9_.-]{0,127})$/;
  const SITE=/^[a-z][a-z0-9_-]{0,63}$/;

  function eligibleHost(object){
    if(!object || object.retired===true || RESERVED.has(String(object.id)))return false;
    // explicit_front_page is the canonical operator choice. The public
    // front_page field is legacy *derived* presentation state: a historical
    // Network aggregate can set it false for a designated gateway. Never
    // misinterpret that aggregate suppression as an operator hide decision.
    if(object.explicit_front_page===false)return false;
    // A deliberately designated site gateway is a system role, not a vendor.
    if(object.system_role==='site_gateway' &&
        (object.kind==='host'||object.kind==='network_device'))return true;
    // Discovery/module ownership defeats kind=host AND legacy front_page=true.
    return object.kind==='host' && object.homepage_origin==='operator';
  }

  function availableEntries(site,objects){
    const entries=[],seen=new Set();
    for(const object of Array.isArray(objects)?objects:[]){
      if(!object || object.retired===true || RESERVED.has(String(object.id)))continue;
      if(object.kind!=='host' && object.kind!=='network_device')continue;
      const id='host:'+String(object.id);
      if(!ID.test(id)||seen.has(id))continue;
      seen.add(id);
      entries.push({id,kind:'host',label:String(object.label||object.id),
        value:object,defaultVisible:eligibleHost(object)});
    }
    for(const card of Array.isArray(site?.cards)?site.cards:[]){
      if(!card||card.kind!=='dashboard_card')continue;
      const family=String(card.family||card.id||'');
      if(family==='services')continue; // Existing Services section, not a duplicate.
      const id='family:'+family;
      if(!ID.test(id)||seen.has(id))continue;
      seen.add(id);
      entries.push({id,kind:'family',label:String(card.label||family),
        value:card,defaultVisible:true});
    }
    return entries;
  }

  function defaults(site,objects){
    const available=availableEntries(site,objects);
    const families=new Map(available.filter(row=>row.kind==='family').map(row=>[row.id,row]));
    const hosts=available.filter(row=>row.kind==='host'&&row.defaultVisible);
    const builtin=BUILTIN.map(family=>families.get('family:'+family)).filter(Boolean);
    const builtinIds=new Set(builtin.map(row=>row.id));
    const additional=available.filter(row=>row.kind==='family'&&!builtinIds.has(row.id))
      .sort((a,b)=>a.id.localeCompare(b.id));
    return [...hosts,...builtin,...additional].map(row=>({id:row.id,visible:true}));
  }

  // Optional versioned card-content preferences extend the accepted v1
  // layout without invalidating or rewriting historical UI41 snapshots.
  // Core still stores this entire section as opaque, snapshot-paired JSON.
  function validatePresentation(value){
    if(value===undefined)return;
    if(!value||typeof value!=='object'||Array.isArray(value)||
        value.schema_version!==1)throw Error('Unsupported card-content preference schema');
    const allowed=new Set(['schema_version','title','compact','hidden_member_ids']);
    if(Object.keys(value).some(key=>!allowed.has(key)))
      throw Error('Unsupported card-content preference fields');
    if(value.title!==undefined&&(typeof value.title!=='string'||
        value.title.trim()!==value.title||!value.title||value.title.length>80))
      throw Error('Card title must contain 1–80 characters');
    if(value.compact!==undefined&&typeof value.compact!=='boolean')
      throw Error('Card compact option must be boolean');
    if(value.hidden_member_ids!==undefined){
      if(!Array.isArray(value.hidden_member_ids)||value.hidden_member_ids.length>128)
        throw Error('Too many hidden card members');
      const seen=new Set();
      for(const member of value.hidden_member_ids){
        if(typeof member!=='string'||member.length>128||!member||
            !/^[a-z][a-z0-9_.:-]*$/.test(member)||seen.has(member))
          throw Error('Invalid or duplicate hidden card member');
        seen.add(member);
      }
    }
  }

  function validate(entry){
    if(entry==null)return null;
    if(typeof entry!=='object'||Array.isArray(entry)||![1,SCHEMA].includes(entry.schema_version)||
      !entry.data||typeof entry.data!=='object'||Array.isArray(entry.data)||
      !entry.data.sites||typeof entry.data.sites!=='object'||Array.isArray(entry.data.sites))
      throw Error('Unsupported dashboard layout schema. Update UI or restore a compatible revision; layout was not reset.');
    for(const [siteId,site] of Object.entries(entry.data.sites)){
      if(!SITE.test(siteId)||!site||typeof site!=='object'||
        !['custom','auto'].includes(site.mode)||!Array.isArray(site.cards)||
        site.cards.length>128)throw Error('Invalid dashboard layout for '+siteId);
      const seen=new Set();
      for(const row of site.cards){
        if(!row||typeof row.id!=='string'||!ID.test(row.id)||
          typeof row.visible!=='boolean'||seen.has(row.id))
          throw Error('Invalid or duplicate card for '+siteId);
        seen.add(row.id);
        if(entry.schema_version===1&&row.presentation!==undefined)
          throw Error('Card-content preferences require layout schema v2');
        validatePresentation(row.presentation);
      }
    }
    return entry;
  }

  function siteRows(entry,site,objects,pinned=false){
    validate(entry);
    const saved=entry?.data?.sites?.[site.id];
    return saved?.mode==='custom'||(pinned && saved?.mode==='auto')
      ?saved.cards.map(row=>({...row}))
      :defaults(site,objects);
  }

  function visible(site,objects,entry,pinned=false){
    const available=availableEntries(site,objects);
    const byId=new Map(available.map(row=>[row.id,row]));
    return siteRows(entry,site,objects,pinned).filter(row=>row.visible && byId.has(row.id))
      .map(row=>byId.get(row.id));
  }
  globalThis.MonitorBoxCardPolicy=Object.freeze({
    MODULE_ID,SCHEMA,BUILTIN,eligibleHost,availableEntries,defaults,
    validate,validatePresentation,siteRows,visible,
  });
})();
