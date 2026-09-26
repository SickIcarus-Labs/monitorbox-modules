'use strict';

// UI-owned, provider-neutral homepage selection. Canonical objects are never
// changed by hiding, ordering or promoting a card.
(()=>{
  const MODULE_ID='com.sickicarus.monitorbox.ui';
  const SCHEMA=4; // v1/v2/v3 remain readable; only deliberate edits migrate to v4.
  const BUILTIN=Object.freeze(['internet','network','cameras','power']);
  const RESERVED=new Set(['monitor','monitorbox']);
  const ID=/^(?:host:[a-z][a-z0-9_-]{0,63}|family:[a-z][a-z0-9_.-]{0,127}|custom:[a-z][a-z0-9_-]{0,63})$/;
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

  // Bounded, provider-neutral clean-bootstrap curation from REAL canonical
  // observed numbers. Do not confuse cumulative byte counters, link speed or
  // an arbitrary healthy Ethernet check with utilization/throughput.
  function autoHostItems(object){
    if(!object||object.kind!=='host')return [];
    const candidates=new Map(),components=Array.isArray(object.components)?object.components:[];
    function offer(category,priority,component,key){
      const id=component.id;
      if(typeof id!=='string'||!id||!key||!Number.isFinite(priority))return;
      const current=candidates.get(category);
      if(!current||priority<current.priority)
        candidates.set(category,{priority,key:JSON.stringify([
          'object',String(object.id),'metric',id,key])});
    }
    const norm=x=>String(x).replace(/[^a-z0-9]/gi,'').toLowerCase();
    for(const component of components){
      if(!component||!component.id)continue;
      const metrics=component.metrics;
      if(!metrics||typeof metrics!=='object'||Array.isArray(metrics))continue;
      const measured=new Map(Object.entries(metrics)
        .filter(([_,v])=>typeof v==='number'&&Number.isFinite(v))
        .map(([k,v])=>[norm(k),v]));
      for(const [key,value] of Object.entries(metrics)){
        if(typeof value!=='number'||!Number.isFinite(value))continue;
        const k=norm(key);
        const validPercent=value>=0&&value<=100;
        if(validPercent&&/^cpu(?:usage|used|utilization)(?:percent|pct)?$/.test(k))
          offer('cpu',k.endsWith('percent')?0:1,component,key);
        if(validPercent&&/^(?:memory|mem|ram)(?:used|usage|utilization)(?:percent|pct)$/.test(k))
          offer('memory',0,component,key);
        if(validPercent&&/^(?:disk|storage|filesystem|fs|pool|volume)(?:used|usage|utilization)(?:percent|pct)$/.test(k))
          offer('storage',0,component,key);
        if(validPercent&&/^(?:eth|ethernet|nic|network|interface|link)(?:used|usage|utilization)(?:percent|pct)$/.test(k))
          offer('network',0,component,key);
        // Absolute free capacity is truthful storage data even if that
        // provider exposes no used-percent metric. Prefer percent when both
        // exist. Never infer utilization from a lone free capacity.
        if(value>=0&&/^(?:disk|storage|filesystem|fs|pool|volume)(?:available|free)(?:bytes|kib|mib)$/.test(k))
          offer('storage',3,component,key);
      }
      const idle=measured.get('cpuidlepercent');
      if(idle!==undefined&&idle>=0&&idle<=100)
        offer('cpu',2,component,'@derived.cpu_used_percent');
      const total=measured.get('memorytotalkib'),available=measured.get('memoryavailablekib');
      if(total>0&&available!==undefined&&available>=0&&available<=total)
        offer('memory',2,component,'@derived.memory_used_percent');
      // Prefer a real percentage. If not exposed, a directly observed
      // memory-used quantity is still more useful than an empty host card.
      for(const [key,value] of Object.entries(metrics)){
        const k=norm(key);
        if(value>=0&&/^(?:memory|mem|ram)used(?:bytes|kib|mib)$/.test(k))
          offer('memory',4,component,key);
      }
    }
    return ['cpu','memory','storage','network'].filter(k=>candidates.has(k))
      .map(k=>({key:candidates.get(k).key,mode:'value'}));
  }

  function defaults(site,objects){
    const available=availableEntries(site,objects);
    const families=new Map(available.filter(row=>row.kind==='family').map(row=>[row.id,row]));
    const hosts=available.filter(row=>row.kind==='host'&&row.defaultVisible);
    const builtin=BUILTIN.map(family=>families.get('family:'+family)).filter(Boolean);
    const builtinIds=new Set(builtin.map(row=>row.id));
    const additional=available.filter(row=>row.kind==='family'&&!builtinIds.has(row.id))
      .sort((a,b)=>a.id.localeCompare(b.id));
    return [...hosts,...builtin,...additional].map(row=>{
      const items=row.kind==='host'?autoHostItems(row.value):[];
      return {id:row.id,visible:true,...(items.length
        ?{presentation:{schema_version:2,items}}:{})};
    });
  }

  // Optional versioned card-content preferences extend the accepted v1
  // layout without invalidating or rewriting historical UI41 snapshots.
  // Core still stores this entire section as opaque, snapshot-paired JSON.
  function validatePresentation(value){
    if(value===undefined)return;
    if(!value||typeof value!=='object'||Array.isArray(value)||
        ![1,2].includes(value.schema_version))throw Error('Unsupported card-content preference schema');
    const allowed=new Set(['schema_version','title','compact','hidden_member_ids','items']);
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
    if(value.schema_version===1&&value.items!==undefined)
      throw Error('Selected card items require presentation schema v2');
    if(value.items!==undefined){
      if(value.schema_version!==2||!Array.isArray(value.items)||
          value.items.length>64)
        throw Error('Selected items require schema v2 and at most 64 entries');
      const seen=new Set(),registry=globalThis.MonitorBoxCardItems;
      if(!registry)throw Error('Dashboard source registry is unavailable');
      for(const item of value.items){
        if(!item||typeof item!=='object'||Array.isArray(item)||
            Object.keys(item).some(k=>!['key','mode'].includes(k))||
            !registry.parseKey(item.key)||seen.has(item.key)||
            !['tile','list','value'].includes(item.mode)||
            (item.mode==='value'&&!['metric','live'].includes(registry.parseKey(item.key)[2])))
          throw Error('Invalid or duplicate card display item');
        seen.add(item.key);
      }
    }
  }

  function validate(entry){
    if(entry==null)return null;
    if(typeof entry!=='object'||Array.isArray(entry)||![1,2,3,SCHEMA].includes(entry.schema_version)||
      !entry.data||typeof entry.data!=='object'||Array.isArray(entry.data)||
      !entry.data.sites||typeof entry.data.sites!=='object'||Array.isArray(entry.data.sites))
      throw Error('Unsupported dashboard layout schema. Update UI or restore a compatible revision; layout was not reset.');
    for(const [siteId,site] of Object.entries(entry.data.sites)){
      if(!SITE.test(siteId)||!site||typeof site!=='object'||
        !['custom','auto'].includes(site.mode)||!Array.isArray(site.cards)||
        site.cards.length>128||
        (site.arranged!==undefined&&(entry.schema_version<4||typeof site.arranged!=='boolean')))
        throw Error('Invalid dashboard layout for '+siteId);
      const seen=new Set();
      for(const row of site.cards){
        if(!row||typeof row.id!=='string'||!ID.test(row.id)||
          typeof row.visible!=='boolean'||seen.has(row.id))
          throw Error('Invalid or duplicate card for '+siteId);
        if(row.id.startsWith('custom:')){
          if(entry.schema_version<3||!row.presentation||row.presentation.schema_version!==2||
              !row.presentation.title||!Array.isArray(row.presentation.items))
            throw Error('Custom cards require a named schema-v3 layout');
        }
        if(entry.schema_version<3&&row.presentation?.items!==undefined)
          throw Error('Item compositions require layout schema v3');
        if(row.placement!==undefined){
          if(entry.schema_version!==4||!row.placement||typeof row.placement!=='object'||
             Array.isArray(row.placement)||Object.keys(row.placement).join(',')!=='column'||
             !Number.isInteger(row.placement.column)||row.placement.column<0||
             row.placement.column>2)throw Error('Invalid dashboard card placement');
        }
        if(site.arranged===true&&row.placement===undefined)
          throw Error('An arranged dashboard card is missing its placement');
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
    // v4 stores an explicit baseline: installing a new module must NOT
    // silently rewrite an operator's saved UI50 cards or restored snapshot.
    // Older bootstrap-only auto schemas still get the current fresh defaults.
    return saved?.mode==='custom'||(pinned && saved?.mode==='auto')||
      (entry?.schema_version===4&&saved?.mode==='auto')
      ?saved.cards.map(row=>({...row}))
      :defaults(site,objects);
  }

  function visible(site,objects,entry,pinned=false){
    const available=availableEntries(site,objects);
    const byId=new Map(available.map(row=>[row.id,row]));
    return siteRows(entry,site,objects,pinned).filter(row=>
      row.visible&&(byId.has(row.id)||row.id.startsWith('custom:'))).map(row=>{
        if(!row.id.startsWith('custom:'))return byId.get(row.id);
        return {id:row.id,kind:'custom',label:row.presentation.title,
          defaultVisible:false,
          value:{id:row.id,label:row.presentation.title,kind:'ui_custom_card',
            state:'unknown',summary:'Custom dashboard composition',components:[]}};
      });
  }
  globalThis.MonitorBoxCardPolicy=Object.freeze({
    MODULE_ID,SCHEMA,BUILTIN,eligibleHost,availableEntries,autoHostItems,defaults,
    validate,validatePresentation,siteRows,visible,
  });
})();
