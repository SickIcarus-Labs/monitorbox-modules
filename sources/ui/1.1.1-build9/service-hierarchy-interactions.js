'use strict';

// UI 1.1.1 build 9: preserve child management affordances and explicit stack
// disclosure state across ordinary Service Directory refreshes.
const uiBuild9BaseProviderWorkloadObject=providerWorkloadObject;
const uiBuild9BaseProviderWorkloadDrawer=renderProviderWorkloadDrawer;
const uiBuild9BaseServiceStackRow=serviceStackRow;
const uiBuild9BaseBindServiceNavigation=bindServiceNavigation;

app.serviceStackExpansion=app.serviceStackExpansion||Object.create(null);

function uiBuild9SafeHttpUrl(value){
  const text=String(value||'').trim();
  if(!text)return null;
  try{
    const parsed=new URL(text);
    return parsed.protocol==='http:'||parsed.protocol==='https:'?parsed.href:null;
  }catch(_error){return null;}
}

function uiBuild9EndpointUrl(endpoint){
  if(!endpoint||typeof endpoint!=='object')return null;
  for(const key of ['presentation_url','management_url','url','href']){
    const direct=uiBuild9SafeHttpUrl(endpoint[key]);
    if(direct)return direct;
  }
  const scheme=String(endpoint.scheme||endpoint.presentation_scheme||'').trim().toLowerCase().replace(/:$/,'');
  if(!['http','https'].includes(scheme))return null;
  const host=String(endpoint.host||'').trim().replace(/^\[|\]$/g,'');
  const port=Number(endpoint.public_port||endpoint.port);
  if(!host||!Number.isInteger(port)||port<1||port>65535)return null;
  const authority=host.includes(':')?`[${host}]`:host;
  return uiBuild9SafeHttpUrl(`${scheme}://${authority}:${port}/`);
}

function uiBuild9ProviderPresentationUrl(workload){
  if(!workload||typeof workload!=='object')return null;
  for(const key of ['presentation_url','management_url']){
    const direct=uiBuild9SafeHttpUrl(workload[key]);
    if(direct)return direct;
  }
  for(const endpoint of workload.service_endpoints||[]){
    const url=uiBuild9EndpointUrl(endpoint);
    if(url)return url;
  }
  return null;
}

providerWorkloadObject=function(workload,host){
  const object=uiBuild9BaseProviderWorkloadObject(workload,host);
  object.presentation_url=uiBuild9ProviderPresentationUrl(workload);
  return object;
};

renderProviderWorkloadDrawer=function(site,object){
  uiBuild9BaseProviderWorkloadDrawer(site,object);
  if(!object?.presentation_url)return;
  const body=$('#drawer-body');
  if(!body)return;
  body.insertAdjacentHTML('beforeend',`<section class="detail-section"><h3>Management</h3><div class="action-list"><a class="button secondary open-service-icon" href="${esc(object.presentation_url)}" target="_blank" rel="noopener">Open management interface ↗</a></div></section>`);
};

function uiBuild9StackRemembered(key){
  return Object.prototype.hasOwnProperty.call(app.serviceStackExpansion,key)
    ? app.serviceStackExpansion[key]
    : null;
}

serviceStackRow=function(site,entry,parent){
  let html=uiBuild9BaseServiceStackRow(site,entry,parent);
  const key=String(entry?.group?.key||'');
  const forced=stateRank(entry?.state)>0;
  const remembered=key?uiBuild9StackRemembered(key):null;
  if(!forced&&remembered===true&&!/^<details\b[^>]*\sopen(?:\s|>)/.test(html)){
    html=html.replace(/^<details\b/,'<details open');
  }
  return html;
};

function uiBuild9BindStackDisclosure(){
  document.querySelectorAll('details[data-compose-stack]').forEach(node=>{
    if(node.dataset.uiBuild9DisclosureBound==='1')return;
    node.dataset.uiBuild9DisclosureBound='1';
    node.addEventListener('toggle',()=>{
      const key=String(node.dataset.composeStack||'');
      if(!key)return;
      const forced=[...node.classList].some(name=>['unknown','degraded','failed','offline'].includes(name));
      if(forced){
        if(!node.open)node.open=true;
        return;
      }
      app.serviceStackExpansion[key]=!!node.open;
    });
  });
}

function uiBuild9BindNestedPresentationLinks(){
  document.querySelectorAll('.service-compose-members a.icon-outbound, .service-compose-members a.open-service-icon').forEach(node=>{
    if(node.dataset.uiBuild9LinkBound==='1')return;
    node.dataset.uiBuild9LinkBound='1';
    node.addEventListener('click',event=>event.stopPropagation());
  });
}

bindServiceNavigation=function(site){
  uiBuild9BaseBindServiceNavigation(site);
  uiBuild9BindStackDisclosure();
  uiBuild9BindNestedPresentationLinks();
};

$('#drawer')?.addEventListener('close',()=>{
  app.serviceStackExpansion=Object.create(null);
});
