'use strict';

// #359 / #220 / #219: cards are controller-projected presentation, not canonical
// Resources. UI-owned dashboard configuration selects host cards, hides projected
// card families, and orders the resulting At-a-glance surface.

(()=>{
  const CORE_CARD_ORDER = ['internet', 'network', 'cameras', 'power'];

  function cardLayout(site){
    const layout = app.dashboardConfiguration?.sites?.[site?.id]?.card_layout;
    return layout && typeof layout === 'object' ? layout : {};
  }

  function projectedCards(site){
    const layout = cardLayout(site);
    const hidden = new Set(
      Array.isArray(layout.hidden_card_families)
        ? layout.hidden_card_families.map(String)
        : []
    );
    const cards = Array.isArray(site?.cards) ? site.cards : [];
    const byFamily = new Map(
      cards
        .filter(card => card && card.kind === 'dashboard_card')
        .map(card => [String(card.family || card.id || ''), card])
        .filter(([family]) => family && family !== 'services' && !hidden.has(family))
    );
    const preferred = CORE_CARD_ORDER
      .map(family => byFamily.get(family))
      .filter(Boolean);
    const known = new Set(CORE_CARD_ORDER);
    const extras = [...byFamily.entries()]
      .filter(([family]) => !known.has(family))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([, card]) => card);
    return [...preferred, ...extras];
  }

  function projectedHosts(site){
    const layout = cardLayout(site);
    const available = parityObjects(site)
      .filter(object =>
        object &&
        object.kind === 'host' &&
        object.id !== 'monitor' &&
        object.id !== 'monitorbox' &&
        object.retired !== true
      );
    if(Array.isArray(layout.host_ids)){
      const selected = new Set(layout.host_ids.map(String));
      return available.filter(object => selected.has(String(object.id)));
    }
    return available.filter(object => object.front_page !== false);
  }

  function tokenFor(item){
    return item?.kind === 'dashboard_card'
      ? `card:${String(item.family || item.id || '')}`
      : `host:${String(item?.id || '')}`;
  }

  function projectedCoreObjects(site){
    const items = [...projectedHosts(site), ...projectedCards(site)];
    const order = cardLayout(site).order;
    if(!Array.isArray(order) || !order.length) return items;

    const byToken = new Map(items.map(item => [tokenFor(item), item]));
    const result = [];
    const used = new Set();
    for(const raw of order){
      const token = String(raw);
      const item = byToken.get(token);
      if(!item || used.has(token)) continue;
      used.add(token);
      result.push(item);
    }
    for(const item of items){
      const token = tokenFor(item);
      if(used.has(token)) continue;
      used.add(token);
      result.push(item);
    }
    return result;
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

  // dashboard-widgets.js loads configuration asynchronously. Its loader calls
  // renderLiveOverview() after the configuration arrives, so wrap that stable
  // refresh seam to apply host/card composition immediately rather than waiting
  // for the next controller-state poll.
  const baseRenderLiveOverviewForCards = renderLiveOverview;
  renderLiveOverview = function projectedLayoutRefresh(){
    baseRenderLiveOverviewForCards();
    if(!app.state) return;
    const grid = document.querySelector('#core-grid');
    if(!grid) return;
    grid.innerHTML = parityCoreMarkup();
    bindCards();
  };

  globalThis.MonitorBoxCardProjection = Object.freeze({
    cardLayout,
    projectedCards,
    projectedHosts,
    projectedCoreObjects,
    tokenFor,
  });
})();
