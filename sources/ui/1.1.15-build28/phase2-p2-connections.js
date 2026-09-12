
/* MonitorBox UI v1.1.15 build 28 — P2 Phase-2 Quick Add ordering (#268). */
(()=>{
  if(typeof renderConnections!=='function')return;
  const baseRenderConnections=renderConnections;
  const collator=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});

  function visibleName(card){
    const preferred=card.querySelector('.connection-head strong, .connection-title, h3, h4, strong');
    return String(preferred?.textContent||'').replace(/\s+/g,' ').trim();
  }

  function stableIdentity(card){
    for(const key of ['candidateId','connectionId','providerId','id']){
      const value=String(card.dataset?.[key]||'').trim();
      if(value)return value;
    }
    const control=card.querySelector('[data-id],[data-candidate-id],[name="candidate_id"],[name="connection_id"]');
    return String(control?.dataset?.id||control?.dataset?.candidateId||control?.value||card.id||'').trim();
  }

  function sortCards(container){
    if(!container)return;
    const entries=[...container.children]
      .filter(node=>node.matches?.('.connection'))
      .map((card,index)=>({card,index,name:visibleName(card),identity:stableIdentity(card)}));
    entries.sort((left,right)=>
      collator.compare(left.name,right.name)
      ||collator.compare(left.identity,right.identity)
      ||left.index-right.index
    );
    container.append(...entries.map(entry=>entry.card));
  }

  renderConnections=function phase2P2SortedConnections(items){
    baseRenderConnections(items);
    sortCards(document.querySelector('#newConnections [data-v22-new-list]'));
    sortCards(document.querySelector('#alreadyConfiguredConnections [data-v22-existing-list]'));
  };
})();
