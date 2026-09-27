'use strict';

// Card composer: same deliberate Show / Up / Down / Available / Validate ->
// Preview -> Apply model as Dashboard graphs. Only a successful authenticated
// optimistic-concurrency PUT can create a new canonical snapshot revision.
(()=>{
  const policy=globalThis.MonitorBoxCardPolicy;
  const registry=globalThis.MonitorBoxCardItems;
  if(!policy||!registry)throw Error('Dashboard card policy or item registry did not load');
  const $=id=>document.getElementById(id);
  const copy=value=>JSON.parse(JSON.stringify(value));
  const empty=()=>({schema_version:policy.SCHEMA,data:{sites:{}}});
  let csrf=null,revision=null,contentHash=null,original=null,working=null;
  let publicSites=[],siteId=null,previewEntry=null,pending=false,restored=false;
  let editingContents=null,selectedItems=[],pickerChosen=new Set();
  let arranging=false,arrangeStart=null,arrangeUndo=[],dragging=null;
  let previewFrame=null,previewReady=false,previewObserver=null,previewRetry=0;
  const LANES=['Left','Middle','Right'];
  const liveViewer='monitorbox-card-editor-'+Math.random().toString(36).slice(2);
  let liveRequestRunning=false,liveSourceCount=0;
  async function refreshLiveCatalog(){
    if(liveRequestRunning||document.hidden||!siteId)return;
    liveRequestRunning=true;
    try{
      const before=registry.catalog(liveSite()).items.size;
      const payload=await api('/api/v2/live?window=30',{
        headers:{'X-MonitorBox-Viewer':liveViewer},
      });
      registry.setLiveSeries(payload);
      const after=registry.catalog(liveSite()).items.size;
      liveSourceCount=(payload.series||[]).filter(row=>row.site_id===siteId).length;
      if($('liveCatalogStatus'))
        $('liveCatalogStatus').textContent=liveSourceCount
          ?liveSourceCount+' live series available · updated every second while viewing'
          :'Waiting for configured live telemetry. Standard metrics use 15-second status updates.';
      if($('itemPicker')?.open&&after!==before)showPicker();
    }catch(error){
      if($('liveCatalogStatus'))$('liveCatalogStatus').textContent=
        'Live telemetry unavailable; existing health and 15-second metrics remain selectable.';
    }finally{liveRequestRunning=false;}
  }
  setInterval(()=>{if(!$('editor').hidden)void refreshLiveCatalog();},1000);

  function notice(message,error=false){
    const el=$('layoutStatus');
    el.textContent=message;
    el.className='status'+(error?' error':' notice');
    el.hidden=!message;
  }
  function toast(message){
    const el=$('toast');
    el.textContent=message;
    el.style.display='block';
  }
  async function api(url,options={}){
    const headers={...(options.headers||{})};
    if(options.body)headers['Content-Type']='application/json';
    if(csrf&&options.method&&options.method!=='GET')
      headers['X-MonitorBox-CSRF']=csrf;
    const response=await fetch(url,{cache:'no-store',...options,headers});
    const raw=await response.text();
    let data;
    try{data=raw?JSON.parse(raw):{};}catch{data={error:raw};}
    if(!response.ok){
      const error=Error(data.error||data.message||raw||'HTTP '+response.status);
      error.status=response.status;
      throw error;
    }
    return data;
  }
  function liveSite(){return publicSites.find(site=>site.id===siteId)||{id:siteId,cards:[],objects:[]};}
  function entries(){
    const site=liveSite();
    return policy.availableEntries(site,site.objects||[]);
  }
  function rows(){
    return policy.siteRows(working,liveSite(),liveSite().objects||[],restored);
  }
  function changeRows(){
    const current=working.data.sites[siteId];
    if(!current||current.mode!=='custom')
      working.data.sites[siteId]={mode:'custom',cards:rows().map(row=>({...row}))};
    // Explicit edits upgrade historical UI41 v1 layouts, never on read.
    working.schema_version=policy.SCHEMA;
    return working.data.sites[siteId].cards;
  }
  function rowFor(row){
    return entries().find(item=>item.id===row.id)||null;
  }
  function label(row){
    const match=rowFor(row);
    return row.presentation?.title||match?.label||row.id+' (currently unavailable)';
  }
  function unsaved(){return JSON.stringify(working)!==JSON.stringify(original);}
  function updateButtons(){
    $('validate').disabled=!siteId||!unsaved()||pending||arranging;
    $('apply').disabled=pending;
  }
  function button(name,fn,disabled=false,css='button'){
    const el=document.createElement('button');
    el.type='button';el.className=css;el.textContent=name;el.disabled=disabled;
    el.onclick=fn;return el;
  }

  // #104 — placement is a UI preference, not a resource or canvas coordinate.
  // Editing the draft does not write canonical configuration until Apply.
  // Match the homepage's automatic column admission estimate exactly.
  // The old editor counted every raw network device, even though the card
  // renderer can display a shorter native summary; that made Arrange lie.
  function approximateHeight(row){
    const value=rowFor(row)?.value||{},family=String(value.family||value.id||'');
    const base=value.kind==='dashboard_card'
      ?family==='network'?185:['cameras','power'].includes(family)?135:95
      :90;
    return base+(Array.isArray(row.presentation?.items)?row.presentation.items.length:0)*51;
  }
  function initializePlacement(){
    const list=changeRows(),lanes=[0,0,0];
    list.forEach((row,i)=>{
      const lane=i<3?i:lanes.indexOf(Math.min(...lanes));
      row.placement={column:lane};
      if(row.visible)lanes[lane]+=approximateHeight(row)+9;
    });
    working.data.sites[siteId].arranged=true;
  }
  function arrangementSnapshot(){arrangeUndo.push(copy(working));}
  function arrangementRows(lane){
    return rows().filter(row=>row.visible&&row.placement?.column===lane);
  }
  function moveCard(id,lane,before=null){
    if(!arranging||pending||!Number.isInteger(lane)||lane<0||lane>2)return;
    const list=rows(),index=list.findIndex(row=>row.id===id);
    if(index<0||!list[index].visible||before===id)return;
    if(before&&!list.some(row=>row.id===before&&row.visible&&row.placement?.column===lane))return;
    const existingLane=list[index].placement.column;
    const ordered=arrangementRows(lane).filter(row=>row.id!==id).map(row=>row.id);
    const desired=before?ordered.indexOf(before):ordered.length;
    const current=ordered.indexOf(id);
    if(existingLane===lane&&((desired===ordered.length&&
      list.filter(row=>row.visible&&row.placement.column===lane).at(-1)?.id===id)||
      (before&&list.filter(row=>row.visible&&row.placement.column===lane)
        .findIndex(row=>row.id===id)===
       list.filter(row=>row.visible&&row.placement.column===lane)
        .findIndex(row=>row.id===before)-1)))return;
    arrangementSnapshot();
    const next=changeRows(),from=next.splice(next.findIndex(row=>row.id===id),1)[0];
    from.placement={column:lane};
    const at=before?next.findIndex(row=>row.id===before): -1;
    if(at>=0)next.splice(at,0,from);
    else{
      const last=next.reduce((idx,row,i)=>row.visible&&row.placement?.column===lane?i:idx,-1);
      next.splice(last+1,0,from);
    }
    $('arrangeStatus').textContent=label(from)+' moved to '+LANES[lane]+' column.';
    render();
  }
  function verticalMove(id,direction){
    const row=rows().find(item=>item.id===id),lane=row?.placement?.column;
    if(lane===undefined)return;
    const same=arrangementRows(lane),index=same.findIndex(item=>item.id===id);
    if(direction<0&&index>0)moveCard(id,lane,same[index-1].id);
    else if(direction>0&&index>=0&&index<same.length-1)
      moveCard(id,lane,same[index+2]?.id||null);
  }

  // Document-level capture keeps pointer movement and release observable even
  // when Safari changes targets during touch scrolling or a cross-lane drag.
  // The explicit placement is committed on pointer-up, never on every frame.
  function clearDropTarget(){
    for(const doc of [document,previewFrame?.contentDocument])
      doc?.querySelectorAll('.mb-arrange-target').forEach(node=>
        node.classList.remove('mb-arrange-target'));
  }
  function cancelDragging(){
    dragging?.item?.classList.remove('mb-arrange-dragging');
    dragging=null;clearDropTarget();
  }
  document.addEventListener('pointermove',event=>{
    if(!dragging||event.pointerId!==dragging.pointerId)return;
    const traveled=Math.hypot(event.clientX-dragging.startX,
                              event.clientY-dragging.startY);
    if(traveled<9)return;
    const edge=44,viewport=window.innerHeight||0;
    if(viewport&&event.clientY>viewport-edge)window.scrollBy?.(0,20);
    else if(event.clientY<edge)window.scrollBy?.(0,-20);
    const point=document.elementFromPoint(event.clientX,event.clientY);
    const slot=point?.closest?.('.mb-arrange-slot');
    const candidate=slot||point?.closest?.('.mb-arrange-card,.mb-arrange-column');
    const column=candidate?.closest?.('.mb-arrange-column');
    clearDropTarget();
    if(!column){dragging.last=null;return;}
    const before=slot?.dataset.mbBefore||
      candidate?.closest?.('.mb-arrange-card')?.dataset.mbArrangeCard||null;
    candidate.classList.add('mb-arrange-target');
    dragging.last={lane:Number(column.dataset.mbArrangeColumn),before};
  },true);
  document.addEventListener('pointerup',event=>{
    if(!dragging||event.pointerId!==dragging.pointerId)return;
    const {id,last,startX,startY}=dragging;
    const traveled=Math.hypot(event.clientX-startX,event.clientY-startY);
    cancelDragging();
    if(traveled>=9&&last)moveCard(id,last.lane,last.before);
  },true);
  document.addEventListener('pointercancel',cancelDragging,true);


  // UI50: the ONLY visual preview is an actual same-origin homepage instance.
  // The editor supplies a validated, ephemeral draft to its existing UI
  // renderer. Handles/actions sit OUTSIDE the rendered card DOM; CSS and native
  // contents remain exactly those of the homepage at the iframe's width.
  const frameCss=[
    'html,body{background:transparent!important;overflow:hidden!important;min-height:0!important}',
    'body>*:not(main):not(script):not(dialog){display:none!important}',
    'main.v1-shell{width:100%!important;max-width:none!important;padding:0!important;display:block!important}',
    'main.v1-shell>*:not(.parity-section){display:none!important}',
    'main.v1-shell>.parity-section{display:none!important;margin:0!important}',
    'main.v1-shell>.parity-section:has(#core-grid){display:block!important}',
    'main.v1-shell>.parity-section .parity-section-heading{display:none!important}',
    '#core-grid{margin:0!important;display:block!important}',
    '.mb-masonry-site>.parity-site-label{display:none!important}',
    '.mb-card-column{gap:0!important}',
    '.mb-arrange-frame-card{position:relative;min-width:0;width:100%;margin-bottom:9px}',
    '.mb-arrange-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;',
      'position:relative;min-height:42px;margin-bottom:5px}',
    '.mb-arrange-frame-card>.parity-card,.mb-arrange-frame-card>.mb-card-shell{width:100%;min-width:0}',
    '.mb-arrange-frame-card .parity-card,.mb-arrange-frame-card .mb-card-shell{pointer-events:none!important}',
    '.mb-arrange-handle{position:relative;z-index:7;border:1px solid #607fa1;',
      'border-radius:9px;background:#18324b;color:#f4f8fb;min-height:42px;',
      'min-width:44px;font-size:20px;touch-action:none;cursor:grab}',
    '.mb-arrange-handle:active{cursor:grabbing}',
    '.mb-arrange-toolbar .mb-arrange-actions{display:none;gap:4px;align-items:center;',
      'flex-wrap:wrap;min-width:0;padding:2px 4px;border:1px solid #607fa1;',
      'border-radius:9px;background:#101e31;max-width:100%}',
    '.mb-arrange-toolbar .mb-arrange-actions[data-open=true]{display:flex}',
    '.mb-arrange-actions button,.mb-arrange-actions select{min-height:41px;',
      'background:#233953;color:#f4f8fb;border:1px solid #607fa1;border-radius:7px}',
    '.mb-arrange-actions button{min-width:38px}',
    '.mb-arrange-actions button:disabled{opacity:.3}',
    '.mb-arrange-target{outline:2px solid #7da6ff!important;outline-offset:2px}',
    '.mb-arrange-dragging{outline:2px dashed #7da6ff;outline-offset:4px}',
    '.mb-arrange-end{height:22px;min-height:22px;border:1px dashed #527095;',
      'border-radius:8px;text-align:center;color:#a4b8ca;font:10px/20px system-ui}',
    '.mb-arrange-end.mb-arrange-target{background:#7da6ff24}',
  ].join('');
  function closeFrame(){
    previewObserver?.disconnect();previewObserver=null;
    if(previewFrame){previewFrame.onload=null;previewFrame.remove();}
    previewFrame=null;previewReady=false;previewRetry=0;
    $('arrangeColumns').classList.remove('mb-arrange-live');
  }
  function frameHeight(){
    if(!previewFrame?.isConnected)return;
    const doc=previewFrame.contentDocument;
    const grid=doc?.querySelector('#core-grid');
    if(!grid)return;
    previewFrame.style.height=Math.max(100,Math.ceil(
      grid.getBoundingClientRect().bottom+12))+'px';
  }
  function attachFramePointer(doc){
    doc.addEventListener('pointermove',event=>{
      if(!dragging||dragging.frameDoc!==doc||event.pointerId!==dragging.pointerId)return;
      if(Math.hypot(event.clientX-dragging.startX,event.clientY-dragging.startY)<9)return;
      dragging.moved=true;
      const y=previewFrame.getBoundingClientRect().top+event.clientY;
      if(y>window.innerHeight-44)window.scrollBy(0,22);
      else if(y<44)window.scrollBy(0,-22);
      const point=doc.elementFromPoint(event.clientX,event.clientY);
      const column=point?.closest?.('.mb-card-column');
      if(!column)return;
      const wrapper=point.closest?.('.mb-arrange-frame-card');
      let before=wrapper?.dataset.mbArrangeCard||null;
      if(wrapper&&event.clientY>wrapper.getBoundingClientRect().top+
        wrapper.getBoundingClientRect().height/2){
        before=wrapper.nextElementSibling?.classList.contains('mb-arrange-frame-card')
          ?wrapper.nextElementSibling.dataset.mbArrangeCard:null;
      }
      clearDropTarget();(wrapper||column).classList.add('mb-arrange-target');
      dragging.last={lane:Number(column.dataset.mbArrangeColumn),before};
    },true);
    doc.addEventListener('pointerup',event=>{
      if(!dragging||dragging.frameDoc!==doc||event.pointerId!==dragging.pointerId)return;
      const {id,last,startX,startY,handle}=dragging;
      const traveled=Math.hypot(event.clientX-startX,event.clientY-startY);
      if(traveled>=9&&handle)handle.dataset.mbMoved='true';
      cancelDragging();
      if(traveled>=9&&last)moveCard(id,last.lane,last.before);
    },true);
    doc.addEventListener('pointercancel',cancelDragging,true);
  }
  function decorateFrame(){
    if(!previewFrame?.isConnected||!arranging)return;
    const doc=previewFrame.contentDocument;
    if(!doc)return;
    // The homepage can rerender on the 15-second canonical-state cadence.
    // Watch its actual DOM rather than copying the stale editor inventory.
    const root=doc.querySelector('.mb-masonry-site[data-mb-site="'+siteId+'"]');
    if(!root)return;
    doc.querySelectorAll('.mb-masonry-site').forEach(node=>
      node.style.display=node===root?'':'none');
    const columns=[...root.querySelectorAll('.mb-card-column')];
    if(!columns.length)return;
    if(columns[0].querySelector('.mb-arrange-frame-card')){
      frameHeight();return;
    }
    previewObserver?.disconnect();
    const active=rows().filter(row=>row.visible);
    const rowForObject=new Map(active.map(row=>[row.id.slice(row.id.indexOf(':')+1),row]));
    for(const [lane,column] of columns.entries()){
      column.dataset.mbArrangeColumn=String(lane);
      column.setAttribute('aria-label',
        (columns.length===3?LANES[lane]:columns.length===2?
          ['Left','Middle and right'][lane]:'All')+' preview column');
      for(const card of [...column.children]){
        // Normal cards have the native data-object. A newly created custom
        // card carries its stable explicit ID, never its mutable label.
        const objectId=card.dataset.object||
          card.querySelector('[data-object]')?.dataset.object||
          card.dataset.mbCustomCardId||'';
        const saved=rowForObject.get(objectId);
        if(!saved)continue;
        const wrapper=doc.createElement('div');
        wrapper.className='mb-arrange-frame-card';
        wrapper.dataset.mbArrangeCard=saved.id;
        column.insertBefore(wrapper,card);wrapper.append(card);
        const toolbar=doc.createElement('div');
        toolbar.className='mb-arrange-toolbar';
        const handle=doc.createElement('button');
        handle.type='button';handle.className='mb-arrange-handle';
        handle.textContent='☷';handle.title='Drag to arrange; tap for move controls';
        handle.setAttribute('aria-label','Drag or tap to move '+label(saved));
        handle.setAttribute('aria-expanded','false');
        handle.onpointerdown=event=>{
          if(event.button!==0||pending||!arranging)return;
          event.preventDefault();
          dragging={id:saved.id,pointerId:event.pointerId,
            startX:event.clientX,startY:event.clientY,last:null,
            item:wrapper,frameDoc:doc,handle,moved:false};
          try{handle.setPointerCapture?.(event.pointerId);}catch(_){}
          wrapper.classList.add('mb-arrange-dragging');
        };
        handle.onkeydown=event=>{
          if(event.key==='ArrowUp'){event.preventDefault();verticalMove(saved.id,-1);}
          else if(event.key==='ArrowDown'){event.preventDefault();verticalMove(saved.id,1);}
          else if(event.key==='ArrowLeft'){event.preventDefault();
            moveCard(saved.id,Math.max(0,saved.placement.column-1));}
          else if(event.key==='ArrowRight'){event.preventDefault();
            moveCard(saved.id,Math.min(2,saved.placement.column+1));}
        };
        const actions=doc.createElement('div');
        actions.className='mb-arrange-actions';
        actions.id='mb-move-'+saved.id.replace(/[^a-z0-9_-]/gi,'-');
        handle.setAttribute('aria-controls',actions.id);
        handle.onclick=()=>{
          if(handle.dataset.mbMoved==='true'){
            delete handle.dataset.mbMoved;return;
          }
          const opened=actions.dataset.open!=='true';
          actions.dataset.open=String(opened);
          handle.setAttribute('aria-expanded',String(opened));
        };
        const action=(name,fn,disabled=false)=>{
          const b=doc.createElement('button');b.type='button';b.textContent=name;
          b.disabled=disabled;b.onclick=fn;return b;
        };
        const logical=saved.placement?.column??lane;
        const same=arrangementRows(logical),index=same.findIndex(row=>row.id===saved.id);
        const select=doc.createElement('select');
        select.setAttribute('aria-label','Move '+label(saved)+' to column');
        LANES.forEach((name,i)=>{
          const option=doc.createElement('option');option.value=String(i);
          option.textContent=name;select.append(option);
        });
        select.value=String(logical);
        select.onchange=()=>moveCard(saved.id,Number(select.value));
        actions.append(
          action('←',()=>moveCard(saved.id,logical-1),logical===0),
          action('↑',()=>verticalMove(saved.id,-1),index===0),
          action('↓',()=>verticalMove(saved.id,1),index===same.length-1),
          action('→',()=>moveCard(saved.id,logical+1),logical===2),
          select);
        toolbar.append(handle,actions);
        wrapper.prepend(toolbar);
      }
      const end=doc.createElement('div');
      end.className='mb-arrange-end';end.textContent='Drop at end';
      column.append(end);
    }
    previewReady=true;$('doneArrange').disabled=pending;
    if(!$('arrangeStatus').textContent||
        $('arrangeStatus').textContent.startsWith('Loading the actual')||
        $('arrangeStatus').textContent.startsWith('Preview syncing'))
      $('arrangeStatus').textContent='Actual homepage preview ready · '+
        active.length+' cards. Drag the grip, or tap it for move controls.';
    frameHeight();
    const grid=doc.querySelector('#core-grid');
    if(grid&&doc.defaultView.MutationObserver){
      previewObserver=new doc.defaultView.MutationObserver(()=>{
        if(arranging&&!grid.querySelector('.mb-arrange-frame-card'))
          doc.defaultView.requestAnimationFrame(decorateFrame);
        else frameHeight();
      });
      previewObserver.observe(grid,{childList:true,subtree:false});
    }
  }
  function syncFrame(){
    if(!previewFrame?.contentWindow?.MonitorBoxCardLayout)return;
    try{
      previewReady=false;$('doneArrange').disabled=true;
      previewObserver?.disconnect();previewObserver=null;
      previewFrame.contentWindow.MonitorBoxCardLayout.setPreview(copy(working));
      const doc=previewFrame.contentDocument;
      if(!doc?.querySelector('.mb-card-column')){
        if(++previewRetry<90)window.setTimeout(syncFrame,100);
        else $('arrangeStatus').textContent=
          'The actual homepage preview did not become ready. No arrangement can be committed.';
        return;
      }
      previewRetry=0;decorateFrame();
    }catch(error){
      $('arrangeStatus').textContent='Homepage preview unavailable: '+error.message+
        '. No arrangement can be committed.';
    }
  }
  function renderArrangement(){
    const visible=rows().filter(row=>row.visible);
    const hidden=rows().length-visible.length;
    $('arrangeDescription').textContent='Live homepage preview · '+visible.length+
      ' cards'+(hidden?' · '+hidden+' hidden retained':'')+
      '. Drag the grip to arrange; tap the same grip for arrow/column controls. Card content and dimensions match the homepage.';
    $('undoArrange').disabled=pending||!arrangeUndo.length;
    if(!previewFrame){
      $('arrangeColumns').replaceChildren();
      $('arrangeColumns').classList.add('mb-arrange-live');
      previewFrame=document.createElement('iframe');
      previewFrame.id='mb-arrange-actual-homepage';
      previewFrame.title='Actual homepage card arrangement preview';
      previewFrame.setAttribute('loading','eager');
      previewFrame.style.cssText='display:block;width:100%;border:0;min-height:240px;height:400px;background:transparent';
      $('arrangeColumns').append(previewFrame);
      $('arrangeStatus').textContent='Loading the actual homepage preview…';
      previewFrame.onload=()=>{
        if(!arranging)return;
        try{
          const doc=previewFrame.contentDocument;
          const style=doc.createElement('style');style.id='mb-arrange-preview-style';
          style.textContent=frameCss;doc.head.append(style);
          attachFramePointer(doc);
          syncFrame();
        }catch(error){
          $('arrangeStatus').textContent='Same-origin preview failed: '+error.message;
        }
      };
      previewFrame.src='/?mb_layout_preview=1';
    }else syncFrame();
  }
  function endArrange(cancel){
    if(!arranging)return;
    if(cancel&&arrangeStart)working=copy(arrangeStart);
    arranging=false;arrangeStart=null;arrangeUndo=[];dragging=null;
    closeFrame();
    $('arrangeStatus').textContent=cancel?'Arrangement canceled; earlier draft edits retained.':
      'Arrangement staged. Validate changes, preview and Apply to save one revision.';
    render();
  }
  $('arrange').onclick=()=>{
    if(pending||arranging)return;
    arrangeStart=copy(working);arrangeUndo=[];
    const existing=working.data.sites[siteId];
    if(existing?.arranged!==true)initializePlacement();
    arranging=true;render();
  };
  $('undoArrange').onclick=()=>{
    if(!arranging||!arrangeUndo.length)return;
    working=arrangeUndo.pop();$('arrangeStatus').textContent='Last move undone.';render();
  };
  $('doneArrange').onclick=()=>endArrange(false);
  $('cancelArrange').onclick=()=>endArrange(true);

  function renderSelected(){
    const selected=$('selected');
    selected.replaceChildren();
    const current=rows();
    const byId=new Map(entries().map(item=>[item.id,item]));
    $('count').textContent=current.filter(row=>row.visible&&(byId.has(row.id)||row.id.startsWith('custom:'))).length+
      ' visible / '+current.length+' selected';
    $('selectedEmpty').hidden=current.length!==0;
    current.forEach((saved,index)=>{
      const available=byId.get(saved.id),custom=saved.id.startsWith('custom:');
      const el=document.createElement('div');
      el.className='layout-row'+(available||custom?'':' unavailable');
      const identity=document.createElement('div');identity.className='identity';
      const heading=document.createElement('strong');
      heading.textContent=saved.presentation?.title||available?.label||saved.id;
      const sub=document.createElement('span');sub.className='sub';
      sub.textContent=custom?'Custom card · '+(saved.presentation?.items?.length||0)+' selected items':
        available?(available.kind==='family'?'Shared monitoring family':
          available.defaultVisible?'Intentional host or designated gateway':'Legacy standalone device'):
        'Not present in live inventory; saved placement is retained.';
      identity.append(heading,sub);el.append(identity);
      const toggle=document.createElement('label');toggle.className='toggle';
      const input=document.createElement('input');
      input.type='checkbox';input.checked=saved.visible;input.disabled=pending;
      input.setAttribute('aria-label','Show '+(available?.label||saved.id));
      input.onchange=()=>{
        const list=changeRows();list[index].visible=input.checked;render();
      };
      toggle.append(input,document.createTextNode('Show'));
      el.append(toggle);
      el.append(button('↑',()=>{
        const list=changeRows();[list[index-1],list[index]]=[list[index],list[index-1]];
        render();
      },pending||index===0,'button move'));
      el.append(button('↓',()=>{
        const list=changeRows();[list[index+1],list[index]]=[list[index],list[index+1]];
        render();
      },pending||index===current.length-1,'button move'));
      el.append(button('Edit contents',()=>openContents(index),pending,'button'));
      el.append(button('Remove',()=>{
        changeRows().splice(index,1);render();
      },pending,'button danger'));
      selected.append(el);
    });
  }
  function renderAvailable(){
    const pool=$('available');pool.replaceChildren();
    const search=$('search').value.trim().toLowerCase();
    const selected=new Set(rows().map(row=>row.id));
    const missing=entries().filter(item=>!selected.has(item.id))
      .sort((a,b)=>Number(b.kind==='family')-Number(a.kind==='family')||
        a.label.localeCompare(b.label));
    // Devices and metrics are selected inside the shared item picker, never
    // promoted as an unbounded top-level Available card list.
    const suggestions=missing.filter(item=>item.kind==='family'||item.defaultVisible);
    let count=0;
    for(const item of suggestions){
      const category=item.kind==='family'?'Shared monitoring family':
        'Intentional host or designated gateway';
      if(search&&!([item.id,item.label,category].join(' ').toLowerCase().includes(search)))continue;
      count++;
      const row=document.createElement('div');row.className='available-item';
      const identity=document.createElement('div');
      const heading=document.createElement('strong');heading.textContent=item.label;
      const detail=document.createElement('span');detail.className='sub';
      detail.textContent=category+' · '+item.id;
      identity.append(heading,detail);
      row.append(identity,button('Add',()=>{
        const list=changeRows();
        if(list.some(row=>row.id===item.id))return;
        if(list.length>=128){notice('Maximum 128 selected cards.',true);return;}
        list.push({id:item.id,visible:true,...(working.data.sites[siteId].arranged?{placement:{column:0}}:{})});render();
      },pending,'button'));
      pool.append(row);
    }
    $('availableEmpty').hidden=count!==0;
    $('add').disabled=pending||!suggestions.length;
  }
  function render(){
    $('editor').hidden=false;
    renderSelected();renderAvailable();
    $('selected').hidden=arranging;$('arrangePanel').hidden=!arranging;
    $('arrange').disabled=arranging||pending;
    $('add').disabled=arranging||$('add').disabled;
    $('createCustom').disabled=arranging||pending;
    $('regenerate').disabled=arranging||pending;
    $('regenAll').disabled=arranging||pending;
    $('regenScope').hidden=publicSites.length<2;
    if(arranging)renderArrangement();
    updateButtons();
  }

  async function authenticate(){
    const status=await api('/api/v2/config/status');
    if(status.authenticated){
      csrf=(await api('/api/v2/config/session')).csrf_token;
      $('login').hidden=true;
      await load();
    }else{
      $('login').hidden=false;
      $('editor').hidden=true;
      $('loginStatus').textContent='Sign in to change the homepage.';
    }
  }
  async function load(){
    if(pending)return;
    pending=true;updateButtons();
    try{
      const [current,state]=await Promise.all([
        api('/api/v2/config/current'),api('/api/v2/state'),
      ]);
      const entry=current.config?.module_preferences?.[policy.MODULE_ID]||null;
      policy.validate(entry); // Never silently reset a future/invalid schema.
      if(!Number.isInteger(current.revision)||typeof current.content_hash!=='string')
        throw Error('Canonical revision identity is missing');
      const sites=Array.isArray(current.config.sites)?current.config.sites:[];
      if(!sites.length)throw Error('No configured sites are available to edit');
      if(!Array.isArray(state.sites))throw Error('Live site/card projection is unavailable');
      const live=new Map(state.sites.map(site=>[site.id,site]));
      if(sites.some(site=>!live.has(site.id)||!Array.isArray(live.get(site.id).cards)))
        throw Error('Core site.cards projection is unavailable; no layout changes were made');
      publicSites=sites.map(site=>live.get(site.id));
      revision=current.revision;contentHash=current.content_hash;
      restored=Array.isArray(current.config.metadata?.restored_preference_ids)&&
        current.config.metadata.restored_preference_ids.includes(policy.MODULE_ID);
      arranging=false;arrangeStart=null;arrangeUndo=[];closeFrame();
      original=copy(entry||empty());working=copy(original);
      const previous=siteId;
      siteId=sites.some(site=>site.id===previous)?previous:sites[0].id;
      $('site').replaceChildren();
      for(const site of sites){
        const option=document.createElement('option');
        option.value=site.id;option.textContent=site.label||site.id;
        $('site').append(option);
      }
      $('site').value=siteId;
      $('regenAll').checked=false;
      $('login').hidden=true;
      notice('');
      await refreshLiveCatalog();
      render();
    }catch(error){
      // Keep an already loaded editor intact on transient read failure.
      notice('Reload failed: '+error.message,true);
      if(!working){$('editor').hidden=true;$('login').hidden=false;
        $('loginStatus').textContent=error.message;}
    }finally{pending=false;if(working&&!$('editor').hidden)render();else updateButtons();}
  }
  // UI-owned, versioned content preferences. All member selection below is
  // homepage-only; never mutate canonical objects or the full detail drawer.
  function membersFor(row){
    const selected=rowFor(row);
    if(!selected||selected.kind!=='family')return [];
    const site=liveSite();
    const objects=Array.isArray(site.objects)?site.objects:[];
    const family=String(selected.value.family||selected.value.id||'');
    const kinds=family==='network'?new Set(['network_device','remote_site']):
      family==='cameras'?new Set(['camera']):
      family==='power'?new Set(['ups']):null;
    if(!kinds)return [];
    return objects.filter(object=>kinds.has(object.kind))
      .map(object=>({id:String(object.id),label:String(object.label||object.id)}))
      .sort((a,b)=>a.label.localeCompare(b.label));
  }

  // The same grouped source/item picker serves preset and custom cards.
  // Draft selections are display-only references to existing public telemetry.
  function showSelectedItems(){
    const container=$('contentSelectedItems');container.replaceChildren();
    if(!selectedItems.length){
      const empty=document.createElement('p');empty.className='muted';
      empty.textContent='No additional items. Use Add item to browse monitored sources.';
      container.append(empty);return;
    }
    const index=registry.catalog(liveSite()).items;
    selectedItems.forEach((item,i)=>{
      const descriptor=registry.display(liveSite(),item.key,index);
      const row=document.createElement('div');row.className='mb-selected-item';
      const identity=document.createElement('div');identity.className='identity';
      const name=document.createElement('strong');name.textContent=descriptor.label;
      const info=document.createElement('span');info.className='sub';
      info.textContent=descriptor.sourceLabel+
        (descriptor.available?'':descriptor.type==='live'
          ?' · waiting for fresh live sample (reference retained)'
          :' · currently unavailable (saved reference retained)');
      identity.append(name,info);row.append(identity);
      const type=registry.parseKey(item.key)?.[2];
      const modes=['metric','live'].includes(type)
        ?['value','list','tile']:['list','tile'];
      const presentation=document.createElement('select');
      presentation.setAttribute('aria-label','Presentation for '+descriptor.label);
      for(const mode of modes){const option=document.createElement('option');
        option.value=mode;option.textContent=mode==='value'?'Live/metric value':
          mode==='tile'?'Tile':'Compact row';presentation.append(option);}
      presentation.value=item.mode;
      presentation.onchange=()=>{selectedItems[i].mode=presentation.value;};
      row.append(presentation,
        button('↑',()=>{[selectedItems[i-1],selectedItems[i]]=
          [selectedItems[i],selectedItems[i-1]];showSelectedItems();},pending||i===0,'button move'),
        button('↓',()=>{[selectedItems[i+1],selectedItems[i]]=
          [selectedItems[i],selectedItems[i+1]];showSelectedItems();},
          pending||i===selectedItems.length-1,'button move'),
        button('Remove',()=>{selectedItems.splice(i,1);showSelectedItems();},
          pending,'button danger'));
      container.append(row);
    });
  }
  function showPicker(){
    const query=$('pickerSearch').value.trim().toLowerCase();
    const groups=$('pickerGroups');groups.replaceChildren();
    const catalog=registry.catalog(liveSite());
    let shown=0;
    for(const group of catalog.groups){
      const sources=group.sources.map(source=>({...source,items:source.items.filter(item=>
        !query||[source.label,item.label,item.metricKey,group.label].join(' ')
          .toLowerCase().includes(query))})).filter(source=>source.items.length);
      if(!sources.length)continue;
      const outer=document.createElement('details');outer.className='mb-picker-group';
      outer.open=!!query;
      const summary=document.createElement('summary');
      summary.textContent=group.label+' · '+sources.length+' sources';outer.append(summary);
      for(const source of sources){
        const detail=document.createElement('details');detail.className='mb-picker-source';
        detail.open=!!query;
        const heading=document.createElement('summary');
        heading.textContent=source.label+' · '+source.items.length+' items';detail.append(heading);
        for(const item of source.items){
          shown++;
          const line=document.createElement('label');line.className='member-option';
          const input=document.createElement('input');input.type='checkbox';
          input.checked=pickerChosen.has(item.key);
          input.onchange=()=>{if(input.checked)pickerChosen.add(item.key);
            else pickerChosen.delete(item.key);};
          const label=document.createElement('span');
          label.textContent=item.label+(item.type==='live'
            ?' · LIVE (1 s samples when configured)'
            :item.type==='metric'?' · state (~15 s)':item.type==='check'?' · health':'')+
            (item.unit?' ('+item.unit+')':'');
          line.append(input,label);detail.append(line);
        }
        outer.append(detail);
      }
      groups.append(outer);
    }
    $('pickerEmpty').hidden=shown!==0;
  }
  $('addContentItem').onclick=async()=>{
    if(editingContents===null||pending)return;
    await refreshLiveCatalog();
    pickerChosen=new Set(selectedItems.map(item=>item.key));
    $('pickerSearch').value='';showPicker();$('itemPicker').showModal();
  };
  $('pickerSearch').oninput=showPicker;
  $('cancelPicker').onclick=()=>{$('itemPicker').close();};
  $('donePicker').onclick=()=>{
    const existing=new Map(selectedItems.map(item=>[item.key,item]));
    const catalog=registry.catalog(liveSite()).items;
    // Existing order is preserved; newly checked items append by catalog order.
    selectedItems=selectedItems.filter(item=>pickerChosen.has(item.key));
    for(const [key] of catalog){
      if(!pickerChosen.has(key)||existing.has(key))continue;
      if(selectedItems.length>=64){$('itemPicker').close();
        $('contentError').textContent='Maximum 64 items per card.';
        $('contentError').hidden=false;showSelectedItems();return;}
      const kind=registry.parseKey(key)?.[2];
      selectedItems.push({key,mode:['metric','live'].includes(kind)?'value':'list'});
    }
    $('itemPicker').close();showSelectedItems();
  };
  $('createCustom').onclick=()=>{
    if(pending)return;
    $('newCardTitle').value='';$('newCardError').hidden=true;$('newCard').showModal();
  };
  $('cancelNewCard').onclick=()=>{$('newCard').close();};
  $('saveNewCard').onclick=()=>{
    const title=$('newCardTitle').value.trim();
    if(!title||title.length>80){$('newCardError').textContent='Enter a 1–80 character title.';
      $('newCardError').hidden=false;return;}
    if(rows().length>=128){$('newCardError').textContent='Maximum 128 cards.';
      $('newCardError').hidden=false;return;}
    const list=changeRows();
    let id;
    do{
      const bytes=new Uint8Array(12);
      if(globalThis.crypto?.getRandomValues)globalThis.crypto.getRandomValues(bytes);
      else for(let i=0;i<bytes.length;i++)bytes[i]=Math.floor(Math.random()*256);
      id='custom:c'+Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    }
    while(list.some(row=>row.id===id));
    list.push({id,visible:true,presentation:{schema_version:2,title,items:[]},
       ...(working.data.sites[siteId].arranged?{placement:{column:0}}:{})});
    const index=list.length-1;
    $('newCard').close();render();openContents(index);
  };

  function openContents(index){
    const row=rows()[index];
    if(!row||pending)return;
    editingContents=index;
    const own=row.presentation||{};
    selectedItems=Array.isArray(own.items)?copy(own.items):[];
    $('contents-heading').textContent='Edit contents · '+label(row);
    $('contentTitle').value=own.title||label(row);
    $('contentCompact').checked=own.compact===true;
    $('contentError').hidden=true;
    const members=membersFor(row);
    const hidden=new Set(own.hidden_member_ids||[]);
    const panel=$('contentMembersPanel'),list=$('contentMembers');
    list.replaceChildren();
    panel.hidden=!members.length;
    for(const item of members){
      const line=document.createElement('label');
      line.className='member-option';
      const input=document.createElement('input');
      input.type='checkbox';input.checked=!hidden.has(item.id);
      input.dataset.memberId=item.id;
      line.append(input,document.createTextNode(item.label));
      list.append(line);
    }
    showSelectedItems();
    $('contents').showModal();
  }
  $('cancelContents').onclick=()=>{
    $('contents').close();editingContents=null;
  };
  $('saveContents').onclick=()=>{
    if(editingContents===null||pending)return;
    const originalRow=rows()[editingContents];
    if(!originalRow)return;
    const title=$('contentTitle').value.trim();
    const base=rowFor(originalRow)?.label||originalRow.presentation?.title||originalRow.id;
    const previous=originalRow.presentation||{};
    const currentlyListed=new Set([...$('contentMembers').querySelectorAll('input[data-member-id]')]
      .map(input=>input.dataset.memberId));
    const hidden=[
      ...(previous.hidden_member_ids||[]).filter(id=>!currentlyListed.has(id)),
      ...[...$('contentMembers').querySelectorAll('input[data-member-id]')]
        .filter(input=>!input.checked).map(input=>input.dataset.memberId),
    ];
    const custom=originalRow.id.startsWith('custom:');
    const itemContent=custom||selectedItems.length>0||Array.isArray(previous.items);
    const preference={schema_version:itemContent?2:1};
    if(custom||title!==base)preference.title=title;
    if(itemContent)preference.items=copy(selectedItems);
    if($('contentCompact').checked)preference.compact=true;
    if(hidden.length)preference.hidden_member_ids=hidden;
    try{
      if(Object.keys(preference).length>1)
        policy.validatePresentation(preference);
      const row=changeRows()[editingContents];
      if(Object.keys(preference).length>1)row.presentation=preference;
      else delete row.presentation;
      $('contents').close();editingContents=null;
      notice('Card contents staged. Validate changes to preview and apply.');
      render();
    }catch(error){
      $('contentError').textContent=error.message;
      $('contentError').hidden=false;
    }
  };

  $('loginButton').onclick=async()=>{
    try{
      const response=await api('/api/v2/config/auth/login',{
        method:'POST',body:JSON.stringify({password:$('password').value}),
      });
      csrf=response.csrf_token;$('password').value='';
      $('login').hidden=true;await load();
    }catch(error){$('loginStatus').textContent=error.message;}
  };
  $('password').addEventListener('keydown',event=>{
    if(event.key==='Enter')$('loginButton').click();
  });
  $('site').onchange=()=>{if(arranging)endArrange(true);siteId=$('site').value;notice('');render();};
  $('search').oninput=()=>renderAvailable();
  $('add').onclick=()=>{
    // Reveal Available; individual Add controls make promotion explicit.
    $('search').focus();
    $('available').scrollIntoView({behavior:'smooth',block:'start'});
  };
  // One user-visible action replaces the redundant single-site and all-site
  // resets. It is a DRAFT only; canonical state changes on explicit Apply.
  $('regenerate').onclick=()=>{
    if(pending||arranging)return;
    const all=publicSites.length>1&&$('regenAll').checked;
    const targets=all?publicSites:[liveSite()];
    const prior=targets.reduce((n,site)=>n+
      (working?.data?.sites?.[site.id]?.cards||[]).length,0);
    const fresh=targets.reduce((n,site)=>n+
      policy.defaults(site,site.objects||[]).length,0);
    if(!confirm('Regenerate dashboard for '+
      (all?'ALL '+targets.length+' sites':liveSite().label||siteId)+'? This discards '+
      prior+' existing card definitions, custom cards, manual readings and saved positions in the selected scope, replacing them with '+
      fresh+' capability-aware defaults. Other monitoring and graphs are unchanged. Take a full appliance backup before Apply.'))return;
    const next=copy(working);
    next.schema_version=policy.SCHEMA;
    for(const site of targets)next.data.sites[site.id]={
      mode:'auto',cards:policy.defaults(site,site.objects||[])};
    try{
      policy.validate(next);working=next;
      notice((all?'All sites':'Site '+siteId)+' regenerated in the draft. '+
        'Validate, review and Apply to create one recoverable configuration revision.');
      render();
    }catch(error){notice('Regenerate refused: '+error.message,true);}
  };
  $('reload').onclick=()=>{
    if(working&&unsaved()&&!confirm('Discard unsaved card changes and reload?'))return;
    load();
  };
  $('validate').onclick=()=>{
    try{
      policy.validate(working);
      if(!unsaved())return toast('No changes to apply.');
      const before=policy.siteRows(original,liveSite(),liveSite().objects||[],restored);
      const after=policy.siteRows(working,liveSite(),liveSite().objects||[],
        restored && JSON.stringify(working)===JSON.stringify(original));
      const oldIds=new Set(before.map(row=>row.id)),newIds=new Set(after.map(row=>row.id));
      const added=after.filter(row=>!oldIds.has(row.id)).length;
      const removed=before.filter(row=>!newIds.has(row.id)).length;
      const mode=working.data.sites[siteId]?.mode||'auto';
      const spatial=working.data.sites[siteId]?.arranged===true;
      $('previewSummary').textContent='Site '+siteId+' · '+added+
        ' added · '+removed+' removed · '+after.filter(row=>row.visible).length+
        ' shown · mode '+mode+(spatial?' · spatial columns':' · automatic columns')+
        '. This saves one recoverable configuration revision.';
      $('previewChanges').textContent=JSON.stringify({
        before:before.map(row=>({card:label(row),...row})),
        after:after.map(row=>({card:label(row),...row})),
        site_mode:mode,
      },null,2);
      previewEntry=copy(working);
      $('apply').disabled=false;$('preview').showModal();
    }catch(error){notice('Validation failed: '+error.message,true);}
  };
  $('cancelPreview').onclick=()=>{$('preview').close();previewEntry=null;};
  $('apply').onclick=async()=>{
    if(!previewEntry||pending)return;
    pending=true;$('apply').disabled=true;updateButtons();
    try{
      const saved=await api(
        '/api/v2/config/module-preferences/'+encodeURIComponent(policy.MODULE_ID),
        {method:'PUT',body:JSON.stringify({
          revision,content_hash:contentHash,preferences:previewEntry,
        })},
      );
      revision=saved.revision;contentHash=saved.content_hash;
      original=copy(previewEntry);working=copy(previewEntry);restored=false;
      previewEntry=null;$('preview').close();
      notice('Applied as configuration revision '+revision+
        '. Its paired layout is available in Configuration snapshots.');
      toast('Dashboard cards saved.');
      render();
    }catch(error){
      $('preview').close();previewEntry=null;
      notice(error.status===409
        ?'Another configuration change or snapshot restore occurred. Your edits remain staged. Reload and review before saving.'
        :'Apply failed: '+error.message,true);
    }finally{pending=false;if(working&&!$('editor').hidden)render();else updateButtons();}
  };
  authenticate().catch(error=>{
    $('login').hidden=false;$('loginStatus').textContent=error.message;
  });
})();
