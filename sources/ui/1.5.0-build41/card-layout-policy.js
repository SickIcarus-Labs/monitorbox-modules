'use strict';

// Pure, provider-blind UI placement policy shared by the dashboard and its
// graph-editor-style card editor. No Core interpretation of this preference JSON.
(()=>{
  const MODULE_ID='com.sickicarus.monitorbox.ui';
  const SCHEMA=1;
  const BUILTIN=['internet','network','cameras','power'];
  const RESERVED=new Set(['monitor','monitorbox']);
  const ID=/^(?:host:[a-z][a-z0-9_-]{0,63}|family:[a-z][a-z0-9_.-]{0,127})$/;

  function eligibleHost(object){
    if(!object||object.retired===true||RESERVED.has(String(object.id)))return false;
    if(object.explicit_front_page===false)return false;
    if(object.system_role==='site_gateway' &&
       (object.kind==='network_device'||object.kind==='host'))return true;
    // Discovery/module ownership wins over a generic canonical kind=host.
    return object.kind==='host' && object.homepage_origin==='operator';
  }

  function availableEntries(site,objects){
    const values=[],seen=new Set();
    for(const object of Array.isArray(objects)?objects:[]){
      if(!object||RESERVED.has(String(object.id))||object.retired===true)continue;
      // All network devices and discovered host-like Resources can be promoted
      // deliberately, but none receive a default slot simply from discovery.
      if(object.kind!=='host'&&object.kind!=='network_device')continue;
      const id='host:'+String(object.id);
      if(!ID.test(id)||seen.has(id))continue;
      seen.add(id);
      values.push({id,kind:'host',label:String(object.label||object.id),
        value:object,defaultVisible:eligibleHost(object)});
    }
    for(const card of site?.cards||[]){
      if(!card||card.kind!=='dashboard_card')continue;
      const family=String(card.family||card.id||'');
      if(family==='services')continue; // Services has its own page section.
      const id='family:'+family;
      if(!ID.test(id)||seen.has(id))continue;
      seen.add(id);
      values.push({id,kind:'family',label:String(card.label||card.family||card.id),
        value:card,defaultVisible:true});
    }
    return values;
  }

  function defaults(site,objects){
    const available=availableEntries(site,objects);
    const families=new Map(available.filter(item=>item.kind==='family').map(item=>[item.id,item]));
    const hosts=available.filter(item=>item.kind==='host'&&item.defaultVisible);
    const builtins=BUILTIN.map(name=>families.get('family:'+name)).filter(Boolean);
    const known=new Set(builtins.map(item=>item.id));
    const additional=available.filter(item=>item.kind==='family'&&!known.has(item.id))
      .sort((a,b)=>a.id.localeCompare(b.id));
    return [...hosts,...builtins,...additional].map(item=>({id:item.id,visible:true}));
  }

  function validate(entry){
    if(entry==null)return null;
    if(!entry||entry.schema_version!==SCHEMA||
       !entry.data||typeof entry.data!=='object'||Array.isArray(entry.data)||
       !entry.data.sites||typeof entry.data.sites!=='object'||Array.isArray(entry.data.sites))
      throw Error('Unsupported or invalid dashboard layout; update the UI module or restore a compatible snapshot.');
    for(const [siteId,site] of Object.entries(entry.data.sites)){
      if(!/^[a-z][a-z0-9_-]{0,63}$/.test(siteId)||
         !site||!['custom','auto'].includes(site.mode)||
         !Array.isArray(site.cards)||site.cards.length>128)
        throw Error('Invalid saved layout at site '+siteId);
      const seen=new Set();
      for(const row of site.cards){
        if(!row||typeof row.id!=='string'||!ID.test(row.id)||
           typeof row.visible!=='boolean'||seen.has(row.id))
          throw Error('Invalid or duplicate saved card at site '+siteId);
        seen.add(row.id);
      }
    }
    return entry;
  }

  function siteRows(entry,site,objects){
    validate(entry);
    const saved=entry?.data?.sites?.[site.id];
    return saved?.mode==='custom'
      ?saved.cards.map(row=>({id:row.id,visible:row.visible}))
      :defaults(site,objects);
  }

  function visible(site,objects,entry){
    const available=availableEntries(site,objects);
    const byId=new Map(available.map(item=>[item.id,item]));
    return siteRows(entry,site,objects)
      .filter(row=>row.visible!==false&&byId.has(row.id))
      .map(row=>byId.get(row.id));
  }

  globalThis.MonitorBoxCardPolicy=Object.freeze({
    MODULE_ID,SCHEMA,BUILTIN,eligibleHost,availableEntries,defaults,
    validate,siteRows,visible,
  });
})();
