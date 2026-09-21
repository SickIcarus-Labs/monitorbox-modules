'use strict';

// #359 / #220: cards are controller-projected presentation, not canonical Resources.
// The UI owns which projected cards + host Resources occupy At-a-glance.

(()=>{
  const CORE_CARD_ORDER = ['internet', 'network', 'cameras', 'power'];

  function projectedCards(site){
    const cards = Array.isArray(site?.cards) ? site.cards : [];
    const byFamily = new Map(
      cards
        .filter(card => card && card.kind === 'dashboard_card')
        .map(card => [String(card.family || card.id || ''), card])
        .filter(([family]) => family)
    );
    return CORE_CARD_ORDER
      .map(family => byFamily.get(family))
      .filter(Boolean);
  }

  function projectedHosts(site){
    return parityObjects(site)
      .filter(object =>
        object &&
        object.kind === 'host' &&
        object.id !== 'monitor' &&
        object.id !== 'monitorbox' &&
        object.retired !== true &&
        object.front_page !== false
      );
  }

  function projectedCoreObjects(site){
    return [...projectedHosts(site), ...projectedCards(site)];
  }

  // Drill-down remains one shared drawer. Projected cards are resolved only
  // from the controller's state projection and are never inserted into
  // canonical site.objects.
  const baseFindObject = findObject;
  findObject = function projectedFindObject(siteId, objectId){
    const found = baseFindObject(siteId, objectId);
    if(found.object) return found;
    const card = (found.site?.cards || []).find(item => String(item?.id) === String(objectId));
    return {site: found.site, object: card};
  };

  parityCoreObjects = projectedCoreObjects;

  // A dashboard card is a read-only projection over its contributing checks.
  // It has no canonical object lifecycle/action endpoint of its own.
  const baseRenderActions = renderActions;
  renderActions = function projectedRenderActions(site, object){
    if(object?.kind === 'dashboard_card') return '';
    return baseRenderActions(site, object);
  };

  globalThis.MonitorBoxCardProjection = Object.freeze({
    projectedCards,
    projectedHosts,
    projectedCoreObjects,
  });
})();
