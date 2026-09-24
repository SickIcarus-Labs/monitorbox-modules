'use strict';

// UI41 overlays UI40's checked site.cards projector, retaining its projected
// card drill-down resolver and action policy. Layout authority is only the
// versioned, opaque UI preference in Core's generic snapshot transaction.
(()=>{
  const policy=globalThis.MonitorBoxCardPolicy;
  if(!policy)throw Error('MonitorBox card layout policy is missing');
  const state={loaded:false,blocked:false,entry:null,error:null};
  function objects(site){return parityObjects(site);}
  function availableEntries(site){return policy.availableEntries(site,objects(site));}
  function defaults(site){return policy.defaults(site,objects(site));}
  function effectiveCards(site){
    if(!state.loaded||state.blocked)return [];
    return policy.visible(site,objects(site),state.entry);
  }
  function project(site){return effectiveCards(site).map(row=>row.value);}
  parityCoreObjects=project; // UI40's render & drill-down remain in place.

  function controls(){
    const grid=document.querySelector('#core-grid');
    if(!grid)return;
    if(!document.querySelector('#card-layout-edit')){
      const link=document.createElement('a');
      link.id='card-layout-edit';
      link.className='button card-layout-edit';
      link.href='/settings/cards';
      link.textContent='Edit cards';
      link.setAttribute('aria-label','Edit dashboard cards');
      grid.parentElement?.insertBefore(link,grid);
    }
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
    effectiveCards,project,load,refreshGrid,state:()=>({...state}),
  });
})();
