'use strict';

(()=>{
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));
  const sleep=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
  const pending=new Map();
  let lastModel=null,workspaceCsrf=null,prepared=null,projectionGeneration=0;
  let groupedMembers=[];
  const appRoot=document.getElementById('app');
  if(appRoot)appRoot.style.visibility='hidden';

  function stateClass(mode){return mode==='setup_draft'?'staged':'live';}
  function editHref(item){
    const id=encodeURIComponent(item.object_id||item.id||'');
    return `/settings/advanced?object=${id}`;
  }
  function importanceLabel(value){
    if(value==='not_required')return 'Not required';
    if(value==='ignored')return 'Ignored';
    if(value==='mixed')return 'Mixed';
    return 'Required';
  }
  function policyKey(kind,item,extra=''){
    if(kind==='connection'){
      const identity=item.authority_identity||{};
      return `connection:${identity.adapter||item.adapter||''}:${identity.endpoint||''}:${identity.scope||''}`;
    }
    if(kind==='ability')return `ability:${extra}:${item.id}`;
    return `${kind}:${item.id}`;
  }
  function decisionFor(kind,item,extra=''){
    const decision={kind,action:'policy',enabled:item.enabled!==false,importance:item.importance||'required'};
    if(kind==='connection')decision.authority_identity=item.authority_identity;
    else if(kind==='ability'){
      decision.object_id=extra;
      decision.capability_id=item.id;
    }else decision.id=item.id;
    return decision;
  }
  function currentDecision(kind,item,extra=''){
    return pending.get(policyKey(kind,item,extra))||decisionFor(kind,item,extra);
  }
  function setPolicyPending(kind,item,extra,field,value){
    const key=policyKey(kind,item,extra);
    const desired={...currentDecision(kind,item,extra),[field]:value};
    const baseline=decisionFor(kind,item,extra);
    if(desired.enabled===baseline.enabled && desired.importance===baseline.importance)pending.delete(key);
    else pending.set(key,desired);
    prepared=null;
    updatePendingUi();
  }
  function policyHtml(kind,item,extra=''){
    const key=policyKey(kind,item,extra),desired=currentDecision(kind,item,extra);
    const effective=item.effective_enabled!==false;
    const disabledByParent=item.enabled!==false&&!effective;
    return `<div class="policy" data-policy-key="${esc(key)}">
      <label><input class="workspace-enabled" data-kind="${esc(kind)}" data-extra="${esc(extra)}" data-id="${esc(item.id)}" type="checkbox" ${desired.enabled?'checked':''}> Enabled</label>
      <select class="workspace-importance" data-kind="${esc(kind)}" data-extra="${esc(extra)}" data-id="${esc(item.id)}" aria-label="Importance for ${esc(item.label||item.id)}">
        <option value="required" ${desired.importance==='required'?'selected':''}>Required</option>
        <option value="not_required" ${desired.importance==='not_required'?'selected':''}>Not required</option>
        <option value="ignored" ${desired.importance==='ignored'?'selected':''}>Ignored</option>
      </select>
      ${disabledByParent?'<span class="state disabled">Disabled by parent</span>':''}
    </div>`;
  }
  function abilityHtml(objectId,ability){
    const connections=(ability.connection_ids||[]).length;
    return `<div style="display:grid;grid-template-columns:minmax(150px,1fr) auto;gap:8px;align-items:center;padding:6px 0;border-top:1px solid #1e3048">
      <div><span class="ability">${esc(ability.label||ability.kind||ability.id)}</span><span class="relationship"> ${connections} Connection${connections===1?'':'s'}</span></div>
      ${policyHtml('ability',ability,objectId)}
    </div>`;
  }
  function nodeRow(kind,item,mode){
    const abilities=item.abilities||[];
    const actionNames=(item.actions||[]).map(a=>a.kind==='wol'?'WOL':a.label||a.kind).filter(Boolean);
    const detail=[item.kind,item.address,actionNames.length?actionNames.join(', '):null].filter(Boolean).join(' · ');
    const grouped=item.grouped_object?.members?.length
      ?`${item.grouped_object.members.length} ordered source Objects`
      :null;
    return `<div class="item" data-workspace-${esc(kind)}="${esc(item.id)}">
      <div><strong>${esc(item.label||item.id)}</strong><small>${esc(grouped||detail||'Configured')}</small><div class="abilities">${abilities.map(a=>`<span class="ability">${esc(a.label||a.kind||a.id)}</span>`).join('')}</div></div>
      <div class="detail">${policyHtml(kind,item)}<small>${mode==='setup_draft'?'Staged in Setup Draft':'Canonical monitoring intent'}${item.effective_enabled===false&&item.enabled!==false?' · inactive through parent':''}</small>${abilities.length?`<details><summary class="relationship" style="cursor:pointer">${abilities.length} Abilit${abilities.length===1?'y':'ies'} / Metrics</summary>${abilities.map(a=>abilityHtml(item.id,a)).join('')}</details>`:''}</div>
      <a class="button" href="${editHref(item)}">Edit</a>
    </div>`;
  }
  function connectionRow(item,mode){
    const adapter=String(item.adapter||'connection').toLowerCase();
    const detail=[];
    if(item.url)detail.push(item.url);
    else if(item.base_url)detail.push(item.base_url);
    else if(item.host)detail.push(`${item.host}${item.port?`:${item.port}`:''}`);
    else if(item.endpoint)detail.push(item.endpoint);
    if(adapter==='unifi')detail.push(`site ${item.site_id||'default'}`);
    if(adapter==='portainer'){
      const envs=Array.isArray(item.environment_ids)?item.environment_ids:[];
      detail.push(envs.length?`${envs.length} selected environment${envs.length===1?'':'s'}`:'all visible environments');
    }
    const exposed=(item.exposes_object_ids||[]).length;
    return `<div class="item" data-workspace-connection="${esc(item.id)}">
      <div><strong>${esc(item.label||adapter)}</strong><small>${esc(detail.join(' · ')||`${adapter} data source`)}</small>${exposed?`<div class="relationship">Exposes ${exposed} Object${exposed===1?'':'s'}</div>`:''}</div>
      <div class="detail">${policyHtml('connection',item)}<small>${mode==='setup_draft'?'Staged Connection':'Configured Connection'} · ${importanceLabel(item.importance)}</small></div>
      <a class="button" href="${editHref(item)}">Edit</a>
    </div>`;
  }
  function graphRow(item,mode){
    return `<div class="item" data-workspace-graph="${esc(item.id)}"><div><strong>${esc(item.label||item.id||'Graph')}</strong><small>position ${Number(item.position)+1} · ${esc(item.kind||'widget')}</small></div><div class="detail"><span class="state ${stateClass(mode)}">${mode==='setup_draft'?'Staged order':'Canonical order'}</span></div><a class="button" href="/settings/dashboard">Edit</a></div>`;
  }

  async function csrf(){
    if(workspaceCsrf)return workspaceCsrf;
    const response=await fetch('/api/v2/config/session',{headers:{Accept:'application/json'},cache:'no-store'});
    const text=await response.text();let body={};try{body=text?JSON.parse(text):{};}catch{body={error:text};}
    if(!response.ok)throw new Error(body.error||text||`HTTP ${response.status}`);
    workspaceCsrf=body.csrf_token;
    return workspaceCsrf;
  }
  async function apiRequest(url,options={}){
    options.headers={...(options.headers||{}),Accept:'application/json'};
    if(options.body&&!options.headers['Content-Type'])options.headers['Content-Type']='application/json';
    if(options.method&&options.method!=='GET')options.headers['X-MonitorBox-CSRF']=await csrf();
    const response=await fetch(url,options),text=await response.text();let body={};
    try{body=text?JSON.parse(text):{};}catch{body={error:text};}
    if(!response.ok)throw new Error(body.error||text||`HTTP ${response.status}`);
    return body;
  }

  function ensurePendingBar(){
    let bar=document.getElementById('workspacePending');
    if(bar)return bar;
    bar=document.createElement('div');bar.id='workspacePending';bar.className='status';bar.style.margin='0 0 18px';bar.style.display='none';
    const summary=document.getElementById('summary');summary?.insertAdjacentElement('afterend',bar);
    return bar;
  }
  function ensureReviewDialog(){
    let dialog=document.getElementById('workspaceChangeReview');
    if(dialog)return dialog;
    dialog=document.createElement('dialog');dialog.id='workspaceChangeReview';
    dialog.innerHTML='<div class="row"><div><div class="eyebrow">Transactional preview</div><h2 style="margin:2px 0">Review configuration changes</h2></div><span class="spacer"></span><button id="workspaceCloseReview" class="button">Close</button></div><div id="workspaceReviewSummary" class="status"></div><div id="workspaceReviewItems" class="status" style="margin-top:10px"></div><details style="margin-top:10px"><summary style="cursor:pointer;color:var(--muted)">Technical change details</summary><pre id="workspaceReviewChanges"></pre></details><div class="row" style="margin-top:14px"><span class="spacer"></span><button id="workspaceApplyChanges" class="button primary">Apply changes</button></div>';
    document.body.append(dialog);
    dialog.querySelector('#workspaceCloseReview').onclick=()=>dialog.close();
    dialog.querySelector('#workspaceApplyChanges').onclick=applyPrepared;
    return dialog;
  }
  function decisionDescription(decision){
    if(decision.kind==='grouped_object')return `Create Grouped Object — ${decision.label}`;
    const label=decision._label||decision.id||decision.capability_id||decision.kind;
    const parts=[];
    if('enabled' in decision)parts.push(decision.enabled?'Enabled':'Disabled');
    if(decision.importance)parts.push(importanceLabel(decision.importance));
    return `${decision.kind[0].toUpperCase()+decision.kind.slice(1)} — ${label}: ${parts.join(' · ')}`;
  }
  function updatePendingUi(){
    const bar=ensurePendingBar(),count=pending.size;
    if(!bar)return;
    const finish=document.getElementById('finishStatus');
    const finishButton=document.getElementById('prepareFinish');
    if(!count){
      bar.style.display='none';bar.replaceChildren();
      if(finishButton&&lastModel?.mode==='setup_draft')finishButton.disabled=false;
      if(finish&&lastModel?.mode==='setup_draft')finish.textContent='Setup is in progress. Review the complete Setup Draft before activating monitoring.';
      return;
    }
    bar.style.display='flex';bar.style.alignItems='center';bar.style.gap='10px';bar.style.flexWrap='wrap';
    const text=document.createElement('span');text.textContent=`${count} pending configuration change${count===1?'':'s'} · nothing becomes authoritative until review and Apply.`;
    const space=document.createElement('span');space.className='spacer';
    const reset=document.createElement('button');reset.className='button';reset.type='button';reset.textContent='Discard pending';reset.onclick=()=>{pending.clear();prepared=null;renderModel(lastModel);};
    const button=document.createElement('button');button.className='button primary';button.type='button';button.textContent=`Review ${count} change${count===1?'':'s'}`;button.onclick=reviewPending;
    bar.replaceChildren(text,space,reset,button);
    if(finishButton&&lastModel?.mode==='setup_draft')finishButton.disabled=true;
    if(finish&&lastModel?.mode==='setup_draft')finish.textContent='Review or discard pending Workspace changes before finishing Setup.';
  }
  function lookupItem(kind,id,extra=''){
    if(!lastModel)return null;
    if(kind==='connection')return (lastModel.connections||[]).find(item=>item.id===id)||null;
    if(kind==='system')return (lastModel.systems||[]).find(item=>item.id===id)||null;
    if(kind==='object')return (lastModel.objects||[]).find(item=>item.id===id)||null;
    if(kind==='ability'){
      const owner=[...(lastModel.systems||[]),...(lastModel.objects||[])].find(item=>item.id===extra);
      return owner?.abilities?.find(item=>item.id===id)||null;
    }
    return null;
  }
  function bindPolicyControls(){
    for(const input of document.querySelectorAll('.workspace-enabled')){
      input.onchange=()=>{
        const kind=input.dataset.kind,id=input.dataset.id,extra=input.dataset.extra||'';
        const item=lookupItem(kind,id,extra);if(!item)return;
        setPolicyPending(kind,item,extra,'enabled',input.checked);
      };
    }
    for(const select of document.querySelectorAll('.workspace-importance')){
      select.onchange=()=>{
        const kind=select.dataset.kind,id=select.dataset.id,extra=select.dataset.extra||'';
        const item=lookupItem(kind,id,extra);if(!item)return;
        setPolicyPending(kind,item,extra,'importance',select.value);
      };
    }
  }

  async function reviewPending(){
    const bar=ensurePendingBar();
    try{
      if(!pending.size)return;
      const decisions=[...pending.values()].map(({_label,...decision})=>decision);
      const trigger=bar?.querySelector('.primary');if(trigger){trigger.disabled=true;trigger.textContent='Validating…';}
      const mutation=await apiRequest('/api/v2/config/workspace/mutate',{method:'POST',body:JSON.stringify({decisions})});
      if(!mutation.changed)throw new Error('The pending decisions no longer change configuration. Reload the Workspace.');
      let preview=mutation.preview,candidateId=null;
      if(!mutation.setup_mode){
        const candidate=await apiRequest('/api/v2/config/candidates',{method:'POST',body:JSON.stringify({config:mutation.config})});
        candidateId=candidate.candidate_id;preview=candidate.preview;
      }
      prepared={setup:!!mutation.setup_mode,config:mutation.config,candidateId,preview};
      const dialog=ensureReviewDialog();
      dialog.querySelector('#workspaceReviewSummary').textContent=`${preview.summary.added} added · ${preview.summary.modified} modified · ${preview.summary.removed} removed`;
      dialog.querySelector('#workspaceReviewItems').textContent=[...pending.values()].map(decisionDescription).join('\n');
      dialog.querySelector('#workspaceReviewChanges').textContent=JSON.stringify(preview.changes,null,2);
      const apply=dialog.querySelector('#workspaceApplyChanges');apply.disabled=false;apply.textContent=mutation.setup_mode?'Add changes to Setup Draft':'Apply changes';
      dialog.showModal();
    }catch(error){
      if(bar){bar.style.display='block';bar.textContent=`Pending changes are not valid: ${error.message}`;}
    }finally{
      const trigger=bar?.querySelector('.primary');if(trigger)trigger.disabled=false;
    }
  }
  async function applyPrepared(){
    const dialog=ensureReviewDialog(),apply=dialog.querySelector('#workspaceApplyChanges'),summary=dialog.querySelector('#workspaceReviewSummary');
    try{
      if(!prepared)return;
      apply.disabled=true;apply.textContent=prepared.setup?'Staging…':'Applying…';
      if(prepared.setup){
        const staged=await apiRequest('/api/v2/config/setup/draft',{method:'POST',body:JSON.stringify({config:prepared.config})});
        summary.textContent=`Added to Setup Draft. ${staged.cumulative_preview.summary.added} added · ${staged.cumulative_preview.summary.modified} modified · ${staged.cumulative_preview.summary.removed} removed versus bootstrap.`;
        pending.clear();prepared=null;dialog.close();await loadSemanticWorkspace();
      }else{
        if(!prepared.candidateId)throw new Error('validated candidate is missing');
        const applied=await apiRequest(`/api/v2/config/candidates/${encodeURIComponent(prepared.candidateId)}/apply`,{method:'POST'});
        summary.textContent=`Revision ${applied.revision} applied. ${applied.runtime_reconcile}.`;
        pending.clear();prepared=null;setTimeout(()=>location.href='/settings',900);
      }
    }catch(error){summary.textContent=`Apply failed: ${error.message}`;apply.disabled=false;apply.textContent=prepared?.setup?'Add changes to Setup Draft':'Apply changes';}
  }

  function renderModel(model){
    if(!model)return;
    lastModel=model;
    const systems=document.getElementById('systemRows'),connections=document.getElementById('connectionRows'),objects=document.getElementById('objectRows'),dashboard=document.getElementById('dashboardRows'),summary=document.getElementById('summary'),site=document.getElementById('siteHome');
    if(site&&model.site)site.textContent=model.site.label||model.site.id||'Site';
    if(systems)systems.innerHTML=model.systems?.length?model.systems.map(item=>nodeRow('system',item,model.mode)).join(''):'<div class="empty">No Systems configured yet.</div>';
    if(connections)connections.innerHTML=model.connections?.length?model.connections.map(item=>connectionRow(item,model.mode)).join(''):'<div class="empty">No Connections configured yet. Add a System and choose how MonitorBox may obtain data.</div>';
    if(objects)objects.innerHTML=model.objects?.length?model.objects.map(item=>nodeRow('object',item,model.mode)).join(''):'<div class="empty">No Objects discovered/adopted yet.</div>';
    if(dashboard){
      const widgets=(model.dashboard?.widgets||[]).filter(item=>item.enabled!==false);
      dashboard.innerHTML=widgets.length?widgets.map(item=>graphRow(item,model.mode)).join(''):'<div class="empty">No dashboard graphs selected.</div>';
    }
    if(summary&&model.summary){
      const parts=[`${model.summary.systems||0} systems`,`${model.summary.connections||0} connections`,`${model.summary.objects||0} objects`,`${model.summary.abilities||0} abilities`,`${model.summary.graphs||0} graphs`,model.mode==='setup_draft'?`${model.summary.staged_credentials||0} staged credentials`:`revision ${model.revision}`];
      summary.innerHTML=parts.map((text,index)=>`<span class="pill ${model.mode==='setup_draft'&&index===parts.length-1?'pending':''}">${esc(text)}</span>`).join('');
    }
    bindPolicyControls();
    updatePendingUi();
  }

  function openGroupedDialog(){
    if(!lastModel)return;
    groupedMembers=[];
    const dialog=document.getElementById('groupedObjectDialog');
    document.getElementById('groupedObjectName').value='';
    document.getElementById('groupedObjectSearch').value='';
    renderGroupedMatches('');renderGroupedMembers();dialog?.showModal();
  }
  function sourceObjects(){return (lastModel?.objects||[]).filter(item=>!item.grouped_object?.members?.length);}
  function renderGroupedMatches(query){
    const root=document.getElementById('groupedObjectMatches');if(!root)return;
    const q=String(query||'').trim().casefold?.()||String(query||'').trim().toLowerCase();
    const name=document.getElementById('groupedObjectName')?.value.trim().toLowerCase()||'';
    const candidates=sourceObjects().filter(item=>!groupedMembers.includes(item.id)).filter(item=>!q||String(item.label||item.id).toLowerCase().includes(q)||String(item.id).toLowerCase().includes(q)).sort((a,b)=>{
      const ae=String(a.label||'').toLowerCase()===name?0:1,be=String(b.label||'').toLowerCase()===name?0:1;
      return ae-be||String(a.label||a.id).localeCompare(String(b.label||b.id));
    }).slice(0,30);
    root.innerHTML=candidates.length?candidates.map(item=>`<button type="button" class="button grouped-match" data-id="${esc(item.id)}" style="margin:3px">${esc(item.label||item.id)} · ${esc((item.abilities||[]).map(a=>a.label||a.kind).slice(0,2).join(', ')||item.kind)}</button>`).join(''):'No matching source Objects.';
    for(const button of root.querySelectorAll('.grouped-match'))button.onclick=()=>{groupedMembers.push(button.dataset.id);renderGroupedMembers();renderGroupedMatches(document.getElementById('groupedObjectSearch').value);};
  }
  function renderGroupedMembers(){
    const root=document.getElementById('groupedObjectMembers');if(!root)return;
    const lookup=new Map(sourceObjects().map(item=>[item.id,item]));
    root.innerHTML=groupedMembers.length?groupedMembers.map((id,index)=>`<div class="row" style="margin:5px 0"><strong>Item ${index+1}${index===0?' · Primary':''}</strong><span>${esc(lookup.get(id)?.label||id)}</span><span class="spacer"></span><button type="button" class="button grouped-up" data-index="${index}" ${index===0?'disabled':''}>↑</button><button type="button" class="button grouped-down" data-index="${index}" ${index===groupedMembers.length-1?'disabled':''}>↓</button><button type="button" class="button grouped-remove" data-index="${index}">Remove</button></div>`).join(''):'Add at least two source Objects. Item 1 supplies default Abilities; later Items are automatic fallbacks.';
    for(const button of root.querySelectorAll('.grouped-remove'))button.onclick=()=>{groupedMembers.splice(Number(button.dataset.index),1);renderGroupedMembers();renderGroupedMatches(document.getElementById('groupedObjectSearch').value);};
    for(const button of root.querySelectorAll('.grouped-up'))button.onclick=()=>{const i=Number(button.dataset.index);[groupedMembers[i-1],groupedMembers[i]]=[groupedMembers[i],groupedMembers[i-1]];renderGroupedMembers();};
    for(const button of root.querySelectorAll('.grouped-down'))button.onclick=()=>{const i=Number(button.dataset.index);[groupedMembers[i+1],groupedMembers[i]]=[groupedMembers[i],groupedMembers[i+1]];renderGroupedMembers();};
  }
  function saveGroupedObject(){
    const name=document.getElementById('groupedObjectName').value.trim();
    const status=document.getElementById('groupedObjectMembers');
    if(!name){status.textContent='Enter a Grouped Object name.';return;}
    if(groupedMembers.length<2){status.textContent='Add at least two source Objects.';return;}
    const key=`grouped-object:new:${Date.now()}`;
    pending.set(key,{kind:'grouped_object',action:'create',label:name,member_ids:[...groupedMembers],_label:name});
    prepared=null;document.getElementById('groupedObjectDialog')?.close();updatePendingUi();
  }

  async function authenticated(){
    try{
      const response=await fetch('/api/v2/config/status',{headers:{Accept:'application/json'},cache:'no-store'});
      if(!response.ok)return false;
      const body=await response.json();
      return body.authenticated===true;
    }catch{return false;}
  }
  async function awaitAuthentication(generation){
    for(let attempt=0;attempt<160;attempt++){
      if(generation!==projectionGeneration)return false;
      if(await authenticated())return true;
      await sleep(125);
    }
    return false;
  }
  async function loadSemanticWorkspace(){
    try{
      const model=await apiRequest('/api/v2/config/workspace/state');
      renderModel(model);
      return true;
    }catch(error){
      const finish=document.getElementById('finishStatus');if(finish)finish.textContent=`Workspace state refresh failed: ${error.message}`;
      return false;
    }
  }
  function failProjection(message,generation){
    if(generation!==projectionGeneration)return;
    document.documentElement.dataset.workspaceProjection='failed';
    if(appRoot){appRoot.classList.remove('hidden');appRoot.style.visibility='';}
    const finish=document.getElementById('finishStatus');if(finish)finish.textContent=`Workspace state refresh failed: ${message}`;
  }
  async function awaitSemanticWorkspace(){
    const generation=++projectionGeneration;
    document.documentElement.dataset.workspaceProjection='loading';
    if(appRoot)appRoot.style.visibility='hidden';
    if(!(await awaitAuthentication(generation))){
      if(generation!==projectionGeneration)return;
      document.documentElement.dataset.workspaceProjection='awaiting-auth';
      return;
    }
    let ready=false;
    for(let attempt=0;attempt<80;attempt++){
      if(generation!==projectionGeneration)return;
      if(await loadSemanticWorkspace()){ready=true;break;}
      await sleep(125);
    }
    if(!ready){failProjection('semantic configuration state did not become available after authentication.',generation);return;}
    if(generation!==projectionGeneration)return;
    document.documentElement.dataset.workspaceProjection='ready';
    if(appRoot){appRoot.classList.remove('hidden');appRoot.style.visibility='';}
  }

  document.getElementById('createGroupedObject')?.addEventListener('click',openGroupedDialog);
  document.getElementById('groupedObjectSearch')?.addEventListener('input',event=>renderGroupedMatches(event.target.value));
  document.getElementById('groupedObjectName')?.addEventListener('input',()=>renderGroupedMatches(document.getElementById('groupedObjectSearch').value));
  document.getElementById('saveGroupedObject')?.addEventListener('click',saveGroupedObject);
  window.addEventListener('monitorbox-workspace-authenticated',()=>{workspaceCsrf=null;awaitSemanticWorkspace();});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')awaitSemanticWorkspace();});
  document.getElementById('loginButton')?.addEventListener('click',()=>setTimeout(awaitSemanticWorkspace,150));
  awaitSemanticWorkspace();
})();
