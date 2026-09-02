'use strict';

(()=>{
  const RECOVERY_KEY='monitorbox.discovery.reconcile-recovery-until';
  const MANAGED_RECOVERY_MS=20000;
  const BLANK_STARTUP_RECOVERY_MS=10000;
  const RECOVERY_RETRY_MS=750;

  function visible(element){
    return !!element&&!element.classList.contains('hidden');
  }

  function managedRecoveryDeadline(){
    try{
      const raw=window.sessionStorage.getItem(RECOVERY_KEY);
      const value=Number(raw||0);
      if(Number.isFinite(value)&&value>Date.now())return value;
      window.sessionStorage.removeItem(RECOVERY_KEY);
    }catch(error){
      console.warn('discovery reconcile recovery state unavailable',error);
    }
    return 0;
  }

  function markManagedRecovery(){
    try{
      window.sessionStorage.setItem(RECOVERY_KEY,String(Date.now()+MANAGED_RECOVERY_MS));
    }catch(error){
      console.warn('could not mark discovery reconcile recovery window',error);
    }
    document.documentElement.dataset.monitorboxDiscoveryRecovery='managed';
  }

  function clearManagedRecovery(){
    try{window.sessionStorage.removeItem(RECOVERY_KEY)}catch{}
  }

  function bindManagedReconcileRecovery(){
    const apply=document.getElementById('apply');
    if(!apply||apply.dataset.recoveryBound==='true')return;
    apply.dataset.recoveryBound='true';
    apply.addEventListener('click',markManagedRecovery);
  }

  function exposeLoginAfterReconcile(){
    const login=document.getElementById('login');
    const app=document.getElementById('app');
    app?.classList.add('hidden');
    login?.classList.remove('hidden');
    const loginStatus=document.getElementById('loginStatus');
    if(loginStatus)loginStatus.textContent='MonitorBox reconciled its managed runtime. Log in again to continue.';
    clearManagedRecovery();
    document.documentElement.dataset.monitorboxDiscoveryRecovery='login-required';
  }

  function startAuthSurfaceRecovery(){
    const managedUntil=managedRecoveryDeadline();
    const startupUntil=Date.now()+BLANK_STARTUP_RECOVERY_MS;
    const managed=managedUntil>0;
    const deadline=managed?managedUntil:startupUntil;
    const login=document.getElementById('login');
    const app=document.getElementById('app');

    if(!managed&&(visible(login)||visible(app))){
      document.documentElement.dataset.monitorboxDiscoveryRecovery='settled';
      return;
    }
    document.documentElement.dataset.monitorboxDiscoveryRecovery=managed?'managed':'startup';

    async function attempt(){
      const stillManaged=managed&&Date.now()<managedUntil;
      if(!stillManaged&&!managed&&(visible(login)||visible(app))){
        document.documentElement.dataset.monitorboxDiscoveryRecovery='settled';
        return;
      }
      try{
        const response=await fetch('/api/v2/config/status',{
          headers:{Accept:'application/json'},
          cache:'no-store',
        });
        if(!response.ok)throw new Error(`config status HTTP ${response.status}`);
        const status=await response.json();
        if(status?.authenticated===false){
          exposeLoginAfterReconcile();
          return;
        }
        if(status?.authenticated===true&&!visible(app)&&typeof auth==='function'){
          try{await auth()}catch(error){console.warn('discovery auth recovery retry failed',error)}
        }
        if(!managed&&visible(app)){
          document.documentElement.dataset.monitorboxDiscoveryRecovery='settled';
          return;
        }
      }catch(error){
        console.warn('discovery auth surface recovery waiting for controller',error);
      }

      if(Date.now()<deadline){
        window.setTimeout(attempt,RECOVERY_RETRY_MS);
        return;
      }
      clearManagedRecovery();
      document.documentElement.dataset.monitorboxDiscoveryRecovery=(visible(login)||visible(app))?'settled':'failed';
      if(!visible(login)&&!visible(app))console.warn('discovery auth surface did not recover before the bounded retry window expired');
    }

    window.setTimeout(attempt,250);
  }

  function safeCandidateEndpoint(value){
    const text=String(value||'').trim();
    if(!text||text.length>2048)return'';
    try{
      const endpoint=new URL(text);
      if(!['http:','https:'].includes(endpoint.protocol))return'';
      if(!endpoint.hostname||endpoint.username||endpoint.password)return'';
      if(endpoint.search||endpoint.hash)return'';
      return endpoint.origin;
    }catch{return''}
  }

  function addV22Controls(){
    const scan=document.getElementById('scan');
    const cidr=document.getElementById('cidr');
    const hint=document.getElementById('subnetHint');
    if(!scan||!cidr||!hint)return;

    scan.textContent='Scan LAN';
    let refresh=document.getElementById('refreshConnections');
    if(!refresh){
      refresh=document.createElement('button');
      refresh.id='refreshConnections';
      refresh.type='button';
      refresh.className='button';
      refresh.textContent='Refresh connections';
      scan.insertAdjacentElement('afterend',refresh);
    }

    let deep=document.getElementById('deepTools');
    if(!deep){
      deep=document.createElement('details');
      deep.id='deepTools';
      deep.style.marginTop='14px';
      deep.style.borderTop='1px solid var(--line)';
      deep.style.paddingTop='12px';
      deep.innerHTML=`<summary style="cursor:pointer;color:var(--muted);font-weight:650">Deep Scan tools</summary>
        <p class="muted"><strong>Deep Scan is explicit and intrusive.</strong> It may take a while and may trigger IDS/IPS. It exhaustively checks TCP ports with rate limiting, performs only a small protocol-aware UDP set, and never guesses SNMP credentials.</p>
        <div class="row"><label class="field grow">Private host IPv4<input id="deepAddress" placeholder="192.168.1.10"></label>
        <button id="deepHost" class="button" type="button">Deep Scan this host</button><button id="deepAll" class="button" type="button">Deep Scan all in CIDR</button></div>
        <pre id="deepResult" class="muted" style="white-space:pre-wrap;overflow:auto;max-height:240px"></pre>`;
      hint.parentElement?.append(deep);
    }

    async function waitDiscoveryJob(jobId){
      for(let i=0;i<1800;i++){
        const job=await api(`/api/v2/config/discovery/jobs/${encodeURIComponent(jobId)}`);
        const pct=Math.round((job.progress||0)*100);
        note(`${String(job.kind||'discovery').replaceAll('_',' ')} · ${String(job.phase||job.status||'working').replaceAll('-',' ')} · ${pct}%`);
        if(job.status==='completed')return job.result;
        if(job.status==='failed')throw new Error(job.error||'discovery job failed');
        if(job.status==='canceled')throw new Error('discovery job canceled');
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      throw new Error('discovery job status timed out');
    }

    async function startDiscoveryJob(body){
      const job=await api('/api/v2/config/discovery/jobs',{
        method:'POST',
        body:JSON.stringify(body),
      });
      if(!job?.id)throw new Error('controller did not return a discovery job id');
      return waitDiscoveryJob(job.id);
    }

    function connectionSuggestionScope(suggestion,adapter){
      const explicit=String(suggestion?.scope||'').trim().toLowerCase();
      if(explicit==='site'||explicit==='object')return explicit;
      // Scrypted is a site-level authenticated integration Connection. HTTP(S)
      // and unknown future suggestions are object-scoped unless their evidence
      // explicitly declares otherwise.
      return adapter==='scrypted'?'site':'object';
    }

    function connectionSuggestions(item){
      const suggestions=[];
      const seen=new Set();
      for(const evidence of item?.evidence||[]){
        const raw=evidence?.metadata?.connection_suggestions;
        if(!Array.isArray(raw))continue;
        for(const suggestion of raw){
          const adapter=String(suggestion?.adapter||'').trim().toLowerCase();
          const preset=String(suggestion?.preset||adapter).trim().toLowerCase();
          if(!adapter||!preset||seen.has(adapter))continue;
          seen.add(adapter);
          suggestions.push({
            adapter,
            preset,
            scope:connectionSuggestionScope(suggestion,adapter),
            label:String(suggestion?.label||adapter),
            reason:String(suggestion?.reason||'Provider evidence suggests another Connection.'),
            candidate_endpoint:safeCandidateEndpoint(suggestion?.candidate_endpoint),
          });
        }
      }
      return suggestions;
    }

    function renderConnectionSuggestions(){
      for(const row of document.querySelectorAll('#results .candidate')){
        row.querySelectorAll('.connection-suggestion').forEach(element=>element.remove());
        const candidateId=row.querySelector('input[type=checkbox][data-id]')?.dataset.id;
        const item=(candidates||[]).find(candidate=>candidate.candidate_id===candidateId);
        if(!item)continue;
        const configuredObject=new Set((item.configured_adapters||[]).map(adapter=>String(adapter||'').trim().toLowerCase()).filter(Boolean));
        const configuredSite=new Set((item.configured_site_adapters||[]).map(adapter=>String(adapter||'').trim().toLowerCase()).filter(Boolean));
        const evidenceCell=row.querySelector('.wide');
        if(!evidenceCell)continue;
        for(const suggestion of connectionSuggestions(item)){
          const configured=suggestion.scope==='site'?configuredSite:configuredObject;
          if(configured.has(suggestion.adapter))continue;
          const box=document.createElement('div');
          box.className='connection-suggestion';
          box.style.marginTop='8px';
          box.style.padding='8px';
          box.style.border='1px solid var(--line)';
          box.style.borderRadius='9px';
          const title=document.createElement('strong');
          title.textContent=`Suggested Connection · ${suggestion.label}`;
          const reason=document.createElement('div');
          reason.className='muted';
          reason.textContent=suggestion.reason+' Nothing will be added until you configure, test and review it.';
          const link=document.createElement('a');
          link.className='button';
          link.style.display='inline-block';
          link.style.marginTop='7px';
          link.textContent=`Configure ${suggestion.label}`;
          const params=new URLSearchParams({flow:'connection',preset:suggestion.preset});
          if(suggestion.candidate_endpoint)params.set('endpoint',suggestion.candidate_endpoint);
          link.href=`/settings/quick-add?${params.toString()}`;
          box.append(title,reason,link);
          evidenceCell.append(box);
        }
      }
    }

    function acceptDiscoveryResult(result){
      discoveryId=result.discovery_id;
      candidates=Array.isArray(result.candidates)?result.candidates:[];
      renderProviders(result.providers);
      render();
      renderConnectionSuggestions();
      summarize();
      document.getElementById('resultsCard')?.classList.remove('hidden');
      document.getElementById('previewCard')?.classList.add('hidden');
      candidateId=null;
      if(typeof setupDraftPending!=='undefined')setupDraftPending=false;
      const apply=document.getElementById('apply');
      if(apply)apply.textContent='Apply monitoring changes';
      note('Discovery complete. Nothing has been changed.');
    }

    scan.onclick=async()=>{
      try{
        scan.disabled=true;
        note('Starting conservative LAN discovery…');
        const result=await startDiscoveryJob({kind:'lan',cidr:cidr.value.trim()});
        acceptDiscoveryResult(result);
      }catch(error){
        note(`Discovery failed: ${error.message}`);
      }finally{
        scan.disabled=false;
      }
    };

    refresh.onclick=async()=>{
      try{
        refresh.disabled=true;
        note('Refreshing configured provider inventories…');
        const result=await startDiscoveryJob({kind:'integrations'});
        acceptDiscoveryResult(result);
      }catch(error){
        note(`Connection refresh failed: ${error.message}`);
      }finally{
        refresh.disabled=false;
      }
    };

    const deepHost=document.getElementById('deepHost');
    const deepAll=document.getElementById('deepAll');
    const deepAddress=document.getElementById('deepAddress');
    const deepResult=document.getElementById('deepResult');
    if(deepHost&&deepAddress&&deepResult){
      deepHost.onclick=async()=>{
        try{
          const address=deepAddress.value.trim();
          if(!address)throw new Error('Enter a private host IPv4 address.');
          if(!confirm('Deep Scan may take a while and may trigger IDS/IPS. Run it for this host?'))return;
          deepHost.disabled=true;
          deepResult.textContent='Deep Scan running…';
          const result=await startDiscoveryJob({kind:'deep_host',address,acknowledge_intrusive:true});
          deepResult.textContent=JSON.stringify(result,null,2);
          note('Deep Scan complete. Results are evidence only.');
        }catch(error){
          note(`Deep Scan failed: ${error.message}`);
        }finally{
          deepHost.disabled=false;
        }
      };
    }
    if(deepAll&&deepResult){
      deepAll.onclick=async()=>{
        try{
          const network=cidr.value.trim();
          if(!network)throw new Error('Enter a private IPv4 CIDR first.');
          if(!confirm(`Deep Scan ALL hosts in ${network} may take a long time and may trigger IDS/IPS. Continue?`))return;
          deepAll.disabled=true;
          deepResult.textContent='Deep Scan all running…';
          const result=await startDiscoveryJob({kind:'deep_all',cidr:network,acknowledge_intrusive:true});
          deepResult.textContent=JSON.stringify(result,null,2);
          note('Deep Scan all complete. Results are evidence only.');
        }catch(error){
          note(`Deep Scan all failed: ${error.message}`);
        }finally{
          deepAll.disabled=false;
        }
      };
    }
  }

  function initializeV22Discovery(){
    bindManagedReconcileRecovery();
    startAuthSurfaceRecovery();
    addV22Controls();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initializeV22Discovery,{once:true});
  else initializeV22Discovery();
})();
