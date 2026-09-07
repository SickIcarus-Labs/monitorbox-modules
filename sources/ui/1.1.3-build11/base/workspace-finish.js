'use strict';

(()=>{
  // Persistent live-settings escape contract. The Workspace shell already makes
  // both top-bar identities links to `/`; keep the explicit text exit equally
  // unambiguous so it cannot be mistaken for Dashboard / Graphs configuration.
  for(const id of ['backToMonitoring','menuMonitoring']){
    const exit=document.getElementById(id);
    if(exit){
      exit.textContent='Back to Main Dashboard';
      exit.setAttribute('aria-label','Back to Main Dashboard');
    }
  }

  const apply=document.getElementById('applyFinish');
  const summary=document.getElementById('reviewSummary');
  if(!apply||!summary)return;

  const sleep=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));

  async function waitForManagedRestart(){
    const deadline=Date.now()+75000;
    let sawUnavailable=false;
    let last='controller never became unavailable';
    while(Date.now()<deadline){
      try{
        const health=await fetch('/healthz',{cache:'no-store'});
        if(!health.ok){
          sawUnavailable=true;
          last=`health HTTP ${health.status}`;
        }else if(sawUnavailable){
          const status=await fetch('/api/v2/config/status',{headers:{Accept:'application/json'},cache:'no-store'});
          if(status.ok){
            const state=await status.json();
            if(state.setup_complete===true&&state.setup_required===false)return;
            last='controller returned before setup_complete became authoritative';
          }else{
            last=`status HTTP ${status.status}`;
          }
        }else{
          last='waiting for managed controller restart to begin';
        }
      }catch(error){
        sawUnavailable=true;
        last=error?.message||String(error);
      }
      await sleep(200);
    }
    throw new Error(`controller did not become ready after Finish Setup: ${last}`);
  }

  apply.onclick=async()=>{
    try{
      if(!candidateId)return;
      apply.disabled=true;
      apply.textContent='Finishing…';
      await api(`/api/v2/config/candidates/${encodeURIComponent(candidateId)}/apply`,{method:'POST'});
      summary.textContent='Setup applied. Waiting for MonitorBox to restart and become healthy…';
      await waitForManagedRestart();
      summary.textContent='Setup complete. MonitorBox is ready.';
      location.href='/';
    }catch(error){
      summary.textContent=`Finish failed: ${error.message}`;
      apply.disabled=false;
      apply.textContent='Finish setup';
    }
  };
})();
