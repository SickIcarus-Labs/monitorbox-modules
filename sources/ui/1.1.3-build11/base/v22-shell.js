'use strict';

(()=>{
  const button=document.getElementById('v22-menu-button');
  const menu=document.getElementById('v22-menu');
  const site=document.getElementById('v22-site-name');
  const discoveries=document.getElementById('v22-discoveries');
  const discoveryCount=document.getElementById('v22-discoveries-count');
  if(button&&menu){
    const close=()=>{menu.hidden=true;button.setAttribute('aria-expanded','false');};
    button.addEventListener('click',event=>{event.stopPropagation();menu.hidden=!menu.hidden;button.setAttribute('aria-expanded',String(!menu.hidden));});
    menu.addEventListener('click',event=>event.stopPropagation());
    document.addEventListener('click',close);
    document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
  }

  async function refreshSiteIdentity(){
    if(!site)return;
    try{
      const response=await fetch('/api/v2/state',{headers:{Accept:'application/json'},cache:'no-store'});
      if(!response.ok)return;
      const state=await response.json();
      const sites=Array.isArray(state.sites)?state.sites:[];
      if(sites.length===1){site.textContent=sites[0].label||sites[0].id||'Site';site.title=site.textContent;return;}
      if(sites.length>1){
        const degraded=sites.find(item=>item&&item.state&&item.state!=='healthy');
        const selected=degraded||sites[0];
        site.textContent=selected?.label||selected?.id||`${sites.length} sites`;
        site.title=sites.map(item=>item.label||item.id).filter(Boolean).join(' · ');
      }
    }catch{/* dashboard.js owns offline status */}
  }

  async function refreshDiscoveries(){
    if(!discoveries||!discoveryCount)return;
    try{
      const response=await fetch('/api/v2/config/discovery/runtime/summary',{headers:{Accept:'application/json'},cache:'no-store'});
      if(!response.ok)return;
      const summary=await response.json();
      const raw=Number(summary?.pending_count);
      const count=Number.isFinite(raw)&&raw>=0?Math.floor(raw):0;
      discoveryCount.textContent=String(count);
      discoveries.hidden=count===0;
      const noun=count===1?'discovery':'discoveries';
      const impaired=summary?.visibility_impaired===true;
      discoveries.setAttribute('aria-label',`${count} pending runtime ${noun}`);
      discoveries.title=impaired
        ? `${count} pending runtime ${noun} · Portainer visibility is impaired; retained discoveries may be stale.`
        : `${count} pending runtime ${noun}`;
    }catch{/* retain last-known discovery state during transient dashboard/API failures */}
  }

  refreshSiteIdentity();
  refreshDiscoveries();
  setInterval(refreshSiteIdentity,30000);
  setInterval(refreshDiscoveries,10000);
})();
