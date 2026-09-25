'use strict';

// Card composer: same deliberate Show / Up / Down / Available / Validate ->
// Preview -> Apply model as Dashboard graphs. Only a successful authenticated
// optimistic-concurrency PUT can create a new canonical snapshot revision.
(()=>{
  const policy=globalThis.MonitorBoxCardPolicy;
  if(!policy)throw Error('Dashboard card policy did not load');
  const $=id=>document.getElementById(id);
  const copy=value=>JSON.parse(JSON.stringify(value));
  const empty=()=>({schema_version:policy.SCHEMA,data:{sites:{}}});
  let csrf=null,revision=null,contentHash=null,original=null,working=null;
  let publicSites=[],siteId=null,previewEntry=null,pending=false,restored=false;

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
    return working.data.sites[siteId].cards;
  }
  function rowFor(row){
    return entries().find(item=>item.id===row.id)||null;
  }
  function label(row){
    const match=rowFor(row);
    return match?.label||row.id+' (currently unavailable)';
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
    $('count').textContent=current.filter(row=>row.visible&&byId.has(row.id)).length+
      ' visible / '+current.length+' selected';
    $('selectedEmpty').hidden=current.length!==0;
    current.forEach((saved,index)=>{
      const available=byId.get(saved.id),el=document.createElement('div');
      el.className='layout-row'+(available?'':' unavailable');
      const identity=document.createElement('div');identity.className='identity';
      const heading=document.createElement('strong');
      heading.textContent=available?.label||saved.id;
      const sub=document.createElement('span');sub.className='sub';
      sub.textContent=available
        ?(available.kind==='family'?'Shared monitoring family':
          available.defaultVisible?'Intentional host or designated gateway':'Manually promoted device')
        :'Not present in live inventory; saved placement is retained.';
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
    let count=0;
    for(const item of missing){
      const category=item.kind==='family'?'Shared monitoring family':
        item.defaultVisible?'Intentional host or designated gateway':'Discovered or manually added device';
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
    $('add').disabled=pending||!missing.length;
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
