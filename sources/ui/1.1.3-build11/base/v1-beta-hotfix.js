'use strict';

// Narrow compatibility layer: preserve the exact production-v1 external-link
// grammar, keep camera diagnostics stable across drawer renders, and report the
// centrally injected runtime identity instead of carrying another build constant.
function hotfixBuildId(){
  return document.body?.dataset.monitorboxBuild||'MonitorBox development build';
}

function hotfixServiceGlyph(service){
  const icon=(typeof nativeServiceIcons!=='undefined'&&nativeServiceIcons.has(service.icon))?service.icon:null;
  const letters=String(service.label||'').split(/\s+/).filter(Boolean).map(word=>word[0]).join('').slice(0,2).toUpperCase()||'S';
  const body=icon?`<img src="/static/icons/${esc(icon)}.svg" alt="">`:`<span>${esc(letters)}</span>`;
  return`<span class="service-icon" aria-hidden="true">${body}</span>`;
}

// Production v1 exposed host presentation URLs as a dedicated Management
// section (Arrrrr2 -> Cockpit, Goliath -> its web admin), while service
// presentation URLs were normal labeled external actions with the service
// glyph. Healthy hosts show passive Awake rather than an actionable Wake.
renderActions=function(site,object){
  const custom=object.actions||[];
  const awake=object.kind==='host'&&object.state==='healthy';
  const rendered=custom.map(action=>{
    if(action.kind==='wol'&&awake)return'<span class="awake-state">● Awake</span>';
    return`<button class="button secondary" data-action-id="${esc(action.id)}" type="button">${esc(action.label)}</button>`;
  }).join('');
  const management=(object.kind==='host'&&object.presentation_url)
    ?`<section class="detail-section"><h3>Management</h3><a class="external-action" href="${esc(object.presentation_url)}" target="_blank" rel="noopener">Open ${esc(object.label)} ↗</a></section>`
    :'';
  const external=(object.kind==='service'&&object.presentation_url)
    ?`<a class="external-action" href="${esc(object.presentation_url)}" target="_blank" rel="noopener">${hotfixServiceGlyph(object)}<span>Open service</span></a>`
    :'';
  return`${management}<section class="detail-section"><h3>Actions</h3><div class="action-list"><button class="button" data-run-object type="button">Check object now</button>${rendered}${external}</div></section>`;
};

// The global debug console loaded after this compatibility layer supersedes the
// camera-only debug panel. Keep these delegated handlers intact as a harmless
// compatibility fallback until global-debug.js takes ownership at runtime.
betaBindCameraDebugControls=function(){betaRefreshCameraDebugPanel();};

const hotfixDrawerBody=$('#drawer-body');
if(hotfixDrawerBody&&!hotfixDrawerBody.dataset.cameraDebugDelegated){
  hotfixDrawerBody.dataset.cameraDebugDelegated='1';
  hotfixDrawerBody.addEventListener('click',event=>{
    const target=event.target instanceof Element?event.target:null;
    const toggle=target?.closest('[data-camera-debug-toggle]');
    const copy=target?.closest('[data-camera-debug-copy]');
    const clear=target?.closest('[data-camera-debug-clear]');
    if(!toggle&&!copy&&!clear)return;
    event.preventDefault();
    event.stopPropagation();
    if(toggle){
      app.cameraDebugOpen=!app.cameraDebugOpen;
      betaRefreshCameraDebugPanel();
      if(app.cameraDebugOpen){
        requestAnimationFrame(()=>$('#camera-debug-panel')?.scrollIntoView({block:'nearest'}));
      }
      return;
    }
    if(copy){void betaCopyCameraDebug();return;}
    app.cameraDebugLines=[];
    betaRefreshCameraDebugPanel();
  },true);
}

// v1-beta-polish still carries a historical beta checkpoint internally. Rewrite
// the just-created session header after it runs so copied diagnostics always
// identify the actual image runtime metadata injected by the server.
const hotfixBaseStartCameraLive=startCameraLive;
startCameraLive=function(siteId,objectId){
  hotfixBaseStartCameraLive(siteId,objectId);
  const index=app.cameraDebugLines.findIndex(line=>line.includes('[browser] live session requested'));
  if(index>=0)app.cameraDebugLines[index]=app.cameraDebugLines[index].replace(/build=[^ ]+/,`build=${hotfixBuildId()}`);
  betaRefreshCameraDebugPanel();
};

// Keep every human-visible identity synchronized after older compatibility
// layers run. No frontend file owns a release/build constant anymore.
const hotfixBaseRender=render;
render=function(){
  hotfixBaseRender();
  const identity=hotfixBuildId();
  const build=$('#build-id');
  if(build)build.textContent=identity;
  document.title=`${app.state?.title||'MonitorBox'} · ${identity}`;
  const footer=$('#footer-state');
  if(footer)footer.textContent=footer.textContent.replace(/v2\.0b\d+$/,identity);
};

// A newly loaded dashboard can legitimately receive the controller's startup-
// neutral Unknown snapshot before the new agent boot has produced current
// evidence. Normal steady-state polling is intentionally relaxed, but startup
// convergence should not require an operator page reload. Poll quickly for a
// bounded window while canonical state is still incomplete, then fall back to
// the ordinary dashboard cadence.
let hotfixStartupRefreshAttempts=0;
let hotfixStartupRefreshRunning=false;
function hotfixStartupStateIncomplete(){
  if(!app.state)return true;
  if(app.state.overall==='unknown')return true;
  return(app.state.sites||[]).some(site=>(site.objects||[]).some(object=>object.state==='unknown'));
}
async function hotfixConvergeStartupState(){
  if(document.hidden||hotfixStartupRefreshAttempts>=60||!hotfixStartupStateIncomplete())return;
  if(hotfixStartupRefreshRunning){setTimeout(hotfixConvergeStartupState,1000);return;}
  hotfixStartupRefreshRunning=true;
  hotfixStartupRefreshAttempts++;
  try{await loadState({quiet:true});}catch(_){}
  finally{
    hotfixStartupRefreshRunning=false;
    if(hotfixStartupStateIncomplete()&&hotfixStartupRefreshAttempts<60){
      setTimeout(hotfixConvergeStartupState,1000);
    }
  }
}
setTimeout(hotfixConvergeStartupState,750);
