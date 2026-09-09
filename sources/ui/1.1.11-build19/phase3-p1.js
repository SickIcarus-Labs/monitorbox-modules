'use strict';

(()=>{
  function boundedCheckId(value){
    const text=String(value||'').trim();
    return text&&text.length<=240?text:'';
  }

  function sourceCheckId(component){
    return boundedCheckId(component?.metadata?.source_check_id);
  }

  function patchDerivedCheckActions(){
    if(typeof findObject!=='function'||typeof app==='undefined'||!app?.selected||!app?.state)return 0;
    const found=findObject(app.selected.siteId,app.selected.objectId);
    const components=Array.isArray(found?.object?.components)?found.object.components:[];
    let patched=0;

    for(const button of document.querySelectorAll('#drawer-body [data-run-check]')){
      const renderedId=boundedCheckId(button.dataset.runCheck);
      if(!renderedId)continue;
      const component=components.find(item=>boundedCheckId(item?.id)===renderedId);
      const sourceId=sourceCheckId(component);
      if(!sourceId||sourceId===renderedId)continue;

      // bindDrawer reads dataset.runCheck at click time. Repoint only derived
      // children with explicit provider provenance; direct check behavior is
      // untouched and no synthetic-id parsing is required.
      button.dataset.runCheck=sourceId;
      button.dataset.derivedCheck='true';
      button.title='Refresh owning provider check';
      button.setAttribute('aria-label',`Check ${String(component?.label||'provider item')} now`);
      patched++;
    }
    return patched;
  }

  function install(){
    if(typeof renderDrawer!=='function'){
      console.warn('Phase-3 derived-check repair could not bind drawer renderer');
      return;
    }
    const baseRenderDrawer=renderDrawer;
    renderDrawer=function phase3DerivedRecoveryDrawer(){
      const result=baseRenderDrawer();
      patchDerivedCheckActions();
      return result;
    };
    patchDerivedCheckActions();
  }

  globalThis.MonitorBoxUiPhase3P1={
    boundedCheckId,
    sourceCheckId,
    patchDerivedCheckActions,
  };

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  else install();
})();
