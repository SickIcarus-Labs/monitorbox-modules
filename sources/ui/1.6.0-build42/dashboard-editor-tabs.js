'use strict';

// One Dashboard configuration entry with two peer editors. The existing
// /settings/cards and /settings/dashboard deep links remain stable.
(()=>{
  if(!/^\/settings\/(?:dashboard|cards)(?:\/|$)/.test(location.pathname))return;
  const MARKER='mb-dashboard-editor-tabs';
  function install(){
    if(document.getElementById(MARKER))return true;
    const peer=document.getElementById('mb-configuration-peer-nav');
    const anchor=peer||document.getElementById('mb-app-shell')||
      document.querySelector('header.top');
    if(!anchor?.parentNode)return false;
    const nav=document.createElement('nav');
    nav.id=MARKER;
    nav.setAttribute('aria-label','Dashboard editor');
    const onCards=location.pathname.startsWith('/settings/cards');
    for(const [name,label,href] of [
      ['cards','Cards','/settings/cards'],
      ['graphs','Graphs','/settings/dashboard'],
    ]){
      const link=document.createElement('a');
      link.href=href;link.textContent=label;
      if((name==='cards')===onCards){
        link.className='active';link.setAttribute('aria-current','page');
      }
      nav.append(link);
    }
    anchor.insertAdjacentElement('afterend',nav);
    if(peer&&onCards){
      for(const link of peer.querySelectorAll('a[href]')){
        if(link.getAttribute('href')==='/settings'){
          link.classList.remove('active');link.removeAttribute('aria-current');
        }
        if(link.getAttribute('href')==='/settings/dashboard'){
          link.classList.add('active');link.setAttribute('aria-current','page');
        }
      }
    }
    return true;
  }
  function boot(){
    if(install())return;
    const observer=new MutationObserver(()=>{
      if(install())observer.disconnect();
    });
    observer.observe(document.documentElement,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')
    document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();
