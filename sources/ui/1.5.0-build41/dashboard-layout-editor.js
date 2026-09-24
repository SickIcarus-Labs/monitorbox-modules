'use strict';

// The current graph editor is the interaction baseline: select site, Show,
// move up/down, Remove, Available, Validate -> Preview -> Apply. This editor
// changes only UI-owned composition, never canonical monitored Resources.
(()=>{
  const UI_ID='com.sickicarus.monitorbox.ui';
  const model=globalThis.MonitorBoxCardProjection;
  if(!model) throw new Error('Dashboard layout editor requires card projection');

  let editor=null,preview=null,working=null,original=null,csrf=null;
  let revision=null,contentHash=null,siteId=null,loading=false;
  let messageTimer=null;
  const deep=value=>JSON.parse(JSON.stringify(value));
  const el=(tag,cls,text)=>{
    const item=document.createElement(tag);
    if(cls)item.className=cls;
    if(text!==undefined)item.textContent=text;
    return item;
  };
  const jsonApi=async(url,options={})=>{
    const headers={...(options.headers||{})};
    if(options.body&&typeof options.body==='string'){
      headers['Content-Type']='application/json';
    }
    if(csrf&&options.method&&options.method!=='GET'){
      headers['X-MonitorBox-CSRF']=csrf;
    }
    const response=await fetch(url,{...options,headers,credentials:'same-origin'});
    const body=await response.text();
    let data={};
    try{data=body?JSON.parse(body):{}}catch{data={error:body}}
    if(!response.ok)throw new Error(data.error||body||'HTTP '+response.status);
    return data;
  };
  const $=id=>editor?.querySelector('#'+id);
  function site(){
    return(app.state?.sites||[]).find(item=>item.id===siteId)||null;
  }
  function status(text,bad=false){
    if(!editor)return;
    const node=$('card-editor-status');
    node.textContent=text;
    node.className='mb-card-status'+(bad?' bad':'');
  }
  function available(){
    const s=site();
    return s?model.allAvailable(s):[];
  }
  function siteState(id){
    return working?.data?.sites?.[id]||null;
  }
  function currentOrder(){
    const saved=siteState(siteId);
    return saved?.mode==='custom'&&Array.isArray(saved.order)
      ? [...saved.order]:model.defaultKeys(site());
  }
  function hiddenKeys(){
    const saved=siteState(siteId);
    return new Set(saved?.mode==='custom'&&Array.isArray(saved.hidden)?saved.hidden:[]);
  }
  function editableSite(){
    const id=siteId;
    if(!working.data||typeof working.data!=='object')working.data={};
    if(!working.data.sites||typeof working.data.sites!=='object')working.data.sites={};
    const saved=working.data.sites[id];
    if(!saved||saved.mode!=='custom'){
      working.data.sites[id]={mode:'custom',order:currentOrder(),hidden:[]};
    }
    return working.data.sites[id];
  }
  function editorShell(){
    if(editor)return;
    editor=el('dialog','mb-card-editor');
    editor.id='mb-card-editor';
    editor.innerHTML=[
      '<header class="mb-card-head">',
      '<h2>Edit Dashboard</h2><span class="mb-card-spacer"></span>',
      '<button type="button" id="card-editor-close" class="mb-card-button">Cancel</button>',
      '<button type="button" id="card-editor-validate" class="mb-card-button primary">Validate changes</button>',
      '</header>',
      '<div id="card-editor-login" class="mb-card-login" hidden>',
      '<p>Enter the configuration administrator password to edit your homepage.</p>',
      '<input type="password" id="card-editor-password" autocomplete="current-password" aria-label="Administrator password">',
      '<button type="button" id="card-editor-login-button" class="mb-card-button primary">Sign in</button>',
      '</div>',
      '<main id="card-editor-main" hidden>',
      '<div class="mb-card-toolbar"><label>Site <select id="card-editor-site"></select></label>',
      '<span class="mb-card-spacer"></span>',
      '<button type="button" id="card-editor-reset" class="mb-card-button">Reset to defaults</button></div>',
      '<p class="mb-card-note">Show or hide cards, change their order, or remove them from this homepage. ',
      'Removed cards and hosts remain monitored and available to add. Changes do not apply until you review and save.</p>',
      '<section class="mb-card-section"><h3>Homepage cards</h3>',
      '<div id="card-editor-rows"></div></section>',
      '<section class="mb-card-section"><h3>Available cards and hosts</h3>',
      '<label class="mb-card-search">Find a card or host <input id="card-editor-search" type="search" placeholder="Search cards, hosts, discovered devices"></label>',
      '<div id="card-editor-available"></div></section>',
      '</main><div id="card-editor-status" class="mb-card-status" role="status"></div>'
    ].join('');
    document.body.append(editor);
    preview=el('dialog','mb-card-preview');
    preview.innerHTML=[
      '<h2>Review dashboard changes</h2>',
      '<p>Only this homepage layout changes. Monitoring, alerts and credentials are unaffected. ',
      'The layout is saved with the configuration revision and restored with its snapshot.</p>',
      '<pre id="card-editor-diff"></pre>',
      '<div class="mb-card-actions">',
      '<button type="button" id="card-preview-cancel" class="mb-card-button">Back</button>',
      '<button type="button" id="card-preview-save" class="mb-card-button primary">Apply</button>',
      '</div>',
      '<div id="card-preview-status" class="mb-card-status" role="status"></div>'
    ].join('');
    document.body.append(preview);
    $('card-editor-close').onclick=()=>editor.close();
    $('card-editor-validate').onclick=validate;
    $('card-editor-reset').onclick=()=>{
      if(!working||!siteId)return;
      working.data.sites=working.data.sites||{};
      working.data.sites[siteId]={mode:'default',order:[],hidden:[]};
      render();
    };
    $('card-editor-site').onchange=()=>{
      siteId=$('card-editor-site').value;
      render();
    };
    $('card-editor-search').oninput=renderAvailable;
    $('card-editor-login-button').onclick=async()=>{
      try{
        const value=$('card-editor-password').value;
        const response=await jsonApi('/api/v2/config/auth/login',{
          method:'POST',body:JSON.stringify({password:value})
        });
        csrf=response.csrf_token;
        $('card-editor-password').value='';
        await load();
      }catch(error){status(error.message,true)}
    };
    preview.querySelector('#card-preview-cancel').onclick=()=>preview.close();
    preview.querySelector('#card-preview-save').onclick=apply;
  }
  async function load(){
    if(loading)return;
    loading=true;
    try{
      const response=await jsonApi('/api/v2/config/current');
      revision=response.revision;
      contentHash=response.content_hash;
      const existing=response.config?.module_preferences?.[UI_ID];
      if(existing&&existing.schema_version!==1){
        throw new Error('This layout uses a newer schema. Use Recovery to update the UI instead of overwriting it.');
      }
      original=existing?deep(existing):{schema_version:1,data:{sites:{}}};
      working=deep(original);
      const sites=app.state?.sites||[];
      if(!sites.length)throw new Error('The dashboard has no configured site.');
      siteId=sites.some(item=>item.id===siteId)?siteId:sites[0].id;
      const siteSelect=$('card-editor-site');
      siteSelect.replaceChildren();
      for(const item of sites){
        const option=el('option',null,item.label||item.id);
        option.value=item.id;
        siteSelect.append(option);
      }
      siteSelect.value=siteId;
      $('card-editor-login').hidden=true;
      $('card-editor-main').hidden=false;
      render();
      status('Changes are staged locally until you validate and apply them.');
    }catch(error){
      status(error.message,true);
      if(String(error.message).includes('401')){
        $('card-editor-login').hidden=false;
      }else if(!csrf&&String(error.message).toLowerCase().includes('auth')){
        $('card-editor-login').hidden=false;
      }
    }finally{loading=false}
  }
  async function open(){
    editorShell();
    editor.showModal();
    status('Loading dashboard configuration…');
    $('card-editor-main').hidden=true;
    try{
      const session=await jsonApi('/api/v2/config/session');
      csrf=session.csrf_token;
      await load();
    }catch(error){
      $('card-editor-login').hidden=false;
      status('Administrator sign-in is required to edit the dashboard.');
    }
  }
  function labelFor(key,byKey){
    const found=byKey.get(key);
    return found?.object?.label||'Unavailable: '+key;
  }
  function render(){
    if(!working||!site())return;
    const all=available(), byKey=new Map(all.map(item=>[item.key,item]));
    const order=currentOrder(),hidden=hiddenKeys();
    const rows=$('card-editor-rows');
    rows.replaceChildren();
    for(let i=0;i<order.length;i++){
      const key=order[i];
      const item=byKey.get(key);
      const row=el('div','mb-card-row');
      const toggle=el('label','mb-card-toggle');
      const input=el('input');
      input.type='checkbox';
      input.checked=!hidden.has(key);
      input.setAttribute('aria-label','Show '+labelFor(key,byKey));
      input.onchange=()=>{
        const saved=editableSite(),set=new Set(saved.hidden);
        if(input.checked)set.delete(key);else set.add(key);
        saved.hidden=[...set];
        render();
      };
      toggle.append(input,document.createTextNode('Show'));
      row.append(toggle);
      const details=el('div','mb-card-name');
      details.append(el('strong',null,labelFor(key,byKey)));
      details.append(el('span','mb-card-kind',item?.group||'Unavailable (retained)'));
      row.append(details);
      function arrow(text,delta){
        const button=el('button','mb-card-button',text);
        button.type='button';
        button.disabled=i+delta<0||i+delta>=order.length;
        button.setAttribute('aria-label',(delta<0?'Move up ':'Move down ')+labelFor(key,byKey));
        button.onclick=()=>{
          const list=editableSite().order;
          [list[i],list[i+delta]]=[list[i+delta],list[i]];
          render();
        };
        return button;
      }
      row.append(arrow('↑',-1),arrow('↓',1));
      const remove=el('button','mb-card-button','Remove');
      remove.type='button';
      remove.setAttribute('aria-label','Remove '+labelFor(key,byKey)+' from homepage');
      remove.onclick=()=>{
        const saved=editableSite();
        saved.order=saved.order.filter(item=>item!==key);
        saved.hidden=saved.hidden.filter(item=>item!==key);
        render();
      };
      row.append(remove);
      rows.append(row);
    }
    if(!order.length)rows.append(el('p','mb-card-note','No cards selected. Monitoring continues in the Resources and Services views.'));
    renderAvailable();
  }
  function renderAvailable(){
    if(!working||!site())return;
    const list=$('card-editor-available'),order=new Set(currentOrder());
    const search=$('card-editor-search').value.trim().toLowerCase();
    const candidates=available()
      .filter(item=>!order.has(item.key))
      .filter(item=>
        !search||String(item.object.label||item.key).toLowerCase().includes(search)
        ||item.key.toLowerCase().includes(search)
      );
    list.replaceChildren();
    for(const item of candidates){
      const row=el('div','mb-card-row');
      const label=el('div','mb-card-name');
      label.append(el('strong',null,item.object.label||item.key));
      label.append(el('span','mb-card-kind',item.group));
      row.append(label);
      const button=el('button','mb-card-button','+ Add card');
      button.type='button';
      button.setAttribute('aria-label','Add '+(item.object.label||item.key)+' to homepage');
      button.onclick=()=>{
        const saved=editableSite();
        saved.order.push(item.key);
        saved.hidden=saved.hidden.filter(key=>key!==item.key);
        render();
      };
      row.append(button);
      list.append(row);
    }
    if(!candidates.length){
      list.append(el('p','mb-card-note',
        search?'No available cards match this search.':'All available cards are selected.'));
    }
  }
  function validate(){
    if(!working)return;
    if(!working.data||!working.data.sites)working.data={...working.data,sites:{}};
    for(const [id,settings] of Object.entries(working.data.sites)){
      if(!['custom','default'].includes(settings.mode)){
        return status('Unsupported layout mode for site '+id,true);
      }
      if(!Array.isArray(settings.order)||!Array.isArray(settings.hidden)){
        return status('Invalid layout selections for site '+id,true);
      }
      if(new Set(settings.order).size!==settings.order.length){
        return status('Duplicate card in site '+id,true);
      }
    }
    const old=original?.data?.sites||{},next=working.data.sites||{};
    const changed=JSON.stringify(old)!==JSON.stringify(next);
    preview.querySelector('#card-editor-diff').textContent=JSON.stringify({
      changed,previous:old,proposed:next
    },null,2);
    preview.querySelector('#card-preview-status').textContent=
      changed?'Review the complete proposed layout before saving.':
      'No layout changes staged.';
    preview.querySelector('#card-preview-save').disabled=!changed;
    preview.showModal();
  }
  async function apply(){
    const button=preview.querySelector('#card-preview-save');
    button.disabled=true;
    try{
      const response=await jsonApi('/api/v2/config/module-preferences/'+UI_ID,{
        method:'PUT',
        body:JSON.stringify({
          revision,content_hash:contentHash,preferences:working,
        })
      });
      preview.close();
      editor.close();
      location.reload();
    }catch(error){
      preview.querySelector('#card-preview-status').textContent=
        'Apply failed: '+error.message+'. No partial layout was saved.';
      button.disabled=false;
    }
  }
  globalThis.MonitorBoxDashboardEditor=Object.freeze({open});
})();