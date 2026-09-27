'use strict';

// UI41 overlays UI40's checked site.cards projector, retaining its projected
// card drill-down resolver and action policy. Layout authority is only the
// versioned, opaque UI preference in Core's generic snapshot transaction.
(()=>{
  const policy=globalThis.MonitorBoxCardPolicy;
  if(!policy)throw Error('MonitorBox card layout policy is missing');
  const state={loaded:false,blocked:false,entry:null,error:null,pinned:false};
  function objects(site){return parityObjects(site);}
  function availableEntries(site){return policy.availableEntries(site,objects(site));}
  function defaults(site){return policy.defaults(site,objects(site));}
  function effectiveCards(site){
    if(!state.loaded||state.blocked)return [];
    return policy.visible(site,objects(site),state.entry,state.pinned);
  }
  function project(site){return effectiveCards(site).map(row=>row.value);}
  function spatialFor(site){
    if(!state.loaded||state.blocked||state.entry?.schema_version!==4)return null;
    const saved=state.entry?.data?.sites?.[site.id];
    if(!saved?.arranged||!(saved.mode==='custom'||(state.pinned&&saved.mode==='auto')))return null;
    const placements=new Map(saved.cards.map(row=>[row.id,row.placement?.column]));
    return effectiveCards(site).map(row=>({object:row.value,
      column:placements.get(row.id)??0,id:row.id}));
  }

  // Restrict only homepage presentation; retain the original controller
  // site and object trees for health aggregation, actions and drill-downs.
  function displayFor(site,id){
    const saved=state.entry?.data?.sites?.[site.id];
    if(!state.loaded||state.blocked||!saved||
        !(saved.mode==='custom'||(state.pinned&&saved.mode==='auto')))return null;
    const row=saved.cards.find(item=>item.id===id);
    return row?.presentation||null;
  }
  const baseCoreCard=parityCoreCard;
  parityCoreCard=function presentedCoreCard(site,object){
    const key=object.kind==='ui_custom_card'?String(object.id):
      object.kind==='dashboard_card'
        ?'family:'+String(object.family||object.id)
        :'host:'+String(object.id);
    const presentation=displayFor(site,key);
    if(!presentation)return baseCoreCard(site,object);
    const shown={...object,label:presentation.title||object.label};
    let view=site;
    const hidden=new Set(presentation.hidden_member_ids||[]);
    const family=object.kind==='dashboard_card'
      ?String(object.family||object.id):'';
    if(hidden.size&&['network','cameras','power'].includes(family)){
      const isMember=item=>family==='network'
        ?item.kind==='network_device'||item.kind==='remote_site'
        :item.kind===(family==='cameras'?'camera':'ups');
      view={...site,objects:(site.objects||[]).filter(item=>
        !isMember(item)||!hidden.has(String(item.id)))};
    }
    let markup=baseCoreCard(view,shown);
    if(presentation.compact===true)
      markup=markup.replace('class="parity-card ','class="parity-card mb-card-compact ');
    return markup;
  };
  parityCoreObjects=project; // UI40's render & drill-down remain in place.

  function controls(){
    const grid=document.querySelector('#core-grid');
    if(!grid)return;
    if(!document.querySelector('#card-layout-status')){
      const node=document.createElement('p');
      node.id='card-layout-status';
      node.className='card-layout-status';
      node.setAttribute('role','status');
      grid.parentElement?.insertBefore(node,grid);
    }
    const warning=document.querySelector('#card-layout-status');
    if(warning){
      warning.textContent=state.error||'';
      warning.hidden=!state.error;
    }
  }
  function refreshGrid(){
    if(!app.state)return;
    const grid=document.querySelector('#core-grid');
    if(!grid)return;
    grid.innerHTML=parityCoreMarkup();
    bindCards();
    controls();
  }
  let sequence=0;
  async function load(){
    const mine=++sequence;
    try{
      const response=await fetch('/api/v2/dashboard/config',{cache:'no-store'});
      if(!response.ok)throw Error('Layout unavailable (HTTP '+response.status+')');
      const config=await response.json();
      if(config.configured===false)throw Error('Configuration not yet available');
      let entry;
      try{entry=policy.validate(config.ui_preferences);}
      catch(error){error.layoutSchema=true;throw error;}
      if(mine!==sequence)return;
      state.entry=entry;
      state.pinned=Array.isArray(config.restored_preference_ids)&&
        config.restored_preference_ids.includes(policy.MODULE_ID);
      state.blocked=false;
      state.error=null;
    }catch(error){
      if(mine!==sequence)return;
      // First-load failure must not fabricate a default over unknown saved
      // choices. A later transport failure retains the last known good layout.
      if(!state.loaded||error.layoutSchema)state.blocked=true;
      state.error=String(error?.message||error);
    }
    state.loaded=true;
    refreshGrid();
    controls();
  }
  document.addEventListener('DOMContentLoaded',()=>{controls();load();});
  // Picking a retained snapshot in another tab, then returning here,
  // should display its paired UI preference without an appliance restart.
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  globalThis.MonitorBoxCardLayout=Object.freeze({
    MODULE_ID:policy.MODULE_ID,PREFERENCE_SCHEMA:policy.SCHEMA,
    eligibleHost:policy.eligibleHost,availableEntries,defaults,
    effectiveCards,displayFor,project,spatialFor,load,refreshGrid,state:()=>({...state}),
  });
})();
