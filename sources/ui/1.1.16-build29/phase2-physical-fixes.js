'use strict';

(()=>{
  const bounded=(value,limit=240)=>{
    const text=String(value||'').replace(/\s+/g,' ').trim();
    return text&&text.length<=limit?text:'';
  };

  function providerCoverage(item){
    if(item?.configured_object_id||item?.state==='already_monitored')return null;
    for(const evidence of item?.evidence||[]){
      const coverage=evidence?.metadata?.monitoring_coverage;
      if(coverage&&String(coverage.status||'').trim().toLowerCase()==='covered')return coverage;
    }
    return null;
  }

  function recommendationReason(item){
    const sources=[
      item,
      item?.review_descriptor,
      item?.metadata,
      item?.review_descriptor?.metadata,
      ...(Array.isArray(item?.evidence)?item.evidence.map(row=>row?.metadata):[]),
    ];
    for(const source of sources){
      if(!source||typeof source!=='object')continue;
      for(const key of ['recommendation_reason','recommendation_reason_text','recommended_reason']){
        const value=bounded(source[key],240);
        if(value&&!/^provider\s*:/i.test(value))return value;
      }
    }
    return 'Recommended by discovery policy';
  }

  function candidateForRow(row){
    const id=row.querySelector('input[type="checkbox"][data-id]')?.dataset.id;
    return (typeof candidates!=='undefined'&&Array.isArray(candidates))
      ? candidates.find(item=>item?.candidate_id===id)||null
      : null;
  }

  function normalizeRecommendationReason(row,item){
    const node=row.querySelector('.discovery-recommendation-reason');
    if(node)node.textContent=recommendationReason(item);
  }

  function makeProviderCoverageStatic(row,item){
    if(!providerCoverage(item))return;
    const checkbox=row.querySelector('input[type="checkbox"][data-id]');
    if(!checkbox)return;
    checkbox.checked=false;
    checkbox.disabled=true;
    checkbox.hidden=true;
    const wrapper=checkbox.closest('.discovery-proposed-action');
    if(wrapper){
      wrapper.classList.add('discovery-proposed-action-static');
      const text=wrapper.querySelector('.discovery-proposed-action-text');
      if(text)text.textContent='Monitored';
    }

    // Provider-backed coverage is already monitoring.  Do not expose the old
    // promotion/adoption controls as a second, stronger monitoring state.
    for(const control of row.querySelectorAll('input,select,button')){
      if(control===checkbox)continue;
      if(control.matches('input[data-label-for],select,[type="checkbox"]')){
        control.disabled=true;
        const label=control.closest('label');
        if(label)label.hidden=true;
      }
      if(control.tagName==='BUTTON'&&/not now/i.test(control.textContent||''))control.hidden=true;
    }
    row.classList.remove('proposal-staged');
    row.classList.add('provider-covered-static');
  }

  function reconcile(){
    const root=document.getElementById('results');
    if(!root)return;
    for(const row of root.querySelectorAll('.candidate')){
      const item=candidateForRow(row);
      if(!item)continue;
      normalizeRecommendationReason(row,item);
      makeProviderCoverageStatic(row,item);
    }
  }

  if(typeof render==='function'){
    const baseRender=render;
    render=function(){
      const result=baseRender();
      reconcile();
      return result;
    };
  }
  queueMicrotask(reconcile);
})();
