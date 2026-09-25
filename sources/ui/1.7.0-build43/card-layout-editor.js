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
    const saved=working?.data?.sites?.[siteId];
    return saved?.mode==='custom'||(restored && saved?.mode==='auto')
      ?saved.cards
      :policy.defaults(liveSite(),liveSite().objects||[]);
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
    $('validate').disabled=!siteId||!unsaved()||pending;
    $('apply').disabled=pending;
  }
  function button(name,fn,disabled=false,css='button'){
    const el=document.createElement('button');
    el.type='button';el.className=css;el.textContent=name;el.disabled=disabled;
    el.onclick=fn;return el;
  }
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
        list.push({id:item.id,visible:true});render();
      },pending,'button'));
      pool.append(row);
    }
    $('availableEmpty').hidden=count!==0;
    $('add').disabled=pending||!suggestions.length;
  }
  function render(){
    $('editor').hidden=false;
    renderSelected();renderAvailable();updateButtons();
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
      $('login').hidden=true;
      notice('');
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
        (descriptor.available?'':' · currently unavailable (saved reference retained)');
      identity.append(name,info);row.append(identity);
      const modes=registry.parseKey(item.key)?.[2]==='metric'
        ?['value','tile','list']:['tile','list'];
      const presentation=document.createElement('select');
      presentation.setAttribute('aria-label','Presentation for '+descriptor.label);
      for(const mode of modes){const option=document.createElement('option');
        option.value=mode;option.textContent=mode==='value'?'Metric value':
          mode==='tile'?'Status tile':'Compact list';presentation.append(option);}
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
          label.textContent=item.label+(item.unit?' ('+item.unit+')':'');
          line.append(input,label);detail.append(line);
        }
        outer.append(detail);
      }
      groups.append(outer);
    }
    $('pickerEmpty').hidden=shown!==0;
  }
  $('addContentItem').onclick=()=>{
    if(editingContents===null||pending)return;
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
      selectedItems.push({key,mode:kind==='metric'?'value':'tile'});
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
    list.push({id,visible:true,presentation:{schema_version:2,title,items:[]}});
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
  $('site').onchange=()=>{siteId=$('site').value;notice('');render();};
  $('search').oninput=()=>renderAvailable();
  $('add').onclick=()=>{
    // Reveal Available; individual Add controls make promotion explicit.
    $('search').focus();
    $('available').scrollIntoView({behavior:'smooth',block:'start'});
  };
  $('reset').onclick=()=>{
    working.schema_version=policy.SCHEMA;
    working.data.sites[siteId]={mode:'auto',cards:policy.defaults(liveSite(),liveSite().objects||[])};
    notice('Product defaults staged; Validate changes to preview and apply.');
    render();
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
      $('previewSummary').textContent='Site '+siteId+' · '+added+
        ' added · '+removed+' removed · '+after.filter(row=>row.visible).length+
        ' shown · mode '+mode+'. This saves a new recoverable configuration revision.';
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
