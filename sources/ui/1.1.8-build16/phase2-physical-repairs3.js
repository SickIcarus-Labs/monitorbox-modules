'use strict';

// UI 1.1.8 build 16 — third Broad Leaf physical-acceptance repair pass.
//
// #164: build 15 restored untouched provider authority from a listener attached
// to the Validate button itself. The frozen Advanced page registers its native
// onclick before managed assets load, so target-phase listener ordering can let
// the native handler serialize `working` before the repair runs. Build 16 moves
// that same provider-scoped restoration to a document capture listener. Capture
// runs before the event reaches the Validate target, guaranteeing that unrelated
// render-time/provider presentation drift is removed before the native candidate
// body is serialized. Explicitly edited providers remain untouched.
//
// No Core API or canonical semantics change. #206 URL reconciliation remains
// owned by build 15 and is inherited unchanged.

(()=>{
  const prior=globalThis.MonitorBoxUiPhase2Physical2||{};

  function restoreBeforeNativeValidate(currentDocument,workingDocument,touchedKeys){
    if(typeof prior.restoreUntouchedProviderBaselines!=='function')return 0;
    return prior.restoreUntouchedProviderBaselines(
      currentDocument,
      workingDocument,
      touchedKeys,
    );
  }

  globalThis.MonitorBoxUiPhase2Physical3=Object.freeze({
    restoreBeforeNativeValidate,
  });

  if(typeof document==='undefined')return;

  const touchedProviders=new Set();

  // Provider boxes receive this stable key from build 15's renderProvider wrapper.
  // Capture operator intent before the field/checkbox's own change handler mutates
  // the working canonical model.
  document.addEventListener('change',event=>{
    const target=event.target instanceof Element?event.target:null;
    const box=target?.closest?.('.provider[data-phase2-provider-key]');
    const key=box?.dataset?.phase2ProviderKey;
    if(key)touchedProviders.add(key);
  },true);

  // IMPORTANT: this listener belongs on an ancestor, not on #validate. The
  // frozen page's native onclick was registered before managed assets. Document
  // capture is therefore the deterministic pre-serialization seam.
  document.addEventListener('click',event=>{
    const target=event.target instanceof Element?event.target:null;
    if(!target?.closest?.('#validate'))return;
    if(typeof current==='undefined'||typeof working==='undefined')return;
    restoreBeforeNativeValidate(current,working,touchedProviders);
  },true);

  if(typeof load==='function'){
    const baseLoad=load;
    load=async function(...args){
      touchedProviders.clear();
      return await baseLoad(...args);
    };
  }
})();
