'use strict';

(()=>{
  const COVERED='covered';
  const NEW='new';
  const ATTENTION='attention';
  const RECOMMENDED='recommended';
  const OTHER='other';
  const collator=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});

  function boundedLabel(value){
    const text=String(value||'').trim();
    return text&&text.length<=80?text:'';
  }

  function boundedReason(value){
    const text=String(value||'').replace(/\s+/g,' ').trim();
    return text&&text.length<=180?text:'';
  }

  function providerCoverage(item){
    for(const evidence of item?.evidence||[]){
      const coverage=evidence?.metadata?.monitoring_coverage;
      if(!coverage||String(coverage.status||'').trim().toLowerCase()!=='covered')continue;
      return {status:'covered',kind:boundedLabel(coverage.kind),sourceLabel:boundedLabel(coverage.source_label)};
    }
    return null;
  }

  function coverageState(item){
    if(item?.configured_object_id||item?.state==='already_monitored')return {status:'covered',kind:'canonical',sourceLabel:''};
    return providerCoverage(item);
  }

  function sectionFor(item){
    if(item?.state==='needs_review'||item?.state==='auxiliary')return ATTENTION;
    return coverageState(item)?COVERED:NEW;
  }

  function candidateForRow(row){
    const id=row.querySelector('input[type="checkbox"][data-id]')?.dataset.id;
    return (typeof candidates!=='undefined'&&Array.isArray(candidates))
      ? candidates.find(item=>item?.candidate_id===id)||null
      : null;
  }

  function candidateIdentity(row){
    const children=[...row.children];
    const checkboxIndex=children.findIndex(child=>
      child.matches?.('input[type="checkbox"][data-id]')||child.querySelector?.('input[type="checkbox"][data-id]')
    );
    if(checkboxIndex<0)return null;
    for(let index=checkboxIndex+1;index<children.length;index++){
      const child=children[index];
      if(child.matches?.('input,select,button')||child.classList?.contains('wide'))continue;
      if(child.querySelector?.('input[data-label-for],select[data-policy-for]'))continue;
      return child;
    }
    return null;
  }

  function setCoverageBadge(row,item){
    const identity=candidateIdentity(row);
    if(!identity)return;
    const existing=identity.querySelector('.discovery-coverage-badge');
    const baseBadge=identity.querySelector('.pill:not(.discovery-coverage-badge):not(.discovery-recommendation-badge)');
    const coverage=coverageState(item);
    const badge=existing||document.createElement('span');
    badge.className='pill discovery-coverage-badge';
    if(coverage){
      badge.classList.add('good');
      badge.textContent=coverage.sourceLabel?`Already monitored via ${coverage.sourceLabel}`:'Already monitored';
    }else if(item?.state==='needs_review'){
      badge.classList.add('bad');
      badge.textContent='Needs review';
    }else if(item?.state==='auxiliary'){
      badge.classList.add('warn');
      badge.textContent='Auxiliary';
    }else{
      badge.textContent='Not monitored';
    }
    if(baseBadge){
      if(item?.state==='recommended'&&!coverage){
        baseBadge.classList.add('discovery-recommendation-badge','good');
        baseBadge.textContent='Recommended';
        baseBadge.insertAdjacentElement('beforebegin',badge);
      }else{
        baseBadge.replaceWith(badge);
      }
    }else if(!existing){
      identity.append(document.createTextNode(' '),badge);
    }
  }

  function normalizedRecommendation(item){
    if(sectionFor(item)!==NEW)return false;
    if(item?.recommended===true||item?.monitor_default===true)return true;
    if(String(item?.policy_default||'').trim().toLowerCase()==='required')return true;
    return item?.state==='recommended';
  }

  function recommendationReason(item){
    const direct=boundedReason(item?.recommendation_reason);
    if(direct)return direct;
    const descriptor=boundedReason(item?.review_descriptor?.recommendation_reason);
    if(descriptor)return descriptor;
    return 'Recommended by discovery policy';
  }

  function setRecommendationReason(row,item){
    const identity=candidateIdentity(row);
    if(!identity)return;
    let reason=identity.querySelector('.discovery-recommendation-reason');
    if(!normalizedRecommendation(item)){
      reason?.remove();
      return;
    }
    if(!reason){
      reason=document.createElement('div');
      reason.className='discovery-recommendation-reason';
      identity.append(reason);
    }
    reason.textContent=recommendationReason(item);
  }

  function actionText(item,checkbox){
    const coverage=coverageState(item);
    if(item?.state==='needs_review')return 'Needs review';
    if(item?.state==='auxiliary')return 'No action';
    if(item?.configured_object_id||item?.state==='already_monitored')return checkbox.checked?'Keep monitoring':'Stop monitoring';
    if(coverage)return checkbox.checked?'Add configured monitor':'Keep existing coverage';
    return checkbox.checked?'Start monitoring':'Not staged';
  }

  function ensureActionControl(row,item){
    const checkbox=row.querySelector('input[type="checkbox"][data-id]');
    if(!checkbox)return;
    if(!row.dataset.discoveryCoverageDefaultApplied){
      const coverage=coverageState(item);
      if(coverage&&!item?.configured_object_id&&item?.state!=='already_monitored')checkbox.checked=false;
      row.dataset.discoveryCoverageDefaultApplied='true';
    }
    let wrapper=checkbox.closest('.discovery-proposed-action');
    if(!wrapper){
      wrapper=document.createElement('label');
      wrapper.className='discovery-proposed-action';
      checkbox.replaceWith(wrapper);
      wrapper.append(checkbox);
      const text=document.createElement('span');
      text.className='discovery-proposed-action-text';
      wrapper.append(text);
      checkbox.addEventListener('change',()=>{
        row.classList.toggle('proposal-staged',rowHasStagedChange(row,item));
        text.textContent=actionText(item,checkbox);
        renderManagedSummary();
      });
    }
    const text=wrapper.querySelector('.discovery-proposed-action-text');
    if(text)text.textContent=actionText(item,checkbox);
    if(!row.dataset.discoveryInitialValues){
      const label=row.querySelector(`input[data-label-for="${CSS.escape(String(item?.candidate_id||''))}"]`);
      const controls=[...row.querySelectorAll('select')];
      row.dataset.discoveryInitialValues=JSON.stringify({label:label?.value??null,selects:controls.map(control=>control.value)});
      label?.addEventListener('input',()=>{
        row.classList.toggle('proposal-staged',rowHasStagedChange(row,item));
        renderManagedSummary();
      });
      controls.forEach(control=>control.addEventListener('change',()=>{
        row.classList.toggle('proposal-staged',rowHasStagedChange(row,item));
        renderManagedSummary();
      }));
    }
    row.classList.toggle('proposal-staged',rowHasStagedChange(row,item));
  }

  function rowHasStagedChange(row,item){
    const checkbox=row.querySelector('input[type="checkbox"][data-id]');
    if(!checkbox||checkbox.disabled)return false;
    const coverage=coverageState(item);
    if(item?.configured_object_id||item?.state==='already_monitored'){
      if(!checkbox.checked)return true;
    }else if(checkbox.checked){
      return true;
    }
    let initial={};
    try{initial=JSON.parse(row.dataset.discoveryInitialValues||'{}')}catch{}
    const label=row.querySelector(`input[data-label-for="${CSS.escape(String(item?.candidate_id||''))}"]`);
    if(initial.label!==undefined&&initial.label!==null&&label&&label.value!==initial.label)return true;
    const selects=[...row.querySelectorAll('select')];
    if(Array.isArray(initial.selects)&&selects.some((control,index)=>control.value!==initial.selects[index]))return true;
    if(coverage&&!checkbox.checked)return false;
    return false;
  }

  function section(title,key,count,open){
    const details=document.createElement('details');
    details.className=`discovery-coverage-section discovery-coverage-${key}`;
    details.dataset.coverageSection=key;
    details.open=open;
    const summary=document.createElement('summary');
    const heading=document.createElement('strong'); heading.textContent=title;
    const tally=document.createElement('span'); tally.className='discovery-section-count'; tally.textContent=String(count);
    summary.append(heading,tally);
    const rows=document.createElement('div'); rows.className='discovery-section-rows';
    details.append(summary,rows);
    return details;
  }

  function subsection(title,key,count,open){
    const details=document.createElement('details');
    details.className=`discovery-subsection discovery-subsection-${key}`;
    details.dataset.discoverySubsection=key;
    details.open=open;
    const summary=document.createElement('summary');
    const heading=document.createElement('strong'); heading.textContent=title;
    const tally=document.createElement('span'); tally.className='discovery-section-count discovery-subsection-count'; tally.textContent=String(count);
    summary.append(heading,tally);
    const rows=document.createElement('div'); rows.className='discovery-subsection-rows';
    details.append(summary,rows);
    return details;
  }

  function rememberedDisclosure(root,selector,dataKey){
    const states=new Map();
    for(const details of root.querySelectorAll(selector)){
      const key=details.dataset[dataKey];
      if(key)states.set(key,details.open);
    }
    return states;
  }

  function sortedEntries(rows){
    return rows.map((row,index)=>({row,item:candidateForRow(row),index})).sort((left,right)=>{
      const leftName=boundedLabel(left.item?.display_name)||boundedLabel(left.item?.label)||boundedLabel(left.item?.candidate_id);
      const rightName=boundedLabel(right.item?.display_name)||boundedLabel(right.item?.label)||boundedLabel(right.item?.candidate_id);
      return collator.compare(leftName,rightName)
        ||collator.compare(String(left.item?.candidate_id||''),String(right.item?.candidate_id||''))
        ||left.index-right.index;
    });
  }

  function groupRows(){
    const root=document.getElementById('results');
    if(!root)return;
    const rows=[...root.querySelectorAll('.candidate')];
    if(!rows.length)return;
    const coverageOpen=rememberedDisclosure(root,'.discovery-coverage-section','coverageSection');
    const subgroupOpen=rememberedDisclosure(root,'.discovery-subsection','discoverySubsection');
    const groups={covered:[],new:[],attention:[]};
    for(const row of rows){
      const item=candidateForRow(row);
      if(!item)continue;
      row.dataset.discoveryCoverageSection=sectionFor(item);
      setCoverageBadge(row,item);
      setRecommendationReason(row,item);
      ensureActionControl(row,item);
      groups[row.dataset.discoveryCoverageSection].push(row);
    }
    const fragments=[];
    if(groups.new.length){
      const details=section('New / not yet monitored',NEW,groups.new.length,coverageOpen.get(NEW)??true);
      const container=details.querySelector('.discovery-section-rows');
      const recommended=[]; const other=[];
      for(const entry of sortedEntries(groups.new)){
        const key=normalizedRecommendation(entry.item)?RECOMMENDED:OTHER;
        entry.row.dataset.discoveryRecommendationSection=key;
        (key===RECOMMENDED?recommended:other).push(entry.row);
      }
      if(recommended.length){
        const child=subsection('Recommended',RECOMMENDED,recommended.length,subgroupOpen.get(RECOMMENDED)??true);
        child.querySelector('.discovery-subsection-rows').append(...recommended); container.append(child);
      }
      if(other.length){
        const child=subsection('Other discoveries',OTHER,other.length,subgroupOpen.get(OTHER)??false);
        child.querySelector('.discovery-subsection-rows').append(...other); container.append(child);
      }
      fragments.push(details);
    }
    if(groups.covered.length){
      const details=section('Already monitored',COVERED,groups.covered.length,coverageOpen.get(COVERED)??false);
      details.querySelector('.discovery-section-rows').append(...groups.covered); fragments.push(details);
    }
    if(groups.attention.length){
      const hasReview=groups.attention.some(row=>candidateForRow(row)?.state==='needs_review');
      const details=section('Auxiliary / needs review',ATTENTION,groups.attention.length,coverageOpen.get(ATTENTION)??hasReview);
      details.querySelector('.discovery-section-rows').append(...groups.attention); fragments.push(details);
    }
    root.replaceChildren(...fragments);
  }

  function stagedCount(){
    let count=0;
    for(const row of document.querySelectorAll('#results .candidate')){
      const item=candidateForRow(row);
      if(item&&rowHasStagedChange(row,item))count++;
    }
    return count;
  }

  function renderManagedSummary(){
    const summary=document.getElementById('resultSummary');
    if(!summary||typeof candidates==='undefined'||!Array.isArray(candidates))return;
    let covered=0,unmonitored=0,attention=0;
    for(const item of candidates){
      const section=sectionFor(item);
      if(section===COVERED)covered++; else if(section===NEW)unmonitored++; else attention++;
    }
    const staged=stagedCount();
    summary.textContent=`${candidates.length} discovered · ${covered} already monitored · ${unmonitored} not yet monitored${attention?` · ${attention} auxiliary/needs review`:''} · ${staged} configuration change${staged===1?'':'s'} selected. Canonical configuration is unchanged.`;
  }

  function selectAllNotYetMonitored(){
    for(const row of document.querySelectorAll('#results .candidate')){
      const item=candidateForRow(row);
      if(!item||sectionFor(item)!==NEW)continue;
      const checkbox=row.querySelector('input[type="checkbox"][data-id]');
      if(!checkbox||checkbox.disabled||checkbox.checked)continue;
      checkbox.checked=true;
      checkbox.dispatchEvent(new Event('change',{bubbles:true}));
    }
    renderManagedSummary();
  }

  function applyManagedPresentation(){
    groupRows(); renderManagedSummary();
    const selectNew=document.getElementById('selectNew');
    if(selectNew){selectNew.textContent='Select all not yet monitored'; selectNew.onclick=selectAllNotYetMonitored;}
  }

  function install(){
    if(typeof render!=='function'||typeof summarize!=='function'){
      console.warn('managed discovery coverage presentation could not bind base renderer'); return;
    }
    const baseRender=render; const baseSummarize=summarize;
    render=function managedCoverageRender(){baseRender(); applyManagedPresentation();};
    summarize=function managedCoverageSummary(){baseSummarize(); applyManagedPresentation();};
    applyManagedPresentation();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  else install();
})();
