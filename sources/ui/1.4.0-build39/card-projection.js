'use strict';

// #220: use controller-projected card families, not canonical pseudo-Resources.
// Operator customization and durable layout remain #219's separate UI design
// checkpoint. This slice supplies only deterministic, provider-blind defaults.

(()=>{
  const FAMILIES = ['internet','network','cameras','power'];

  function projectedCards(site){
    const byFamily = new Map();
    for(const card of Array.isArray(site?.cards) ? site.cards : []){
      if(!card || card.kind !== 'dashboard_card') continue;
      const family = String(card.family || card.id || '');
      if(!family || family === 'services' || byFamily.has(family)) continue;
      byFamily.set(family,card);
    }
    const base = FAMILIES.map(family => byFamily.get(family)).filter(Boolean);
    const known = new Set(FAMILIES);
    const extras = [...byFamily.entries()]
      .filter(([family]) => !known.has(family))
      .sort(([left],[right]) => left.localeCompare(right))
      .map(([,card]) => card);
    return [...base,...extras];
  }

  function projectedHosts(site){
    return parityObjects(site).filter(object =>
      object &&
      object.kind === 'host' &&
      object.id !== 'monitor' &&
      object.id !== 'monitorbox' &&
      object.retired !== true &&
      object.front_page !== false
    );
  }

  function projectedCoreObjects(site){
    return [...projectedHosts(site),...projectedCards(site)];
  }

  // The projected card takes precedence over any historical same-ID aggregate
  // Resource, including in drill-down. The old canonical Resource is neither
  // a prerequisite for display nor the destination of projected-card actions.
  const baseFindObject = findObject;
  findObject = function findProjectedCard(siteId,objectId){
    const found = baseFindObject(siteId,objectId);
    const card = Array.isArray(found.site?.cards)
      ? found.site.cards.find(item =>
          item && item.kind === 'dashboard_card' && String(item.id) === String(objectId))
      : null;
    return card ? {site:found.site,object:card} : found;
  };

  parityCoreObjects = projectedCoreObjects;

  const baseRenderActions = renderActions;
  renderActions = function projectedActions(site,object){
    return object?.kind === 'dashboard_card'
      ? ''
      : baseRenderActions(site,object);
  };

  // An updated controller state may arrive before graph configuration.
  // Re-render against the current projection after the existing overview
  // refresh seam without changing canonical Resources or UI layout state.
  const baseRenderLiveOverview = renderLiveOverview;
  renderLiveOverview = function projectedOverviewRefresh(){
    baseRenderLiveOverview();
    if(!app.state) return;
    const grid = document.querySelector('#core-grid');
    if(!grid) return;
    grid.innerHTML = parityCoreMarkup();
    bindCards();
  };

  globalThis.MonitorBoxCardProjection = Object.freeze({
    projectedCards,projectedHosts,projectedCoreObjects,
  });
})();
