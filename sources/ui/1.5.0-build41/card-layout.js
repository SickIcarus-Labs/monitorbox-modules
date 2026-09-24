'use strict';

// UI-owned placement over the versioned Core site.cards stream. The pure
// policy is shared with the editor; no duplicate vendor/device heuristics.
(()=>{
  const policy=globalThis.MonitorBoxCardPolicy;
  if(!policy)throw Error('Dashboard card policy failed to load');
  const state={loaded:false,error:null,entry:null};

  function availableEntries(site){
    return policy.availableEntries(site,parityObjects(site));
  }
  function defaults(site){return policy.defaults(site,parityObjects(site));}
  function effectiveCards(site){
    if(state.error && state.entry)return []; // never silently reset a newer saved layout
    return policy.visible(site,parityObjects(site),state.entry);
  }
  function projectedHosts(site){
    return availableEntries(site)
      .filter(row=>row.kind==='host'&&row.defaultVisible)
      .map(row=>row.value);
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

  function showError(error){
    const status=document.querySelector('#card-layout-status');
    if(status){
      status.textContent=error||'';
      status.hidden=!error;
    }
  }

  async function load(){
    try{
      const response=await fetch('/api/v2/dashboard/config',{cache:'no-store'});
      if(!response.ok)throw Error('Dashboard layout unavailable (HTTP '+response.status+')');
      const config=await response.json();
      policy.validate(config.ui_preferences);
      state.entry=config.ui_preferences||null;
      state.error=null;
    }catch(error){
      // Preserve the last known good selection after transient transport errors.
      // If a saved schema is unsupported, show an explicit error, not a fake
      // default or a silently overwritten layout.
      state.error=String(error?.message||error);
    }
    state.loaded=true;
    refreshGrid();
    showError(state.error);
  }

  document.addEventListener('DOMContentLoaded',load);
  globalThis.MonitorBoxCardLayout=Object.freeze({
    MODULE_ID:policy.MODULE_ID,PREFERENCE_SCHEMA:policy.SCHEMA,
    eligibleHost:policy.eligibleHost,availableEntries,defaults,
    effectiveCards,project,load,refreshGrid,
    state:()=>({...state}),
  });
})();
