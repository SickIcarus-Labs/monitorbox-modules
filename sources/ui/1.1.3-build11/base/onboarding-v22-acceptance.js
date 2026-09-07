'use strict';

(()=>{
  const path=location.pathname;
  const quickAdd=path==='/settings/quick-add';
  const destructive=path==='/settings/advanced/rerun-first-launch';
  if(!quickAdd&&!destructive)return;

  const kindLabels={
    host:'Host',
    network_device:'Network device',
    appliance:'Appliance',
    remote_site:'Remote site',
  };
  const providerLabels={
    portainer:'Portainer',
    unifi:'UniFi Network',
    scrypted:'Scrypted',
    snmp:'SNMP',
    nut:'NUT',
    http:'HTTP(S)',
  };
  const humanize=value=>String(value||'').trim().replace(/[_-]+/g,' ').replace(/^./,c=>c.toUpperCase());
  const kindLabel=value=>kindLabels[String(value||'').toLowerCase()]||humanize(value||'System');
  const providerLabel=value=>providerLabels[String(value||'').toLowerCase()]||humanize(value);
  const existingMutationReviewRows=new Map();

  function provenanceText(item){
    const provenance=item?.provenance;
    if(!provenance||typeof provenance!=='object')return'';
    const provider=providerLabel(provenance.provider||'');
    const source=String(provenance.source||'').toLowerCase();
    if(source==='provider_discovery'&&provider)return`discovered from ${provider}`;
    if(provider)return provider;
    if(source)return humanize(source);
    return'';
  }

  function decorateSystems(summary){
    const systems=Array.isArray(summary?.systems)?summary.systems:[];
    const choices=[...document.querySelectorAll('#existingSystems .system-choice')];
    choices.forEach((choice,index)=>{
      const item=systems[index];
      const text=choice.querySelector('span');
      if(!item||!text)return;
      text.querySelector('[data-v22-system-meta]')?.remove();
      const metadata=document.createElement('div');
      metadata.className='muted';
      metadata.dataset.v22SystemMeta='1';
      const provenance=provenanceText(item);
      metadata.textContent=`${kindLabel(item.kind)}${provenance?` · ${provenance}`:''}`;
      const address=text.querySelector('.muted');
      text.insertBefore(metadata,address||null);
    });
  }

  function decorateConnectionOwner(card,candidate){
    const body=card.querySelector('.connection-head > div');
    if(!body||body.querySelector('[data-v22-owner]'))return;
    const owner=document.createElement('div');
    owner.className='muted';
    owner.dataset.v22Owner='1';
    const label=candidate.system_label||candidate.system_id||'Unknown System';
    const kind=candidate.system_kind?` · ${kindLabel(candidate.system_kind)}`:'';
    owner.textContent=`System: ${label}${kind}`;
    body.append(owner);
  }

  function unifiFields(candidate,{freshSecrets=false}={}){
    const url=escapeHtml(candidate.values?.base_url||candidate.endpoint||'https://');
    const secretAttr=freshSecrets?' data-fresh-secret':'';
    return `<label class="field">Display name<input data-key="label" value="UniFi Network"></label>`+
      `<label class="field">Controller URL<input data-key="base_url" value="${url}"></label>`+
      `<label class="field"${secretAttr}>Username<input data-key="username" autocomplete="off"></label>`+
      `<label class="field"${secretAttr}>Password<input data-key="password" type="password" autocomplete="off"></label>`+
      `<label class="field">Network site<input data-key="network_site" value="default"></label>`;
  }

  function scryptedFieldsForDestructive(candidate){
    const url=escapeHtml(candidate.values?.base_url||candidate.endpoint||'https://');
    return `<label class="field">Display name<input data-key="label" value="Scrypted cameras"></label>`+
      `<label class="field">Server URL<input data-key="base_url" value="${url}"></label>`+
      `<label class="field" data-fresh-secret>Username<input data-key="username" autocomplete="off"></label>`+
      `<label class="field" data-fresh-secret>Password<input data-key="password" type="password" autocomplete="off"></label>`+
      `<label class="field">Excluded camera names (optional)<input data-key="excluded_camera_names"></label>`;
  }

  function ensureProviderFields(card,candidate,{destructiveMode=false}={}){
    const fields=card.querySelector('.connection-fields');
    if(!fields||fields.querySelector('[data-key]'))return;
    if(candidate.kind==='unifi')fields.innerHTML=unifiFields(candidate,{freshSecrets:destructiveMode});
    else if(destructiveMode&&candidate.kind==='scrypted')fields.innerHTML=scryptedFieldsForDestructive(candidate);
    const reuse=card.querySelector('[data-role="reuse"]');
    if(reuse)reuse.dispatchEvent(new Event('change'));
  }

  function enforceAutomaticTlsPolicy(card,candidate){
    const fields=card.querySelector('.connection-fields');
    if(!fields)return;
    for(const control of fields.querySelectorAll('[data-key="verify_tls"]')){
      const wrapper=control.closest('label');
      if(wrapper)wrapper.remove();
      else control.remove();
    }
    if(!['portainer','http','http_service','unifi'].includes(candidate?.kind))return;
    const strict=document.createElement('input');
    strict.type='hidden';
    strict.dataset.key='verify_tls';
    strict.value='true';
    strict.dataset.v22AutomaticTls='strict-first';
    fields.append(strict);
  }

  function placeConnectionCancel(label,redirect){
    const actions=document.querySelector('#connections > .actions');
    if(!actions)return;
    const matches=[...document.querySelectorAll('#connections button')]
      .filter(button=>String(button.textContent||'').trim()===label);
    let button=matches.find(item=>item.dataset.v22ConnectionCancel==='1')||matches[0]||null;
    for(const duplicate of matches){
      if(duplicate!==button)duplicate.remove();
    }
    if(!button){
      button=document.createElement('button');
      button.textContent=label;
    }
    button.type='button';
    button.className='button danger';
    button.dataset.v22ConnectionCancel='1';
    button.onclick=()=>{
      if(typeof discard==='function')void discard();
      else location.href=redirect;
    };
    if(button.parentElement!==actions)actions.append(button);
  }

  function placeDestructiveStageCancel(sectionId){
    const actions=document.querySelector(`#${sectionId} .actions`);
    if(!actions)return;
    let button=actions.querySelector(`button[data-v22-destructive-stage-cancel="${sectionId}"]`);
    if(!button){
      button=document.createElement('button');
      button.type='button';
      button.className='button danger';
      button.textContent='Cancel destructive setup';
      button.dataset.v22DestructiveStageCancel=sectionId;
      actions.append(button);
    }
    button.onclick=()=>{
      if(typeof discard==='function')void discard();
      else location.href='/settings/advanced';
    };
  }

  function savedSecretField(key,label){
    return `<label class="field">Replacement ${label} (optional)<input data-existing-key="${key}" type="password" autocomplete="off" placeholder="Keep saved credential"></label>`;
  }

  function configuredValue(candidate,key,fallback=''){
    const value=candidate?.configured_values?.[key];
    return value===undefined||value===null?fallback:value;
  }

  function existingEditFields(candidate){
    const kind=candidate.kind;
    const value=(key,fallback='')=>escapeHtml(configuredValue(candidate,key,fallback));
    if(kind==='portainer')return `<label class="field">Display name<input data-existing-key="label" value="${value('label','Docker via Portainer')}"></label>`+
      `<label class="field">Controller URL<input data-existing-key="base_url" value="${value('base_url',candidate.endpoint)}"></label>`+
      savedSecretField('api_key','API key');
    if(kind==='nut')return `<label class="field">Display name<input data-existing-key="label" value="${value('label','UPS')}"></label>`+
      `<label class="field">Host<input data-existing-key="host" value="${value('host')}"></label>`+
      `<label class="field">Port<input data-existing-key="port" inputmode="numeric" value="${value('port',3493)}"></label>`+
      `<label class="field">UPS identifier<input data-existing-key="ups" value="${value('ups')}"></label>`;
    if(kind==='http'){
      const statuses=configuredValue(candidate,'statuses',[200]);
      const rendered=Array.isArray(statuses)?statuses.join(','):String(statuses||'200');
      return `<label class="field">Display name<input data-existing-key="label" value="${value('label','Service')}"></label>`+
        `<label class="field">URL<input data-existing-key="url" value="${value('url',candidate.endpoint)}"></label>`+
        `<label class="field">Accepted status codes<input data-existing-key="statuses" value="${escapeHtml(rendered)}"></label>`;
    }
    if(kind==='unifi')return `<label class="field">Display name<input data-existing-key="label" value="${value('label','UniFi Network')}"></label>`+
      `<label class="field">Controller URL<input data-existing-key="base_url" value="${value('base_url',candidate.endpoint)}"></label>`+
      `<label class="field">Network site<input data-existing-key="network_site" value="${value('network_site','default')}"></label>`+
      savedSecretField('username','username')+savedSecretField('password','password');
    if(kind==='scrypted')return `<label class="field">Display name<input data-existing-key="label" value="${value('label','Scrypted cameras')}"></label>`+
      `<label class="field">Server URL<input data-existing-key="base_url" value="${value('base_url',candidate.endpoint)}"></label>`+
      `<label class="field">Excluded camera names (optional)<input data-existing-key="excluded_camera_names" value="${value('excluded_camera_names')}"></label>`+
      savedSecretField('username','username')+savedSecretField('password','password');
    if(kind==='snmp'){
      const mode=String(configuredValue(candidate,'snmp_mode','community'));
      const secrets=mode==='v3'
        ?savedSecretField('username','username')+savedSecretField('auth_password','auth password')+savedSecretField('privacy_password','privacy password')
        :savedSecretField('community','community string');
      return `<div class="muted" style="grid-column:1/-1">Credential mode remains ${escapeHtml(mode==='v3'?'SNMPv3':'community')}; Connection edit does not rewrite the provider schema.</div>`+
        `<label class="field">Host<input data-existing-key="host" value="${value('host')}"></label>`+
        `<label class="field">Port<input data-existing-key="port" inputmode="numeric" value="${value('port',161)}"></label>`+secrets;
    }
    return '<div class="muted">This Connection type does not expose editable fields.</div>';
  }

  function existingEditValues(editor){
    const values={};
    for(const field of editor.querySelectorAll('[data-existing-key]'))values[field.dataset.existingKey]=field.value;
    return values;
  }

  async function mutateExisting(candidate,action,values={}){
    if(!session?.session_id)throw new Error('Quick Add session is missing.');
    const label=providerLabel(candidate.kind)||'Connection';
    status('connectionStatus',action==='edit'?`Validating ${label} changes…`:`Staging removal of ${label}…`);
    const body={
      configured_object_id:candidate.configured_object_id,
      kind:candidate.kind,
      endpoint:candidate.endpoint,
    };
    if(action==='edit')body.values=values;
    try{
      session=await api(`/api/v2/config/onboarding/${encodeURIComponent(session.session_id)}/connections/existing/${action}`,{
        method:'POST',body:JSON.stringify(body),
      });
      const mutation=session?.existing_connection_mutation;
      if(mutation?.object_id){
        const objectId=String(mutation.object_id);
        existingMutationReviewRows.set(objectId,{
          object_id:objectId,
          label:String(candidate.label||providerLabel(candidate.kind)||objectId),
          action:action==='remove'?'remove':'edit',
        });
        window.mbExistingConnectionMutations=[...existingMutationReviewRows.values()];
      }
      renderConnections(session.connections||[]);
      status('connectionStatus',action==='edit'?`${label} changes validated and staged. Nothing is live until Finish.`:`${label} removal staged. Nothing is live until Finish.`,false,true);
    }catch(error){
      status('connectionStatus',String(error?.message||error),true);
    }
  }

  function decorateExistingMutationControls(card,candidate){
    if(candidate.already_configured!==true||!candidate.configured_object_id)return;
    const head=card.querySelector('.connection-head > div');
    if(head){
      const notes=[...head.querySelectorAll('.muted')];
      const preservation=notes.find(item=>String(item.textContent||'').startsWith('Quick Add preserves'));
      if(preservation)preservation.textContent='This Connection stays live and unchanged until Finish; Edit/Remove below modify only this disposable Quick Add draft.';
    }
    const fields=card.querySelector('.connection-fields');
    if(!fields)return;
    fields.innerHTML='';
    fields.classList.remove('grid');

    const actions=document.createElement('div');
    actions.className='actions';
    actions.dataset.v22ExistingActions='1';
    const edit=document.createElement('button');
    edit.type='button';
    edit.className='button';
    edit.textContent='Edit';
    const remove=document.createElement('button');
    remove.type='button';
    remove.className='button danger';
    remove.textContent='Remove';
    actions.append(edit,remove);
    fields.append(actions);

    const editor=document.createElement('div');
    editor.className='grid hidden';
    editor.dataset.v22ExistingEditor='1';
    editor.innerHTML=existingEditFields(candidate);
    const editorActions=document.createElement('div');
    editorActions.className='actions';
    editorActions.style.gridColumn='1/-1';
    const save=document.createElement('button');
    save.type='button';
    save.className='button primary';
    save.textContent='Validate and stage changes';
    const cancel=document.createElement('button');
    cancel.type='button';
    cancel.className='button';
    cancel.textContent='Cancel edit';
    editorActions.append(save,cancel);
    editor.append(editorActions);
    fields.append(editor);

    edit.onclick=()=>editor.classList.remove('hidden');
    cancel.onclick=()=>editor.classList.add('hidden');
    save.onclick=()=>void mutateExisting(candidate,'edit',existingEditValues(editor));
    remove.onclick=()=>{
      if(confirm(`Remove ${providerLabel(candidate.kind)||'this Connection'} from monitoring when Quick Add is finished?`))void mutateExisting(candidate,'remove');
    };
  }

  if(quickAdd){
    window.mbExistingConnectionMutations=[];
    const startCopy=document.querySelector('#startCopy');
    if(startCopy)startCopy.textContent='Extend this Site without destructive setup. Existing Connections are shown separately; Edit/Remove changes stay in the disposable draft until Finish.';
    const finishCopy=document.querySelector('#finish > p.muted');
    if(finishCopy)finishCopy.textContent='New monitoring plus any explicitly staged Existing Connection edits/removals will be validated and atomically applied together. Unrelated existing authority remains protected.';

    const originalSupported=supportedCandidate;
    supportedCandidate=candidate=>originalSupported(candidate)||candidate?.kind==='unifi';

    const originalRenderSystems=renderSystems;
    renderSystems=function(summary,selected=new Set()){
      originalRenderSystems(summary,selected);
      decorateSystems(summary);
    };

    const originalRenderConnections=renderConnections;
    renderConnections=function(items){
      const all=Array.isArray(items)?items:[];
      originalRenderConnections(all);
      const visible=all.filter(supportedCandidate);
      const cards=[...document.querySelectorAll('#connectionList .connection')];
      const root=document.querySelector('#connectionList');
      if(!root)return;

      const newly=document.createElement('section');
      newly.id='newConnections';
      newly.className='subcard';
      newly.innerHTML='<h3>Newly detected</h3><div data-v22-new-list></div>';
      const newList=newly.querySelector('[data-v22-new-list]');

      const existing=document.createElement('details');
      existing.id='alreadyConfiguredConnections';
      existing.className='subcard';
      existing.innerHTML='<summary><strong>Already configured</strong></summary><div data-v22-existing-list></div>';
      const existingList=existing.querySelector('[data-v22-existing-list]');

      visible.forEach((candidate,index)=>{
        const card=cards[index];
        if(!card)return;
        decorateConnectionOwner(card,candidate);
        ensureProviderFields(card,candidate);
        enforceAutomaticTlsPolicy(card,candidate);
        if(candidate.already_configured===true){
          decorateExistingMutationControls(card,candidate);
          existingList.append(card);
        }else newList.append(card);
      });
      if(!newList.children.length)newList.innerHTML='<div class="muted">No new supported Connections were detected.</div>';
      if(!existingList.children.length)existingList.innerHTML='<div class="muted">No configured Connections apply to this Site.</div>';
      root.replaceChildren(newly,existing);
      placeConnectionCancel('Cancel Quick Add','/settings');
    };

    placeConnectionCancel('Cancel Quick Add','/settings');
    return;
  }

  // Destructive setup: every declared non-self System is the explicit probe
  // scope. This keeps automatically declared This MonitorBox out of scans unless
  // the operator explicitly adds it as a target later.
  const originalApi=api;
  api=async function(url,options={}){
    if(String(url).endsWith('/detect')&&String(options?.method||'').toUpperCase()==='POST'){
      const systemIds=(session?.systems||[])
        .filter(item=>item&&item.self!==true&&item.id)
        .map(item=>String(item.id));
      let body={};
      try{body=options.body?JSON.parse(options.body):{}}catch{body={}}
      options={...options,body:JSON.stringify({...body,system_ids:systemIds})};
    }
    return originalApi(url,options);
  };

  const originalSupported=supportedCandidate;
  supportedCandidate=candidate=>originalSupported(candidate)||['unifi','scrypted'].includes(candidate?.kind);
  const originalRenderConnections=renderConnections;
  renderConnections=function(items){
    const all=Array.isArray(items)?items:[];
    originalRenderConnections(all);
    const visible=all.filter(supportedCandidate);
    const cards=[...document.querySelectorAll('#connectionList .connection')];
    visible.forEach((candidate,index)=>{
      const card=cards[index];
      if(!card)return;
      decorateConnectionOwner(card,candidate);
      ensureProviderFields(card,candidate,{destructiveMode:true});
      enforceAutomaticTlsPolicy(card,candidate);
    });
    placeConnectionCancel('Cancel destructive setup','/settings/advanced');
  };
  placeConnectionCancel('Cancel destructive setup','/settings/advanced');
  placeDestructiveStageCancel('authenticatedDiscovery');
  placeDestructiveStageCancel('review');
})();
