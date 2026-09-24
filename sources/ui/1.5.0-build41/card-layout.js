'use strict';

// #219: UI-owned placement, versioned in Core's opaque module-preference
// revision namespace. Core owns monitoring authority and ephemeral site.cards;
// no provider name is a placement rule and no discovered Resource becomes a
// homepage tile merely because its kind happens to be "host".
(()=>{
  const MODULE_ID='com.sickicarus.monitorbox.ui';
  const PREFERENCE_SCHEMA=1;
  const BUILTIN=['internet','network','cameras','power'];
  const RESERVED=new Set(['monitor','monitorbox']);
  const layout={loaded:false,error:null,entry:null};

  function eligibleHost(object){
    if(!object || object.retired===true || RESERVED.has(String(object.id)))return false;
    if(object.explicit_front_page===false)return false;
    if(object.system_role==='site_gateway' &&
       (object.kind==='network_device'||object.kind==='host'))return true;
    return object.kind==='host' && object.homepage_origin==='operator';
  }

  function availableEntries(site){
    const values=[];
    const seen=new Set();
    for(const object of parityObjects(site)||[]){
      if(!object || RESERVED.has(String(object.id)) || object.retired===true)continue;
      // Explicitly added hosts, designated site gateways and individually
      // promoted discovered Resources may all be selected in the editor.
      // Promotion is a UI layout choice; it does not mutate Resource identity.
      const isHost=object.kind==='host' || object.system_role==='site_gateway';
      if(!isHost)continue;
      const id='host:'+String(object.id);
      if(seen.has(id))continue;
      seen.add(id);
      values.push({id,kind:'host',label:String(object.label||object.id),
        value:object,defaultVisible:eligibleHost(object)});
    }
    for(const card of site?.cards||[]){
      if(!card || card.kind!=='dashboard_card')continue;
      const family=String(card.family||card.id||'');
      if(!family || family==='services')continue; // dedicated Services section
      const id='family:'+family;
      if(seen.has(id))continue;
      seen.add(id);
      values.push({id,kind:'family',label:String(card.label||card.family||card.id),
        value:card,defaultVisible:true});
    }
    return values;
  }

  function defaults(site){
    const available=availableEntries(site),byId=new Map(available.map(item=>[item.id,item]));
    const hosts=available.filter(item=>item.kind==='host'&&item.defaultVisible);
    const families=BUILTIN.map(family=>byId.get('family:'+family)).filter(Boolean);
    const names=new Set(families.map(item=>item.id));
    const extras=available.filter(item=>item.kind==='family'&&!names.has(item.id))
      .sort((a,b)=>a.id.localeCompare(b.id));
    return [...hosts,...families,...extras].map(item=>({id:item.id,visible:true}));
  }

  function chosenSite(site){
    const data=layout.entry?.data;
    if(layout.entry?.schema_version!==PREFERENCE_SCHEMA)return null;
    const entry=data?.sites?.[site?.id];
    if(!entry || entry.mode!=='custom' || !Array.isArray(entry.cards))return null;
    // Unsupported future preference schemas fail closed at module admission
    // rather than silently resetting an operator's customized homepage.
    return entry;
  }

  function effectiveCards(site){
    const available=availableEntries(site);
    const lookup=new Map(available.map(item=>[item.id,item]));
    const saved=chosenSite(site);
    const requested=saved?saved.cards:defaults(site);
    const result=[],used=new Set();
    for(const row of requested){
      if(!row || typeof row.id!=='string'||used.has(row.id))continue;
      used.add(row.id);
      if(row.visible===false)continue;
      const known=lookup.get(row.id);
      if(known)result.push(known);
    }
    return result;
  }

  function project(site){return effectiveCards(site).map(item=>item.value);}
  function refreshGrid(){
    if(!app.state)return;
    const grid=document.querySelector('#core-grid');
    if(!grid)return;
    grid.innerHTML=parityCoreMarkup();
    bindCards();
  }

  const baseRenderLiveOverview=renderLiveOverview;
  parityCoreObjects=project;
  renderLiveOverview=function layoutAwareRefresh(){
    baseRenderLiveOverview();
    refreshGrid();
  };

  async function load(){
    try{
      const response=await fetch('/api/v2/dashboard/config',{cache:'no-store'});
      if(!response.ok)throw new Error('Dashboard layout unavailable (HTTP '+response.status+')');
      const config=await response.json();
      const entry=config.ui_preferences;
      if(entry && entry.schema_version!==PREFERENCE_SCHEMA){
        // Fail visible: no silent use of defaults if a newer saved schema exists.
        layout.entry=entry;
        layout.error='Saved dashboard layout uses an unsupported version. Update the UI module.';
      }else{
        layout.entry=entry||null;
        layout.error=null;
      }
    }catch(error){
      layout.error=String(error?.message||error);
    }
    layout.loaded=true;
    refreshGrid();
    if(layout.error){
      const status=document.querySelector('#card-layout-status');
      if(status){status.textContent=layout.error;status.hidden=false;}
    }
  }

  // The UI receives its own state only through the generic read endpoint.
  // On a temporarily failed fetch, the previously loaded entry is retained;
  // the editor itself refuses to apply while its canonical revision is unknown.
  document.addEventListener('DOMContentLoaded',()=>{load();});
  globalThis.MonitorBoxCardLayout=Object.freeze({
    MODULE_ID,PREFERENCE_SCHEMA,BUILTIN,eligibleHost,availableEntries,defaults,
    effectiveCards,project,load,refreshGrid,
    state:()=>({loaded:layout.loaded,error:layout.error,entry:layout.entry}),
  });
})();
