'use strict';

(()=>{
  if(!location.pathname.startsWith('/settings/')||document.getElementById('settingsProductHome'))return;

  const GLOBAL_LINKS=[
    ['/settings','Configure'],
    ['/settings#connections','Connections'],
    ['/settings/discover','Discoveries'],
    ['/settings/dashboard','Dashboard / Graphs'],
    ['/modules','Modules'],
    ['/settings/policy','Actions'],
    ['/settings/appliance','Appliance'],
    ['/settings/recovery','Backup & Restore'],
  ];

  const style=document.createElement('style');
  style.id='settingsV22ShellStyle';
  style.textContent=`
    .settings-v22-identity{display:inline-flex;align-items:center;gap:6px;text-decoration:none;font-weight:750;white-space:nowrap}
    .settings-v22-site{display:inline-flex;align-items:center;text-decoration:none;font-weight:750;white-space:nowrap;max-width:28vw;overflow:hidden;text-overflow:ellipsis}
    .settings-v22-setup{opacity:.82}
    .settings-v22-menu-button{display:inline-grid;place-items:center;min-width:40px;height:40px;padding:0 10px;border:1px solid var(--line,#293b55);border-radius:10px;background:var(--panel2,#142238);color:var(--text,#eef5ff);font:700 20px/1 system-ui,-apple-system,sans-serif;cursor:pointer}
    .settings-v22-menu{position:fixed;z-index:60;top:62px;left:12px;display:flex;min-width:220px;max-width:calc(100vw - 24px);flex-direction:column;padding:7px;border:1px solid var(--line,#293b55);border-radius:12px;background:var(--panel,#101b2b);box-shadow:0 16px 36px #0008}
    .settings-v22-menu[hidden]{display:none}
    .settings-v22-menu a{display:block;padding:9px 11px;border-radius:8px;color:var(--text,#eef5ff);text-decoration:none;font-weight:650}
    .settings-v22-menu a:hover,.settings-v22-menu a:focus-visible{background:var(--panel2,#142238);outline:none}
    @media(max-width:760px){.settings-v22-site{max-width:24vw}.settings-v22-build{display:none}.settings-v22-menu{top:58px}}
  `;
  document.head.append(style);

  let header=document.querySelector('header.top');
  if(!header){
    header=document.createElement('header');
    header.className='top';
    header.style.cssText='position:sticky;top:0;z-index:20;display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:14px 18px;background:#07111fee;border-bottom:1px solid var(--line,#293b55);backdrop-filter:blur(16px)';
    document.body.prepend(header);
  }

  const menuButton=document.createElement('button');
  menuButton.id='settingsV22MenuButton';
  menuButton.className='settings-v22-menu-button';
  menuButton.type='button';
  menuButton.setAttribute('aria-label','Open MonitorBox navigation');
  menuButton.setAttribute('aria-controls','settingsV22Menu');
  menuButton.setAttribute('aria-expanded','false');
  menuButton.textContent='☰';

  const menu=document.createElement('nav');
  menu.id='settingsV22Menu';
  menu.className='settings-v22-menu';
  menu.hidden=true;
  menu.setAttribute('aria-label','MonitorBox');
  for(const [href,label] of GLOBAL_LINKS){
    const link=document.createElement('a');
    link.href=href;
    link.textContent=label;
    menu.append(link);
  }

  const closeMenu=()=>{
    menu.hidden=true;
    menuButton.setAttribute('aria-expanded','false');
  };
  menuButton.addEventListener('click',event=>{
    event.stopPropagation();
    const open=menu.hidden;
    menu.hidden=!open;
    menuButton.setAttribute('aria-expanded',open?'true':'false');
  });
  menu.addEventListener('click',event=>event.stopPropagation());
  document.addEventListener('click',closeMenu);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenu();});

  const product=document.createElement('a');
  product.id='settingsProductHome';
  product.className='settings-v22-identity';
  product.href='/settings';
  product.textContent='MonitorBox';

  const site=document.createElement('a');
  site.id='settingsSiteHome';
  site.className='settings-v22-site';
  site.href='/settings';
  site.textContent='Site';

  let back=[...header.querySelectorAll('a[href="/"]')].find(link=>link.id!=='settingsProductHome');
  if(!back){
    back=document.createElement('a');
    back.className='button';
    header.append(back);
  }
  back.id='settingsBackToMonitoring';

  header.prepend(product);
  header.prepend(menuButton);
  header.insertAdjacentElement('afterend',menu);
  const spacer=document.createElement('span');
  spacer.id='settingsV22Spacer';
  spacer.style.flex='1';
  header.append(spacer,site);

  function applyMode(setupComplete){
    const live=setupComplete===true;
    const target=live?'/':'/settings';
    for(const link of [product,site]){
      link.href=target;
      link.classList.toggle('settings-v22-setup',!live);
    }
    back.href=target;
    back.textContent=live?'Back to Main Dashboard':'Back to Configuration';
    back.setAttribute('aria-label',back.textContent);
    back.classList.toggle('settings-v22-setup',!live);
    if(!live&&site.textContent==='Site')site.textContent='Setup Draft';
  }

  function updateSiteLabel(value){
    const text=String(value||'').trim();
    if(text)site.textContent=text;
  }

  async function hydrate(){
    try{
      const statusResponse=await fetch('/api/v2/config/status',{headers:{Accept:'application/json'},cache:'no-store'});
      if(statusResponse.ok){
        const status=await statusResponse.json();
        applyMode(status.setup_complete===true);
      }
    }catch{/* conservative default remains /settings */}

    try{
      const stateResponse=await fetch('/api/v2/state',{headers:{Accept:'application/json'},cache:'no-store'});
      if(stateResponse.ok){
        const state=await stateResponse.json();
        const sites=Array.isArray(state.sites)?state.sites:[];
        if(sites.length===1)updateSiteLabel(sites[0]?.label||sites[0]?.id);
        else if(sites.length>1)updateSiteLabel(`${sites.length} sites`);
      }
    }catch{/* local select fallback below */}

    const select=document.querySelector('#siteSelect,#site');
    if(select instanceof HTMLSelectElement){
      const sync=()=>updateSiteLabel(select.selectedOptions[0]?.textContent||select.value);
      sync();
      select.addEventListener('change',sync);
    }
  }

  applyMode(false);
  hydrate();
})();
