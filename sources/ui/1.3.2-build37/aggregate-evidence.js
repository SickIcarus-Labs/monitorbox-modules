'use strict';

(()=>{
  function directEvidence(object){
    return (object?.components||[]).filter(component=>component&&component.enabled!==false);
  }

  function evidenceSummary(object){
    const evidence=directEvidence(object);
    if(!evidence.length)return String(object?.summary||'').trim();
    const healthy=evidence.filter(component=>component.state==='healthy').length;
    const attention=evidence.filter(component=>stateRank(component.state)>0).length;
    if(attention===0)return `${evidence.length} check${evidence.length===1?'':'s'} · ${healthy} healthy`;
    return `${evidence.length} checks · ${healthy} healthy · ${attention} need attention`;
  }

  function pruneEmptyDirectories(markup,object){
    if(!directEvidence(object).length||!markup)return markup;
    const template=document.createElement('template');
    template.innerHTML=markup;
    for(const section of template.content.querySelectorAll('.detail-section')){
      const empty=section.querySelector('.chart-empty');
      const rows=section.querySelector('.component-row,.parity-nav-row');
      if(!empty||rows)continue;
      if(/^No\s.+configured\.?$/i.test(String(empty.textContent||'').trim()))section.remove();
    }
    return template.innerHTML;
  }

  if(typeof parityCoreCard==='function'){
    const baseCard=parityCoreCard;
    parityCoreCard=function aggregateEvidenceCard(site,object){
      const markup=baseCard(site,object);
      const summary=evidenceSummary(object);
      if(!summary)return markup;
      const template=document.createElement('template');
      template.innerHTML=markup;
      const card=template.content.querySelector('.parity-card');
      if(!card)return markup;
      const rich=card.querySelector('.parity-mini-directory,.parity-camera-directory,.parity-power-list,.service-directory');
      if(!rich){
        let copy=card.querySelector('.parity-card-copy');
        if(!copy){
          copy=document.createElement('span');
          copy.className='parity-card-copy';
          card.append(copy);
        }
        copy.textContent=summary;
      }
      return template.innerHTML;
    };
  }

  if(typeof paritySpecializedDetail==='function'){
    const baseDetail=paritySpecializedDetail;
    paritySpecializedDetail=function aggregateEvidenceDetail(site,object){
      return pruneEmptyDirectories(baseDetail(site,object),object);
    };
  }

  globalThis.MonitorBoxAggregateEvidence=Object.freeze({
    directEvidence,
    evidenceSummary,
    pruneEmptyDirectories,
  });
})();
