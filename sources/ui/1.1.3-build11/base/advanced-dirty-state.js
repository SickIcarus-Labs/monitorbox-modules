'use strict';

(()=>{
  const app=document.getElementById('app');
  const reloadButton=document.getElementById('reload');
  const validateButton=document.getElementById('validate');
  const previewSummary=document.getElementById('previewSummary');
  if(!app||!reloadButton||!validateButton)return;

  let allowNavigation=false;
  let pendingAction=null;
  let postApplyDestination=null;
  const nativeConfirm=window.confirm.bind(window);
  const systemKinds=new Set(['host','appliance','network_device']);

  function sameAuthority(){
    try{return JSON.stringify(working)===JSON.stringify(current)}catch{return true}
  }
  function dirty(){return !sameAuthority()}
  function entityNoun(obj){return systemKinds.has(String(obj?.kind||'').toLowerCase())?'System':'Object'}

  function ensureStyle(){
    if(document.getElementById('advancedDirtyStateStyle'))return;
    const style=document.createElement('style');
    style.id='advancedDirtyStateStyle';
    style.textContent=`
      #advancedDirtyState{display:inline-flex;align-items:center;gap:6px;border:1px solid #765f2d;border-radius:999px;padding:4px 8px;color:#f4d99a;background:#211d12;font-size:11px;font-weight:700}
      #advancedDirtyState.hidden{display:none!important}
      #advancedDirtyGuard .guard-copy{color:var(--muted);margin:8px 0 0}
      #advancedDirtyGuard .guard-actions{display:flex;gap:9px;justify-content:flex-end;flex-wrap:wrap;margin-top:18px}
      #advancedDirtyGuard .discard{border-color:#765f2d;color:#f4d99a}
    `;
    document.head.append(style);
  }

  function ensureIndicator(){
    let indicator=document.getElementById('advancedDirtyState');
    if(indicator)return indicator;
    indicator=document.createElement('span');
    indicator.id='advancedDirtyState';
    indicator.className='hidden';
    indicator.textContent='Unsaved changes · not applied';
    indicator.title='These edits exist only in this browser until Review & apply completes.';
    const revision=document.getElementById('revision');
    revision?.insertAdjacentElement('afterend',indicator);
    return indicator;
  }

  function ensureGuard(){
    let dialog=document.getElementById('advancedDirtyGuard');
    if(dialog)return dialog;
    dialog=document.createElement('dialog');
    dialog.id='advancedDirtyGuard';
    dialog.innerHTML=`<div class="modal"><div class="eyebrow">Unsaved Advanced changes</div><h2 style="margin-top:4px">These edits are not applied yet</h2><p class="guard-copy">The running MonitorBox still uses the current canonical configuration. Choose whether to keep editing, discard this browser-local candidate, or review it through the normal Validate → Apply transaction.</p><div class="guard-actions"><button type="button" class="button" data-guard="stay">Stay</button><button type="button" class="button discard" data-guard="discard">Discard changes</button><button type="button" class="button primary" data-guard="review">Review & apply</button></div></div>`;
    document.body.append(dialog);
    dialog.querySelector('[data-guard="stay"]').onclick=()=>{pendingAction=null;postApplyDestination=null;dialog.close()};
    dialog.querySelector('[data-guard="discard"]').onclick=()=>{
      const action=pendingAction;
      pendingAction=null;
      postApplyDestination=null;
      dialog.close();
      if(!action)return;
      if(action.kind==='reload'){
        load().then(()=>refresh()).catch(error=>toast(error.message));
        return;
      }
      if(action.kind==='navigate'){
        allowNavigation=true;
        location.href=action.href;
      }
    };
    dialog.querySelector('[data-guard="review"]').onclick=()=>{
      const action=pendingAction;
      pendingAction=null;
      dialog.close();
      postApplyDestination=action?.kind==='navigate'?action.href:null;
      validateButton.click();
    };
    dialog.addEventListener('cancel',event=>{
      event.preventDefault();
      pendingAction=null;
      postApplyDestination=null;
      dialog.close();
    });
    return dialog;
  }

  function refresh(){
    const isDirty=dirty();
    ensureIndicator().classList.toggle('hidden',!isDirty);
    document.body.dataset.advancedDirty=isDirty?'true':'false';
    return isDirty;
  }

  function guard(action){
    pendingAction=action;
    ensureGuard().showModal();
  }

  function sameOriginHref(anchor){
    const raw=anchor.getAttribute('href');
    if(!raw||raw.startsWith('#')||raw.startsWith('javascript:'))return null;
    try{
      const url=new URL(raw,location.href);
      return url.origin===location.origin?url.href:null;
    }catch{return null}
  }

  function interceptObjectDelete(event,button){
    const obj=typeof currentObject==='function'?currentObject():null;
    const noun=entityNoun(obj);
    const label=obj?.label||obj?.id||`this ${noun.toLowerCase()}`;
    const accepted=nativeConfirm(`Remove ${noun} “${label}” from this pending configuration?\n\nNothing changes on the running MonitorBox until you Review & apply. Its owned Connections and Abilities, plus health dependencies and presentation nesting that point to this ${noun}, will also be removed from the pending candidate.`);
    event.preventDefault();
    event.stopImmediatePropagation();
    if(!accepted)return;
    const original=button.onclick;
    if(typeof original!=='function')return;
    const priorConfirm=window.confirm;
    window.confirm=()=>true;
    try{original.call(button,event)}finally{window.confirm=priorConfirm}
    refresh();
  }

  ensureStyle();
  ensureIndicator();
  ensureGuard();

  document.addEventListener('click',event=>{
    const target=event.target instanceof Element?event.target:null;
    if(!target)return;

    const deleteButton=target.closest('#editor .button.danger');
    if(deleteButton&&(/^Delete (?:System|Object)$/i.test(deleteButton.textContent.trim())||deleteButton.dataset.advancedEntityNoun)){
      interceptObjectDelete(event,deleteButton);
      return;
    }

    if(target.closest('#reload')&&dirty()){
      event.preventDefault();
      event.stopImmediatePropagation();
      guard({kind:'reload'});
      return;
    }

    const credentialButton=target.closest('#showSecrets');
    if(credentialButton&&dirty()){
      event.preventDefault();
      event.stopImmediatePropagation();
      guard({kind:'navigate',href:new URL('/settings/appliance#credentials',location.href).href});
      return;
    }

    const anchor=target.closest('a[href]');
    if(!anchor||!dirty())return;
    const href=sameOriginHref(anchor);
    if(!href)return;
    event.preventDefault();
    event.stopImmediatePropagation();
    guard({kind:'navigate',href});
  },true);

  document.addEventListener('change',()=>setTimeout(refresh,0));
  document.addEventListener('click',()=>setTimeout(refresh,0));

  window.addEventListener('beforeunload',event=>{
    if(!dirty()||allowNavigation)return;
    event.preventDefault();
    event.returnValue='';
  });

  if(previewSummary){
    new MutationObserver(()=>{
      const text=previewSummary.textContent||'';
      if(!/Revision \d+ applied\.|Added to Setup Draft\./.test(text))return;
      current=deep(working);
      allowNavigation=true;
      refresh();
      if(postApplyDestination){
        const href=postApplyDestination;
        postApplyDestination=null;
        setTimeout(()=>{location.href=href},50);
      }
    }).observe(previewSummary,{childList:true,subtree:true,characterData:true});
  }

  const editor=document.getElementById('editor');
  if(editor)new MutationObserver(()=>setTimeout(refresh,0)).observe(editor,{childList:true,subtree:true});
  refresh();
})();
