'use strict';

// Provider-blind homepage composition. Core supplies finalized card families
// and operator/discovery provenance. The managed UI owns placement and the
// schema of the opaque preferences saved with every canonical revision.
(()=>{
  const DEFAULT_FAMILIES = ['internet', 'network', 'cameras', 'power'];
  const UI_ID = 'com.sickicarus.monitorbox.ui';
  let preferences = null;
  let loaded = false;

  function keyFor(item){
    return item?.kind === 'dashboard_card'
      ? String(item.family || item.id || '')
      : 'host:' + String(item?.id || '');
  }

  function eligibleHost(item){
    return !!item && item.retired !== true &&
      ['host','network_device','remote_site'].includes(item.kind);
  }

  function allAvailable(site){
    const items = [];
    const seen = new Set();
    for(const card of Array.isArray(site?.cards) ? site.cards : []){
      if(!card || card.kind !== 'dashboard_card') continue;
      const key = keyFor(card);
      if(!key || seen.has(key)) continue;
      seen.add(key);
      items.push({key, object:card, group:'family'});
    }
    for(const object of parityObjects(site)){
      if(!eligibleHost(object)) continue;
      const key = keyFor(object);
      if(seen.has(key)) continue;
      seen.add(key);
      items.push({key, object, group:'resource'});
    }
    return items;
  }

  function defaultKeys(site){
    const available = allAvailable(site);
    const selected = available.filter(item=>
      item.group === 'resource' &&
      (
        (
          item.object.kind === 'host' &&
          item.object.homepage_origin === 'operator' &&
          item.object.explicit_front_page !== false
        ) ||
        (
          ['site_gateway','primary_router'].includes(item.object.system_role) &&
          item.object.explicit_front_page !== false
        )
      )
    ).map(item=>item.key);
    const cards = new Map(available
      .filter(item=>item.group === 'family' && item.key !== 'services')
      .map(item=>[item.key,item]));
    for(const key of DEFAULT_FAMILIES){
      if(cards.has(key)){
        selected.push(key);
        cards.delete(key);
      }
    }
    selected.push(...[...cards.keys()].sort());
    return selected;
  }

  function selectedKeys(site, snapshot){
    const saved = snapshot?.data?.sites?.[site?.id];
    if(snapshot && snapshot.schema_version !== 1) return [];
    if(!saved || saved.mode !== 'custom'){
      return defaultKeys(site);
    }
    if(!Array.isArray(saved.order) || !Array.isArray(saved.hidden)) return [];
    const hidden = new Set(saved.hidden);
    return saved.order.filter(key=>typeof key === 'string' && !hidden.has(key));
  }

  function compose(site, snapshot=preferences){
    const byKey = new Map(allAvailable(site).map(item=>[item.key,item.object]));
    const used = new Set();
    return selectedKeys(site, snapshot).filter(key=>{
      if(used.has(key) || !byKey.has(key)) return false;
      used.add(key);
      return true;
    }).map(key=>byKey.get(key));
  }

  function projectedCards(site){
    return compose(site).filter(item=>item.kind === 'dashboard_card');
  }
  function projectedHosts(site){
    return compose(site).filter(item=>item.kind !== 'dashboard_card');
  }
  function projectedCoreObjects(site){
    return compose(site);
  }

  // Projected card drill-down overrides a historical same-id aggregate;
  // it never acquires that Resource's canonical lifecycle actions.
  const baseFindObject = findObject;
  findObject = function findProjectedCard(siteId,objectId){
    const found = baseFindObject(siteId,objectId);
    const card = Array.isArray(found.site?.cards)
      ? found.site.cards.find(item=>
          item && item.kind === 'dashboard_card' &&
          String(item.id) === String(objectId))
      : null;
    return card ? {site:found.site,object:card} : found;
  };
  parityCoreObjects = projectedCoreObjects;
  const baseRenderActions = renderActions;
  renderActions = function projectedActions(site,object){
    return object?.kind === 'dashboard_card' ? '' : baseRenderActions(site,object);
  };

  function renderComposition(){
    if(!app.state) return;
    const grid=document.querySelector('#core-grid');
    if(!grid) return;
    if(preferences && preferences.schema_version !== 1){
      grid.textContent='Saved dashboard layout requires a newer UI. Open Recovery to update the UI; monitoring remains active.';
      return;
    }
    grid.innerHTML=parityCoreMarkup();
    bindCards();
  }
  const baseRenderLiveOverview=renderLiveOverview;
  renderLiveOverview=function(){
    baseRenderLiveOverview();
    renderComposition();
  };

  function installCardEditorLink(){
    if(document.querySelector('#edit-dashboard-cards')) return;
    const graphs=document.querySelector('a[href="/settings/dashboard"]');
    if(!graphs) return;
    const link=document.createElement('button');
    link.type='button';
    link.id='edit-dashboard-cards';
    link.textContent='Edit Dashboard';
    link.className=graphs.className;
    link.addEventListener('click',()=>{
      if(typeof globalThis.MonitorBoxDashboardEditor?.open === 'function'){
        globalThis.MonitorBoxDashboardEditor.open();
      }
    });
    graphs.after(link);
  }

  async function loadPreferences(){
    try{
      const response=await api('/api/v2/dashboard/config');
      if(!response || response.configured !== true){
        // A restored invalid/incompatible UI schema must not be overwritten
        // by a synthetic default layout.
        loaded=false;
        return;
      }
      preferences=response.ui_preferences || null;
      if(preferences && preferences.schema_version !== 1){
        renderComposition();
        throw new Error('Saved dashboard layout uses an unsupported schema; update the UI using Recovery');
      }
      loaded=true;
      renderComposition();
    }catch(error){
      loaded=false;
      console.warn('Saved dashboard layout unavailable; preserving existing page',error);
    }
  }

  installCardEditorLink();
  void loadPreferences();

  globalThis.MonitorBoxCardProjection=Object.freeze({
    UI_ID, allAvailable, defaultKeys, selectedKeys, compose,
    projectedCards, projectedHosts, projectedCoreObjects,
    keyFor, loadPreferences, isLoaded:()=>loaded,
  });
})();
