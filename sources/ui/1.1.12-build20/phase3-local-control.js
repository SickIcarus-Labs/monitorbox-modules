'use strict';

(() => {
  const LOCAL_URL_KEY='monitorbox.localAccess.url.v1';
  const LAST_STATE_KEY='monitorbox.lastCanonicalStateAt.v1';
  const LOCAL_REFRESH_MS=5*60*1000;
  let lastLocalRefresh=0;

  function storageGet(key){
    try{return window.localStorage?.getItem(key)||'';}catch(_){return'';}
  }
  function storageSet(key,value){
    try{window.localStorage?.setItem(key,value);}catch(_){}
  }
  function storageRemove(key){
    try{window.localStorage?.removeItem(key);}catch(_){}
  }
  function safeHttpUrl(value){
    if(typeof value!=='string'||!value.trim())return'';
    try{
      const parsed=new URL(value.trim(),location.href);
      if(!['http:','https:'].includes(parsed.protocol))return'';
      parsed.hash='';
      parsed.search='';
      parsed.pathname='/';
      return parsed.origin;
    }catch(_){return'';}
  }
  function staleAgeText(stamp,now=Date.now()){
    const value=Number(stamp);
    if(!Number.isFinite(value)||value<=0)return'no previously recorded state';
    const seconds=Math.max(0,Math.round((now-value)/1000));
    if(seconds<5)return'just now';
    if(seconds<60)return`${seconds}s ago`;
    if(seconds<3600)return`${Math.floor(seconds/60)}m ago`;
    return`${Math.floor(seconds/3600)}h ago`;
  }
  function cachedLocalUrl(){return safeHttpUrl(storageGet(LOCAL_URL_KEY));}
  function recordCanonicalState(){storageSet(LAST_STATE_KEY,String(Date.now()));}

  function ensureLocalMenu(url){
    const menu=document.getElementById('v22-menu');
    if(!menu)return;
    let link=document.getElementById('v22-local-access');
    if(!url){link?.remove();return;}
    if(!link){
      link=document.createElement('a');
      link.id='v22-local-access';
      link.rel='noopener';
      menu.appendChild(link);
    }
    link.href=url;
    link.textContent=new URL(url).origin===location.origin?'Local access · this address':'Local access';
    link.title=`WAN-independent MonitorBox address: ${url}`;
  }

  function recoveryBanner(url){
    let node=document.getElementById('mb-local-recovery');
    if(!node){
      node=document.createElement('section');
      node.id='mb-local-recovery';
      node.className='mb-local-recovery';
      node.hidden=true;
      const global=document.getElementById('global');
      global?.insertAdjacentElement('afterend',node);
    }
    if(!node)return;
    if(!url||new URL(url).origin===location.origin){
      node.hidden=true;
      node.replaceChildren();
      return;
    }
    node.replaceChildren();
    const copy=document.createElement('div');
    const strong=document.createElement('strong');
    strong.textContent='Local recovery address';
    const detail=document.createElement('span');
    detail.textContent=url;
    copy.append(strong,detail);
    const link=document.createElement('a');
    link.className='button secondary';
    link.href=url;
    link.rel='noopener';
    link.textContent='Open local MonitorBox';
    node.append(copy,link);
    node.hidden=false;
  }

  function clearRecoveryBanner(){
    const node=document.getElementById('mb-local-recovery');
    if(node)node.hidden=true;
  }

  function renderPathUnavailable(){
    const global=document.getElementById('global');
    global?.classList.remove('healthy','degraded','failed');
    global?.classList.add('unknown');
    const title=document.getElementById('global-title');
    const copy=document.getElementById('global-copy');
    const pill=document.getElementById('global-state');
    const last=storageGet(LAST_STATE_KEY);
    if(title)title.textContent='Connection path unavailable';
    if(copy){
      copy.textContent=last
        ?`This browser cannot currently reach MonitorBox at this address. Last canonical state was ${staleAgeText(last)}; controller health is not proven failed.`
        :'This browser cannot currently reach MonitorBox at this address. This transport error does not prove the controller or appliance has failed.';
    }
    if(pill){pill.className='state-pill unknown';pill.textContent='Path unavailable';}
    const sync=document.getElementById('sync-label');
    if(sync)sync.textContent='Browser path unavailable';
    recoveryBanner(cachedLocalUrl());
  }

  async function refreshLocalAccess({force=false}={}){
    const now=Date.now();
    if(!force&&now-lastLocalRefresh<LOCAL_REFRESH_MS)return cachedLocalUrl();
    lastLocalRefresh=now;
    try{
      const response=await window.fetch('/api/v2/config/local-access',{
        cache:'no-store',
        headers:{Accept:'application/json'},
      });
      if(!response.ok)return cachedLocalUrl();
      const descriptor=await response.json();
      const url=descriptor?.available===true?safeHttpUrl(descriptor.local_url):'';
      if(url)storageSet(LOCAL_URL_KEY,url);else storageRemove(LOCAL_URL_KEY);
      ensureLocalMenu(url);
      return url;
    }catch(_){
      const url=cachedLocalUrl();
      ensureLocalMenu(url);
      return url;
    }
  }

  function frozenCopyDialog(snapshot){
    let dialog=document.getElementById('debug-copy-fallback');
    if(!dialog){
      dialog=document.createElement('dialog');
      dialog.id='debug-copy-fallback';
      dialog.className='debug-copy-fallback';
      dialog.innerHTML='<form method="dialog"><header><strong>Frozen debug snapshot</strong><button class="icon-button" value="close" aria-label="Close">×</button></header><p>Clipboard access is unavailable on this browser origin. This snapshot will not refresh while you copy it.</p><textarea readonly spellcheck="false" aria-label="Frozen debug log snapshot"></textarea><div class="action-list"><button type="button" class="button secondary" data-copy-select>Select all</button><button class="button" value="close">Close</button></div></form>';
      document.body.appendChild(dialog);
      dialog.querySelector('[data-copy-select]')?.addEventListener('click',()=>{
        const field=dialog.querySelector('textarea');
        field?.focus();
        field?.select();
        field?.setSelectionRange?.(0,field.value.length);
      });
    }
    const field=dialog.querySelector('textarea');
    if(field)field.value=snapshot;
    if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','');
    field?.focus();
    field?.select();
    field?.setSelectionRange?.(0,field.value.length);
  }

  function installDebugCopyFallback(){
    const button=document.getElementById('debug-copy');
    const log=document.getElementById('debug-log');
    if(!button||!log||button.dataset.localCopyFallback==='true')return;
    button.dataset.localCopyFallback='true';
    button.addEventListener('click',event=>{
      event.preventDefault();
      event.stopImmediatePropagation();
      const snapshot=String(log.textContent||'');
      if(!snapshot.trim()){
        if(typeof toast==='function')toast('Debug log is empty');
        return;
      }
      const manual=()=>frozenCopyDialog(snapshot);
      if(window.isSecureContext&&navigator.clipboard?.writeText){
        navigator.clipboard.writeText(snapshot).then(()=>{
          if(typeof toast==='function')toast('Debug log copied');
        }).catch(manual);
      }else{
        manual();
      }
    },{capture:true});
  }

  function install(){
    ensureLocalMenu(cachedLocalUrl());
    installDebugCopyFallback();
    if(typeof app!=='undefined'&&app?.state)recordCanonicalState();
    void refreshLocalAccess({force:true});

    if(typeof renderOffline==='function')renderOffline=renderPathUnavailable;
    if(typeof loadState==='function'){
      const baseLoadState=loadState;
      loadState=async function(options={}){
        try{
          const result=await baseLoadState(options);
          recordCanonicalState();
          clearRecoveryBanner();
          void refreshLocalAccess();
          return result;
        }catch(error){
          renderPathUnavailable();
          throw error;
        }
      };
    }
  }

  const api={
    safeHttpUrl,
    staleAgeText,
    renderPathUnavailable,
    frozenCopyDialog,
    refreshLocalAccess,
  };
  window.MonitorBoxUiPhase3LocalControl=api;
  if(typeof document!=='undefined')install();
})();
