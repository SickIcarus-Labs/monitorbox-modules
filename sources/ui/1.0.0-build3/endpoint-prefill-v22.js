'use strict';

(()=>{
  if(location.pathname!=='/settings/quick-add')return;

  const query=new URLSearchParams(location.search);
  const preset=String(query.get('preset')||'').trim().toLowerCase();
  const kind=preset==='scrypted'?'scrypted':(['http','http_service'].includes(preset)?'http':'');

  function safeEndpoint(value){
    const text=String(value||'').trim();
    if(!text||text.length>2048)return'';
    try{
      const endpoint=new URL(text);
      if(!['http:','https:'].includes(endpoint.protocol))return'';
      if(!endpoint.hostname||endpoint.username||endpoint.password)return'';
      if(endpoint.search||endpoint.hash)return'';
      return endpoint.origin;
    }catch{return''}
  }

  const endpoint=safeEndpoint(query.get('endpoint'));
  if(!kind||!endpoint)return;

  function applyPrefill(){
    const card=[...document.querySelectorAll('#connectionList .connection')]
      .find(row=>
        String(row.dataset.kind||'').toLowerCase()===kind&&
        String(row.dataset.endpoint||'').toLowerCase().startsWith('manual://')
      );
    if(!card)return;
    const key=kind==='scrypted'?'base_url':'url';
    const field=card.querySelector(`[data-key="${key}"]`);
    if(!field)return;
    field.value=endpoint;
    card.dataset.v22EndpointPrefill='provider';

    const fields=card.querySelector('.connection-fields');
    if(fields&&!fields.querySelector('[data-v22-endpoint-prefill-note]')){
      const note=document.createElement('div');
      note.className='muted';
      note.dataset.v22EndpointPrefillNote='1';
      note.style.gridColumn='1/-1';
      note.textContent='Prefilled from the provider-advertised endpoint. Review it, supply any required credentials, then validate before Finish.';
      fields.prepend(note);
    }
  }

  if(typeof renderConnections!=='function')return;
  const baseRenderConnections=renderConnections;
  renderConnections=function(items){
    const result=baseRenderConnections(items);
    applyPrefill();
    return result;
  };

  const startCopy=document.getElementById('startCopy');
  if(startCopy){
    startCopy.textContent=`Provider evidence supplied ${endpoint} for this Connection. MonitorBox will prefill that endpoint for review, but will not guess credentials or apply anything until validation and Finish.`;
  }
})();
