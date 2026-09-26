'use strict';

// #94 shared public-state presentation for preset host/family and custom cards.
// Existing Core state, parent card health and object drill-down are unchanged.
(()=>{
  const registry=globalThis.MonitorBoxCardItems;
  const layout=globalThis.MonitorBoxCardLayout;
  if(!registry||!layout)throw Error('Dashboard composer runtime is missing');
  const previous=parityCoreCard;
  const text=value=>esc(String(value==null?'':value));
  const state=value=>['healthy','degraded','failed','unknown','paused','disabled']
    .includes(value)?value:'unknown';
  const showNumber=value=>Number.isFinite(value)
    ?new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(value):'—';
  function items(site,preference){
    const keys=preference?.items;
    if(!Array.isArray(keys)||!keys.length)return '';
    const index=registry.catalog(site).items;
    return '<div class="mb-card-items" aria-label="Selected monitored values">'+
      keys.map(selection=>{
        const item=registry.display(site,selection.key,index);
        const mode=selection.mode==='value'&&item.type==='metric'?'value':
          selection.mode==='list'?'list':'tile';
        const available=item.available;
        const kind=available?state(item.state):'unknown';
        const value=!available?'Unavailable':item.type==='metric'
          ?showNumber(item.value)+(item.unit?' '+text(item.unit):'')
          :state(item.state).replace(/^./,s=>s.toUpperCase());
        const source=String(item.sourceLabel||'');
        const drilldown=item.drilldownObjectId&&
          (site.objects||[]).some(obj=>obj.id===item.drilldownObjectId);
        const control=drilldown?'button':'span';
        const action=drilldown
          ?' type="button" data-mb-source-site="'+text(site.id)+
            '" data-mb-source-object="'+text(item.drilldownObjectId)+'"'
          :'';
        return '<'+control+' class="mb-card-item mb-item-mode-'+mode+' '+kind+
          (available?'':' unavailable')+'"'+action+'>'+
          '<span class="mb-card-item-source">'+text(source)+'</span>'+
          '<span class="mb-card-item-label">'+text(item.label)+'</span>'+
          '<strong class="mb-card-item-value">'+text(value)+'</strong>'+
          '</'+control+'>';
      }).join('')+'</div>';
  }
  parityCoreCard=function composedCard(site,object){
    const custom=object.kind==='ui_custom_card';
    const key=custom?String(object.id):object.kind==='dashboard_card'
      ?'family:'+String(object.family||object.id)
      :'host:'+String(object.id);
    const pref=layout.displayFor(site,key);
    if(!custom&&(!pref||!pref.items?.length))return previous(site,object);
    if(custom){
      const title=text(pref?.title||object.label||'Custom card');
      const contents=items(site,pref);
      const description=contents?'':'<p class="mb-card-item-empty">Add a monitored item in Dashboard → Cards.</p>';
      return '<article class="parity-card mb-custom-card" data-site="'+
        text(site.id)+'"><span class="parity-card-head"><strong>'+
        title+'</strong><span class="mb-card-display-label">Display only</span></span>'+
        (contents||description)+'</article>';
    }
    // Keep the accepted built-in card unchanged and clickable for its normal
    // Core drawer. Render cross-source items as separate, non-nested buttons.
    return '<div class="mb-card-shell">'+previous(site,object)+
      items(site,pref)+'</div>';
  };
  document.addEventListener('click',event=>{
    const node=event.target.closest?.('[data-mb-source-object]');
    if(!node)return;
    const siteId=node.getAttribute('data-mb-source-site');
    const objectId=node.getAttribute('data-mb-source-object');
    if(!siteId||!objectId)return;
    // Never navigate a fabricated object; a missing source should remain
    // visible as unavailable until the user repairs the configuration.
    const current=(app.state?.sites||[]).find(s=>s.id===siteId);
    if(!current?.objects?.some(o=>o.id===objectId))return;
    openDrawer(siteId,objectId);
  });
})();