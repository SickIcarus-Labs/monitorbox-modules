'use strict';

(() => {
  const nativeFetch=window.fetch.bind(window);
  const state={
    capability:false,
    open:false,
    socket:null,
    reconnect:null,
    events:[],
    seenServer:new Set(),
    localSequence:0,
    limit:1000,
    hooksInstalled:false,
  };
  window.monitorboxDebug={
    get enabled(){return state.capability;},
    emit:(category,message,fields={},level='info')=>emitBrowser(category,message,fields,level),
  };

  const $debug=id=>document.getElementById(id);
  const toggle=$debug('debug-toggle');
  const panel=$debug('debug-console');
  const close=$debug('debug-close');
  const filter=$debug('debug-filter');
  const search=$debug('debug-search');
  const log=$debug('debug-log');
  const connection=$debug('debug-connection');
  const count=$debug('debug-count');
  const copy=$debug('debug-copy');
  const clear=$debug('debug-clear');

  function cleanValue(value,depth=0){
    if(depth>2)return'[truncated]';
    if(value===null||value===undefined||typeof value==='boolean'||typeof value==='number')return value;
    if(typeof value==='string')return value.replace(/\s+/g,' ').replace(/Bearer\s+[^\s,;]+/ig,'Bearer [redacted]').slice(0,240);
    if(Array.isArray(value))return value.slice(0,20).map(item=>cleanValue(item,depth+1));
    if(typeof value==='object'){
      const result={};
      Object.entries(value).slice(0,20).forEach(([key,item])=>{
        const name=String(key).slice(0,64);
        if(/authorization|password|passwd|token|secret|cookie|credential|candidate|sdp|payload|base64|body/i.test(name))result[name]='[redacted]';
        else result[name]=cleanValue(item,depth+1);
      });
      return result;
    }
    return String(value).slice(0,240);
  }

  function localEvent(category,message,fields={},level='info'){
    state.localSequence+=1;
    return{
      sequence:`local-${state.localSequence}`,
      timestamp:new Date().toISOString(),
      category:category||'ui',
      source:'browser',
      level,
      message:String(message||'browser event').slice(0,180),
      fields:cleanValue(fields)||{},
      local:true,
    };
  }

  function appendEvent(event){
    if(!event||typeof event!=='object')return;
    if(typeof event.sequence==='number'){
      if(state.seenServer.has(event.sequence))return;
      state.seenServer.add(event.sequence);
    }
    state.events.push(event);
    if(state.events.length>state.limit)state.events.splice(0,state.events.length-state.limit);
    renderLog();
  }

  function mergeSnapshot(events){
    if(!Array.isArray(events))return;
    for(const event of events){
      if(!event||typeof event!=='object')continue;
      if(typeof event.sequence==='number'&&state.seenServer.has(event.sequence))continue;
      if(typeof event.sequence==='number')state.seenServer.add(event.sequence);
      state.events.push(event);
    }
    state.events.sort((a,b)=>String(a.timestamp||'').localeCompare(String(b.timestamp||'')));
    if(state.events.length>state.limit)state.events.splice(0,state.events.length-state.limit);
    renderLog();
  }

  function formatField(value){
    if(value===null||value===undefined||value==='')return'';
    if(typeof value==='object'){
      try{return JSON.stringify(value);}catch(_){return String(value);}
    }
    return String(value);
  }

  function formatEvent(event){
    let stamp='--:--:--.---';
    try{stamp=new Date(event.timestamp).toISOString().slice(11,23);}catch(_){}
    const category=String(event.category||'controller').toUpperCase();
    const source=String(event.source||'monitorbox');
    const level=event.level&&event.level!=='info'?` · ${String(event.level).toUpperCase()}`:'';
    const fields=Object.entries(event.fields||{})
      .filter(([,value])=>value!==null&&value!==undefined&&value!=='')
      .map(([key,value])=>`${key}=${formatField(value)}`)
      .join(' · ');
    return`${stamp} · ${category}${level} · ${source} · ${String(event.message||'event')}${fields?` · ${fields}`:''}`;
  }

  function visibleEvents(){
    const selected=filter?.value||'all';
    const needle=(search?.value||'').trim().toLowerCase();
    return state.events.filter(event=>{
      if(selected==='errors'&&!['warning','error'].includes(String(event.level)))return false;
      if(selected!=='all'&&selected!=='errors'&&event.category!==selected)return false;
      if(needle&&!formatEvent(event).toLowerCase().includes(needle))return false;
      return true;
    });
  }

  function renderLog(){
    if(!log)return;
    const visible=visibleEvents();
    log.textContent=visible.length?visible.map(formatEvent).join('\n'):'No matching debug events.';
    if(count)count.textContent=`${visible.length}/${state.events.length} shown`;
    log.scrollTop=log.scrollHeight;
  }

  function setConnection(label,kind=''){
    if(!connection)return;
    connection.textContent=label;
    connection.className=`debug-connection${kind?` ${kind}`:''}`;
  }

  function send(payload){
    const socket=state.socket;
    if(socket&&socket.readyState===WebSocket.OPEN){
      socket.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  function emitBrowser(category,message,fields={},level='info'){
    if(!state.capability)return;
    const safeFields=cleanValue(fields)||{};
    if(send({type:'browser_event',category,message,fields:safeFields,level}))return;
    appendEvent(localEvent(category,message,safeFields,level));
  }

  function connect(){
    if(!state.capability||!state.open)return;
    if(state.socket&&[WebSocket.OPEN,WebSocket.CONNECTING].includes(state.socket.readyState))return;
    clearTimeout(state.reconnect);
    setConnection('Connecting');
    const protocol=location.protocol==='https:'?'wss:':'ws:';
    const socket=new WebSocket(`${protocol}//${location.host}/api/v2/debug/ws`);
    state.socket=socket;
    socket.addEventListener('open',()=>setConnection('Live','live'));
    socket.addEventListener('message',event=>{
      let message;
      try{message=JSON.parse(event.data);}catch(_){return;}
      if(message.type==='hello'){
        if(Number.isFinite(Number(message.buffer_limit)))state.limit=Math.max(100,Number(message.buffer_limit));
      }else if(message.type==='snapshot'){
        mergeSnapshot(message.events);
      }else if(message.type==='event'){
        appendEvent(message.event);
      }
    });
    socket.addEventListener('error',()=>setConnection('Error','error'));
    socket.addEventListener('close',()=>{
      if(state.socket===socket)state.socket=null;
      setConnection(state.open?'Disconnected':'Paused',state.open?'error':'');
      if(state.open&&state.capability)state.reconnect=setTimeout(connect,1500);
    });
  }

  function disconnect(){
    clearTimeout(state.reconnect);
    state.reconnect=null;
    const socket=state.socket;
    state.socket=null;
    if(socket&&socket.readyState<=WebSocket.OPEN)socket.close(1000,'debug panel closed');
    setConnection('Paused');
  }

  function setOpen(open){
    state.open=!!open&&state.capability;
    if(panel)panel.hidden=!state.open;
    if(toggle){
      toggle.setAttribute('aria-pressed',state.open?'true':'false');
      toggle.classList.toggle('debug-toggle-active',state.open);
    }
    if(state.open){connect();renderLog();}
    else disconnect();
  }

  async function copyVisible(){
    const text=visibleEvents().map(formatEvent).join('\n');
    if(!text){if(typeof toast==='function')toast('Debug log is empty');return;}
    try{
      await navigator.clipboard.writeText(text);
      if(typeof toast==='function')toast('Debug log copied');
    }catch(_){
      const selection=window.getSelection();
      const range=document.createRange();
      range.selectNodeContents(log);
      selection?.removeAllRanges();
      selection?.addRange(range);
      if(typeof toast==='function')toast('Debug log selected — copy it');
    }
  }

  function clearLog(){
    state.events=[];
    state.seenServer.clear();
    renderLog();
    send({type:'clear'});
  }

  function installBrowserHooks(){
    if(state.hooksInstalled)return;
    state.hooksInstalled=true;

    window.addEventListener('error',event=>{
      emitBrowser('ui','browser error',{
        message:event.message||'unknown browser error',
        source:event.filename?new URL(event.filename,location.href).pathname:'',
        line:event.lineno||0,
        column:event.colno||0,
      },'error');
    });
    window.addEventListener('unhandledrejection',event=>{
      const reason=event.reason instanceof Error?`${event.reason.name}: ${event.reason.message}`:String(event.reason||'unknown rejection');
      emitBrowser('ui','unhandled promise rejection',{reason},'error');
    });

    document.addEventListener('click',event=>{
      const node=event.target instanceof Element?event.target.closest('button,a'):null;
      if(!node||node.closest('#debug-console'))return;
      const control=node.id||node.getAttribute('data-action-id')||node.getAttribute('data-run-object')!==null&&'run-object'||node.getAttribute('aria-label')||node.textContent?.trim().slice(0,60)||node.tagName.toLowerCase();
      emitBrowser('ui','operator interaction',{control,element:node.tagName.toLowerCase()});
    },true);

    window.fetch=async function(input,init={}){
      const method=String(init?.method||input?.method||'GET').toUpperCase();
      let path='';
      try{path=new URL(typeof input==='string'?input:input.url,location.href).pathname;}catch(_){}
      if(path.startsWith('/api/v2/debug/'))return nativeFetch(input,init);
      const category=path.includes('/cameras/')?'camera':path.includes('/traffic/')?'network':path.includes('/actions/')?'actions':path.includes('/checks/')||path.includes('/objects/')?'checks':'ui';
      const interesting=method!=='GET'||category==='camera';
      const started=performance.now();
      if(interesting)emitBrowser(category,'API request started',{method,path});
      try{
        const response=await nativeFetch(input,init);
        if(interesting||!response.ok)emitBrowser(category,'API request completed',{method,path,status:response.status,elapsed_ms:Math.round(performance.now()-started)},response.ok?'info':'warning');
        return response;
      }catch(error){
        emitBrowser(category,'API request failed',{method,path,error:`${error?.name||'Error'}: ${error?.message||error}`,elapsed_ms:Math.round(performance.now()-started)},'error');
        throw error;
      }
    };
  }

  function absorbCameraDiagnostics(){
    if(typeof betaCameraDebug==='function'){
      betaCameraDebug=function(source,stage,fields={}){
        emitBrowser('camera',stage,{relay_source:source,...cleanValue(fields)});
      };
    }
    if(typeof betaCameraDebugPanel==='function')betaCameraDebugPanel=function(){return'';};
    if(typeof betaRefreshCameraDebugPanel==='function')betaRefreshCameraDebugPanel=function(){};
    if(typeof betaBindCameraDebugControls==='function')betaBindCameraDebugControls=function(){};
    if(typeof renderCamera==='function'){
      const baseRenderCamera=renderCamera;
      renderCamera=function(site,object){
        return baseRenderCamera(site,object).replace(/<button[^>]*data-camera-debug-toggle[^>]*>Debug log<\/button>/g,'');
      };
    }
  }

  async function initialize(){
    absorbCameraDiagnostics();
    if(toggle)toggle.hidden=true;
    if(panel)panel.hidden=true;
    try{
      const response=await nativeFetch('/api/v2/debug/config',{cache:'no-store'});
      if(!response.ok)return;
      const config=await response.json();
      state.capability=config.enabled===true;
      if(Number.isFinite(Number(config.buffer_limit)))state.limit=Math.max(100,Number(config.buffer_limit));
      if(!state.capability)return;
      if(toggle)toggle.hidden=false;
      installBrowserHooks();
      emitBrowser('ui','debug capability available',{buffer_limit:state.limit});
    }catch(_){
      state.capability=false;
    }
  }

  toggle?.addEventListener('click',()=>setOpen(!state.open));
  close?.addEventListener('click',()=>setOpen(false));
  filter?.addEventListener('change',renderLog);
  search?.addEventListener('input',renderLog);
  copy?.addEventListener('click',()=>void copyVisible());
  clear?.addEventListener('click',clearLog);
  void initialize();
})();
