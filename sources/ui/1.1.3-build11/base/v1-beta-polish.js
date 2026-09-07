'use strict';

// Final beta parity pass recovered from the production-v1 interaction contract.
// The v2 controller remains authoritative; this layer restores the proven v1
// operator grammar while keeping the approved v2 graph and fresh-check fixes.
const BETA_BUILD_ID='v2.0b26';

// Keep the human-visible beta build synchronized with the package build even
// while the older parity layer still carries its previous checkpoint constant.
const betaBaseRender=render;
render=function(){
  betaBaseRender();
  const build=$('#build-id');
  if(build)build.textContent=BETA_BUILD_ID;
  document.title=`${app.state?.title||'MonitorBox'} · ${BETA_BUILD_ID}`;
  const footer=$('#footer-state');
  if(footer)footer.textContent=footer.textContent.replace(/v2\.0b\d+$/,BETA_BUILD_ID);
  betaSyncDrawerBack();
};

// Production v1 never offered Wake while a host was currently healthy. It
// rendered a passive Awake indicator instead. The external presentation action
// is icon-only: service objects use their own outbound service icon, while
// non-service presentation URLs use a compact outbound-arrow control.
renderActions=function(site,object){
  const custom=object.actions||[];
  const awake=object.kind==='host'&&object.state==='healthy';
  const rendered=custom.map(action=>{
    if(action.kind==='wol'&&awake)return'<span class="awake-state">● Awake</span>';
    return`<button class="button secondary" data-action-id="${esc(action.id)}" type="button">${esc(action.label)}</button>`;
  }).join('');
  let external='';
  if(object.presentation_url){
    if(object.kind==='service'&&typeof serviceIcon==='function')external=serviceIcon(object);
    else external=`<a class="button secondary open-service-icon" href="${esc(object.presentation_url)}" target="_blank" rel="noopener" aria-label="Open service" title="Open service"><span aria-hidden="true">↗</span></a>`;
  }
  return`<section class="detail-section"><h3>Actions</h3><div class="action-list"><button class="button" data-run-object type="button">Check object now</button>${rendered}${external}</div></section>`;
};

// Camera debug state is intentionally browser-local and bounded. It contains
// signaling stage/state only; SDP, ICE candidate addresses, credentials, and
// complete protocol payloads are never copied into the transcript.
app.cameraDebugOpen=app.cameraDebugOpen||false;
app.cameraDebugLines=app.cameraDebugLines||[];
function betaDebugValue(value){
  if(value===null)return'null';
  if(value===undefined)return'';
  let text;
  if(typeof value==='object'){
    try{text=JSON.stringify(value);}catch(_){text=String(value);}
  }else text=String(value);
  return text.replace(/\s+/g,' ').slice(0,180);
}
function betaCameraDebug(source,stage,fields={}){
  const details=Object.entries(fields).filter(([,value])=>value!==undefined).map(([key,value])=>`${key}=${betaDebugValue(value)}`).join(' ');
  app.cameraDebugLines.push(`${new Date().toISOString()} [${source}] ${stage}${details?` · ${details}`:''}`);
  if(app.cameraDebugLines.length>240)app.cameraDebugLines.splice(0,app.cameraDebugLines.length-240);
  betaRefreshCameraDebugPanel();
}
function betaCameraDebugText(){return app.cameraDebugLines.join('\n');}
function betaRefreshCameraDebugPanel(){
  const panel=$('#camera-debug-panel'),area=$('#camera-debug-log');
  if(panel)panel.hidden=!app.cameraDebugOpen;
  if(area){area.value=betaCameraDebugText();if(app.cameraDebugOpen)area.scrollTop=area.scrollHeight;}
  document.querySelectorAll('[data-camera-debug-toggle]').forEach(node=>node.setAttribute('aria-expanded',app.cameraDebugOpen?'true':'false'));
}
function betaCameraDebugPanel(){
  return`<section id="camera-debug-panel" class="detail-section camera-debug-section" ${app.cameraDebugOpen?'':'hidden'}><h3>Camera debug log</h3><p class="component-meta">Bounded browser + relay signaling trace. SDP, ICE addresses, and credentials are omitted.</p><textarea id="camera-debug-log" class="camera-debug-log" readonly spellcheck="false" aria-label="Camera debug log">${esc(betaCameraDebugText())}</textarea><div class="action-list camera-debug-actions"><button class="button secondary" data-camera-debug-copy type="button">Copy log</button><button class="button secondary" data-camera-debug-clear type="button">Clear</button></div></section>`;
}
async function betaCopyCameraDebug(){
  const text=betaCameraDebugText(),area=$('#camera-debug-log');
  if(!text){toast('Camera debug log is empty');return;}
  try{
    await navigator.clipboard.writeText(text);
    toast('Camera debug log copied');
  }catch(_){
    if(area){area.focus();area.select();area.setSelectionRange(0,area.value.length);}
    toast('Debug log selected — copy it');
  }
}
function betaBindCameraDebugControls(){
  document.querySelectorAll('[data-camera-debug-toggle]').forEach(node=>node.addEventListener('click',()=>{
    app.cameraDebugOpen=!app.cameraDebugOpen;
    betaRefreshCameraDebugPanel();
  }));
  document.querySelector('[data-camera-debug-copy]')?.addEventListener('click',()=>betaCopyCameraDebug());
  document.querySelector('[data-camera-debug-clear]')?.addEventListener('click',()=>{
    app.cameraDebugLines=[];
    betaRefreshCameraDebugPanel();
  });
  betaRefreshCameraDebugPanel();
}

// v1 deliberately did not rebuild an open camera drawer during background
// status polling. Replacing the <video> node detaches the active WebRTC stream.
const betaBaseLoadState=loadState;
loadState=async function(options={}){
  const selected=app.selected;
  let preserveCamera=false;
  if(selected&&app.state){
    const found=findObject(selected.siteId,selected.objectId);
    preserveCamera=found.object?.kind==='camera';
  }
  if(preserveCamera)app.selected=null;
  try{return await betaBaseLoadState(options);}
  finally{if(preserveCamera)app.selected=selected;}
};

// Restore v1's bounded live-view setup timer and explicit terminal state while
// preserving the first useful failure. The browser watchdog is deliberately
// longer than the bridge's 30-second signaling timeout so the bridge gets the
// first chance to return its more specific failure reason.
const betaBaseSetCameraStatus=setCameraStatus;
setCameraStatus=function(message){
  const live=app.cameraLive;
  if(live){
    const previous=live.message;
    if(message==='Live'){
      live.status='live';
      clearTimeout(live.timer);
    }else if(/failed|failure|error|exception|lost|ended|timed out|unavailable|denied|rejected/i.test(String(message))){
      live.status='failed';
    }else{
      live.status='loading';
    }
    if(previous!==message)betaCameraDebug('browser','status',{message,status:live.status});
  }
  betaBaseSetCameraStatus(message);
  const node=$('#camera-live-status');
  if(node&&live)node.className=`camera-status ${live.status||'loading'}`;
};

// Surface WebRTC state transitions in the copyable transcript without logging
// SDP or candidate addresses. Successful negotiation still uses production-v1
// ICE-connected semantics for the visible Live transition.
const betaBaseEnsureCameraPeer=ensureCameraPeer;
ensureCameraPeer=async function(live,setup){
  const existed=!!live.pc;
  const pc=await betaBaseEnsureCameraPeer(live,setup);
  if(!pc.__monitorboxBetaDiagnostics){
    pc.__monitorboxBetaDiagnostics=true;
    betaCameraDebug('webrtc',existed?'peer reused':'RTCPeerConnection created',{
      audio:!!setup.audio,
      video:!!setup.video,
      ice_servers:Array.isArray(setup.configuration?.iceServers)?setup.configuration.iceServers.length:0,
    });
    pc.addEventListener('connectionstatechange',()=>{
      betaCameraDebug('webrtc','connection state',{state:pc.connectionState});
      if(pc.connectionState==='failed')setCameraStatus('WebRTC connection failed');
    });
    pc.addEventListener('iceconnectionstatechange',()=>betaCameraDebug('webrtc','ICE connection state',{state:pc.iceConnectionState}));
    pc.addEventListener('icegatheringstatechange',()=>betaCameraDebug('webrtc','ICE gathering state',{state:pc.iceGatheringState}));
    pc.addEventListener('signalingstatechange',()=>betaCameraDebug('webrtc','signaling state',{state:pc.signalingState}));
    pc.addEventListener('track',event=>betaCameraDebug('webrtc','remote track received',{kind:event.track?.kind||'unknown'}));
    pc.addEventListener('icecandidate',event=>betaCameraDebug('webrtc',event.candidate?'local ICE candidate emitted':'ICE gathering complete'));
    pc.addEventListener('icecandidateerror',event=>{
      const detail=event?.errorText?`: ${event.errorText}`:'';
      betaCameraDebug('webrtc','ICE candidate error',{code:event?.errorCode,text:event?.errorText});
      setCameraStatus(`ICE candidate error${detail}`);
    });
  }
  return pc;
};

const betaBaseHandleCameraCall=handleCameraCall;
handleCameraCall=async function(live,message){
  const started=performance.now();
  betaCameraDebug('signaling','browser call received',{
    method:message.method,
    call_id:message.callId,
    trickle:!!message.trickle,
  });
  const result=await betaBaseHandleCameraCall(live,message);
  betaCameraDebug('signaling','browser call returned',{
    method:message.method,
    call_id:message.callId,
    elapsed_ms:Math.round(performance.now()-started),
    connection:live.pc?.connectionState,
    ice:live.pc?.iceConnectionState,
    signaling:live.pc?.signalingState,
  });
  return result;
};

const betaBaseStartCameraLive=startCameraLive;
startCameraLive=function(siteId,objectId){
  app.cameraDebugLines=[];
  betaCameraDebug('browser','live session requested',{build:BETA_BUILD_ID,site:siteId,object:objectId,protocol:location.protocol});
  betaBaseStartCameraLive(siteId,objectId);
  const live=app.cameraLive;
  if(!live)return;
  live.status='loading';
  clearTimeout(live.timer);
  live.timer=setTimeout(()=>{
    if(app.cameraLive===live&&live.status!=='live'){
      betaCameraDebug('browser','setup watchdog expired',{
        websocket:live.socket?.readyState,
        connection:live.pc?.connectionState,
        ice:live.pc?.iceConnectionState,
        gathering:live.pc?.iceGatheringState,
        signaling:live.pc?.signalingState,
      });
      setCameraStatus('Playback setup timed out');
      try{live.socket?.close();}catch(_){}
    }
  },40000);
  if(live.socket){
    const socket=live.socket;
    socket.addEventListener('open',()=>betaCameraDebug('websocket','controller websocket open'));
    socket.addEventListener('message',event=>{
      let message;
      try{message=JSON.parse(event.data);}catch(_){betaCameraDebug('websocket','non-JSON message received');return;}
      if(message.type==='debug'){
        const {type,source,stage,...fields}=message;
        betaCameraDebug(source||'relay',stage||'debug',fields);
      }else if(message.type==='call'){
        betaCameraDebug('websocket','signaling call received',{method:message.method,call_id:message.callId,trickle:!!message.trickle});
      }else if(message.type==='ready'){
        betaCameraDebug('websocket','bridge reported signaling ready');
      }else if(message.type==='error'){
        betaCameraDebug('websocket','bridge error',{error:message.error});
      }else{
        betaCameraDebug('websocket','message received',{type:message.type||'unknown'});
      }
    });
    socket.addEventListener('error',()=>betaCameraDebug('websocket','controller websocket error'));
    socket.addEventListener('close',event=>betaCameraDebug('websocket','controller websocket closed',{code:event.code,reason:event.reason||'',clean:event.wasClean}));
    const previousClose=socket.onclose;
    socket.onclose=event=>{
      clearTimeout(live.timer);
      if(app.cameraLive!==live)return;
      // A concrete bridge/ICE failure is more useful than the close event that
      // necessarily follows it. Do not erase it.
      if(live.status==='failed')return;
      previousClose?.call(socket,event);
      if(event?.reason&&app.cameraLive===live&&live.message==='Playback ended'){
        setCameraStatus(`Playback ended: ${event.reason}`);
      }
    };
  }
  betaRefreshCameraDebugPanel();
};
const betaBaseStopCameraLive=stopCameraLive;
stopCameraLive=function(rerender=true){
  const live=app.cameraLive;
  if(live){
    clearTimeout(live.timer);
    betaCameraDebug('browser','live session stopping',{rerender});
  }
  return betaBaseStopCameraLive(rerender);
};

// The v1 camera detail made the snapshot itself the live-view control. Keep the
// separate snapshot refresh action, but remove the redundant "Open live view"
// button and make the media the primary interaction target again. The debug
// transcript is always collected but only shown when the operator toggles it.
renderCamera=function(site,object){
  const debug=betaCameraDebugPanel();
  if(app.cameraLive?.siteId===site.id&&app.cameraLive?.objectId===object.id){
    return`<section class="detail-section camera-media-section"><h3>Live camera</h3><div class="camera-preview"><video id="camera-live-video" autoplay muted playsinline controls></video><span id="camera-live-status" class="camera-status ${esc(app.cameraLive.status||'loading')}">${esc(app.cameraLive.message)}</span></div><div class="action-list camera-media-actions"><button class="button secondary" data-live-stop type="button">Close live view</button><button class="button secondary" data-camera-debug-toggle type="button" aria-expanded="${app.cameraDebugOpen?'true':'false'}">Debug log</button></div><p class="component-meta camera-media-note">WebRTC media travels directly between this browser and Scrypted. MonitorBox brokers signaling only.</p></section>${debug}`;
  }
  const snapshot=`/api/v2/cameras/${encodeURIComponent(site.id)}/${encodeURIComponent(object.id)}/snapshot?t=${Date.now()}`;
  return`<section class="detail-section camera-media-section"><h3>On-demand snapshot</h3><button class="camera-preview camera-snapshot-trigger" data-live-start type="button" aria-label="Open live view for ${esc(object.label)}"><img src="${snapshot}" alt="Latest ${esc(object.label)} snapshot"><span class="camera-status">Tap for live view</span></button><div class="action-list camera-media-actions"><button class="button secondary" data-refresh-snapshot type="button">Refresh snapshot</button><button class="button secondary" data-camera-debug-toggle type="button" aria-expanded="${app.cameraDebugOpen?'true':'false'}">Debug log</button></div><p class="component-meta camera-media-note">Tap the snapshot to start bounded WebRTC playback.</p></section>${debug}`;
};

const betaBaseBindDrawer=bindDrawer;
bindDrawer=function(site,object){
  betaBaseBindDrawer(site,object);
  if(object.kind==='camera')betaBindCameraDebugControls();
};

// v1 used one navigation stack for every nested drawer. Recreate that contract
// generically so Cameras → Camera, Power → UPS, Services → Service, Network →
// device, and Overall Health → condition all share the same Back behavior.
app.navStack=app.navStack||[];
app.navView=app.navView||null;
let betaNavigatingBack=false;

function betaObjectView(siteId,objectId){return{kind:'object',siteId,objectId};}
function betaViewKey(view){return view?.kind==='object'?`${view.siteId}/${view.objectId}`:view?.kind||'';}
function betaViewLabel(view){
  if(!view)return'Back';
  if(view.kind==='global')return'MonitorBox';
  const found=findObject(view.siteId,view.objectId);
  return found.object?.label||'Back';
}
function betaPushCurrent(next){
  if(betaNavigatingBack)return;
  if(!app.navView){app.navStack=[];return;}
  if(betaViewKey(app.navView)!==betaViewKey(next))app.navStack.push(app.navView);
}
function betaSyncDrawerBack(){
  const back=$('#drawer-back');
  if(!back)return;
  const parent=app.navStack[app.navStack.length-1];
  back.hidden=!parent;
  back.textContent=parent?`← ${betaViewLabel(parent)}`:'← Back';
}

const betaBaseOpenDrawer=openDrawer;
openDrawer=function(siteId,objectId){
  const next=betaObjectView(siteId,objectId);
  betaPushCurrent(next);
  betaBaseOpenDrawer(siteId,objectId);
  app.navView=next;
  betaSyncDrawerBack();
};

const betaBaseOpenParityGlobal=openParityGlobal;
openParityGlobal=function(){
  const next={kind:'global'};
  betaPushCurrent(next);
  betaBaseOpenParityGlobal();
  app.navView=next;
  betaAddGlobalDiagnostics();
  betaSyncDrawerBack();
};

const betaBaseCloseDrawer=closeDrawer;
closeDrawer=function(){
  app.navStack=[];
  app.navView=null;
  betaNavigatingBack=false;
  return betaBaseCloseDrawer();
};

function betaGoBack(){
  const parent=app.navStack.pop();
  if(!parent)return;
  betaNavigatingBack=true;
  try{
    if(parent.kind==='global'){
      betaBaseOpenParityGlobal();
      app.navView={kind:'global'};
      betaAddGlobalDiagnostics();
    }else{
      betaBaseOpenDrawer(parent.siteId,parent.objectId);
      app.navView=parent;
    }
  }finally{
    betaNavigatingBack=false;
    betaSyncDrawerBack();
  }
}

// Disable the old service-only body Back row. The generic sticky header stack
// above is now the sole nested-navigation mechanism, matching production v1.
prependServiceBack=function(){};

// Curate camera identity exactly as v1 did. Provider is structured metadata,
// not a printable scalar; the raw native ID is useful evidence but not primary
// operator information.
parityCameraIdentity=function(object){
  if(object.kind!=='camera')return'';
  const component=(object.components||[]).find(item=>item.adapter==='scrypted'&&item.metadata)||
    (object.components||[]).find(item=>item.metadata);
  const metadata=component?.metadata||{};
  const provider=metadata.provider;
  const providerName=typeof provider==='string'?provider:provider?.name;
  const boxes=[];
  if(metadata.camera_id)boxes.push(parityMetricBox('Scrypted device ID',metadata.camera_id));
  if(providerName)boxes.push(parityMetricBox('provider',providerName));
  if(metadata.camera_status)boxes.push(parityMetricBox('Scrypted state',metadata.camera_status));
  if(metadata.selected_profile_id)boxes.push(parityMetricBox('selected profile',metadata.selected_profile_id));
  return boxes.length?`<section class="detail-section camera-identity-section"><h3>Camera identity</h3><div class="metrics">${boxes.join('')}</div></section>`:'';
};

// Turnberry was correctly represented as a Broadleaf Network child in v1. In
// distributed v2 it is intentionally becoming its own site/agent extension, so
// remote_site objects no longer belong in Broadleaf's Network card or drawer.
parityNetworkChildren=function(site){
  const children=parityObjects(site).filter(object=>object.kind==='network_device');
  const selected=[];
  for(const child of children){
    const evidence=(child.components||[]).find(component=>component.adapter==='unifi-component');
    const metadata=evidence?.metadata||{};
    if(metadata.front_page===true||(
      metadata.snmp_applicability==='not_applicable'&&child.state!=='healthy'
    ))selected.push(child);
  }
  return selected;
};
parityNetworkAggregate=function(site,object){
  if(object.id!=='network')return'';
  const children=parityNetworkChildren(site)
    .sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
  const rows=children.map(child=>`<button class="component-row parity-nav-row" data-parity-site="${esc(site.id)}" data-parity-object="${esc(child.id)}" type="button"><span><strong>${esc(child.label)}</strong><small>${esc(child.summary||'Status unavailable')}</small></span>${pill(child.state)}</button>`).join('');
  return`<section class="detail-section"><h3>Infrastructure and required paths</h3><div class="component-list">${rows||'<div class="chart-empty">No local Network children are configured.</div>'}</div></section>`;
};

// Keep the Power card dense and operational: source/status + load on the left,
// battery charge + remaining runtime on the right for every UPS.
parityPowerRows=function(site){
  return parityUps(site).map(ups=>{
    const charge=parityMetric(ups,'battery.charge');
    const runtime=parityMetric(ups,'battery.runtime');
    const load=parityMetric(ups,'ups.load');
    const input=parityMetric(ups,'input.voltage');
    const metadata=(ups.components||[]).map(component=>component.metadata||{}).find(value=>
      value.power_source||value['ups.status']
    )||{};
    const source=metadata.power_source||'unknown';
    const sourceLabel=source==='utility'?'Utility':source==='battery'?'On battery':'Unknown';
    const status=metadata['ups.status']||'';
    const detail=[sourceLabel,status,Number.isFinite(load)?`${Math.round(load)}% load`:null,
      Number.isFinite(input)?`${Math.round(input)}V`:null].filter(Boolean).join(' · ');
    const telemetry=[Number.isFinite(charge)?`${Math.round(charge)}%`:null,
      Number.isFinite(runtime)?`${Math.round(runtime/60)}m`:null].filter(Boolean).join(' · ')||'—';
    return`<span class="parity-power-row"><b>${esc(ups.label)}</b><small>${esc(detail)}</small><strong>${esc(telemetry)}</strong></span>`;
  }).join('');
};

function betaFreshness(object){
  const enabled=(object.components||[]).filter(component=>component.enabled!==false);
  const observed=enabled.map(component=>component.observed_at).filter(Boolean)
    .map(value=>new Date(value).getTime()).filter(Number.isFinite);
  if(!enabled.length||!observed.length)return{label:'Unknown',copy:'No current observation timestamp'};
  const stale=enabled.some(component=>component.state==='unknown'&&/stale observation/i.test(String(component.summary||'')));
  const missing=enabled.some(component=>!component.observed_at);
  const newest=new Date(Math.max(...observed)).toISOString();
  return{label:stale?'Stale':missing?'Unknown':'Fresh',copy:`Newest check ${ageText(newest)}`};
}
function betaEnhanceFreshness(object){
  const stateSection=document.querySelector('#drawer-body > .detail-section');
  const stateCopy=stateSection?.querySelector('.detail-state > div:first-child');
  if(!stateCopy||stateCopy.querySelector('.beta-freshness'))return;
  const freshness=betaFreshness(object);
  stateCopy.insertAdjacentHTML('beforeend',`<div class="beta-freshness"><b>${esc(freshness.label)}</b><span>${esc(freshness.copy)}</span></div>`);
}
function betaMoveCameraMediaFirst(object){
  if(object.kind!=='camera')return;
  const body=$('#drawer-body'),media=body?.querySelector('.camera-media-section');
  const first=body?.querySelector(':scope > .detail-section');
  if(media&&first&&first!==media&&first.nextElementSibling!==media)first.insertAdjacentElement('afterend',media);
}
function betaAddGlobalDiagnostics(){
  const body=$('#drawer-body');
  if(!body||body.querySelector('.beta-global-diagnostics'))return;
  const sites=app.state?.sites||[];
  const agents=sites.flatMap(site=>site.agents||[]);
  const connected=agents.filter(agent=>agent.connected).length;
  const checkIds=new Set();
  for(const site of sites)for(const object of site.objects||[])for(const component of object.components||[]){
    if(component.id&&!String(component.id).includes(':'))checkIds.add(`${site.id}/${component.id}`);
  }
  const conditions=app.state?.global?.conditions?.length||0;
  const running=app.state?.active_operation?'Running':'Idle';
  const html=`<section class="detail-section beta-global-diagnostics"><h3>Monitoring status</h3><div class="metrics">${parityMetricBox('configured checks',String(checkIds.size))}${parityMetricBox('agents connected',`${connected}/${agents.length}`)}${parityMetricBox('full monitoring pass',running)}${parityMetricBox('current conditions',String(conditions))}</div></section>`;
  const actions=[...body.querySelectorAll(':scope > .detail-section')].find(section=>section.querySelector(':scope > h3')?.textContent==='Actions');
  if(actions)actions.insertAdjacentHTML('beforebegin',html);else body.insertAdjacentHTML('beforeend',html);
}

const betaBaseRenderDrawer=renderDrawer;
renderDrawer=function(){
  betaBaseRenderDrawer();
  if(!app.selected||!app.state){betaSyncDrawerBack();return;}
  const {object}=findObject(app.selected.siteId,app.selected.objectId);
  if(!object)return;
  betaEnhanceFreshness(object);
  betaMoveCameraMediaFirst(object);
  if(object.kind==='camera')betaRefreshCameraDebugPanel();
  betaSyncDrawerBack();
};

// Header controls are wired last so the generic navigation stack is the active
// interaction contract even though the base script was loaded first.
$('#drawer-back')?.addEventListener('click',betaGoBack);
if($('#drawer-close'))$('#drawer-close').onclick=()=>closeDrawer();
