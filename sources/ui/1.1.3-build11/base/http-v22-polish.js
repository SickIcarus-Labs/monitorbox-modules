'use strict';

(()=>{
  const fields=document.getElementById('fields');
  const preset=document.getElementById('preset');
  if(!fields||!preset)return;

  const definitions=[
    ['statuses','Accepted HTTP status codes / ranges','200','text'],
    ['timeout_seconds','Timeout (seconds)','5','number'],
    ['follow_redirects','Follow redirects',true,'checkbox'],
    ['verify_tls','Verify HTTPS certificate',true,'checkbox'],
    ['contains','Response body must contain (optional)','','text'],
    ['response_header_name','Expected response header (optional)','','text'],
    ['response_header_value','Expected response header value (optional)','','text'],
    ['latency_warning_ms','Latency warning threshold ms (optional)','','number'],
    ['request_header_name','Protected request header name (optional)','','text'],
    ['request_header_value','Protected request header value (optional)','','password'],
  ];

  function makeField([key,label,value,type]){
    const wrap=document.createElement('label');
    wrap.className='field http-v22-field';
    wrap.dataset.key=key;
    wrap.append(document.createTextNode(label));
    const input=document.createElement('input');
    input.type=type;
    if(type==='checkbox')input.checked=!!value;
    else input.value=String(value??'');
    if(key==='statuses')input.placeholder='200,204,401 or 200-204';
    if(key==='request_header_name')input.placeholder='Authorization';
    if(key==='request_header_value')input.autocomplete='new-password';
    wrap.append(input);
    return wrap;
  }

  function apply(){
    const active=preset.value==='http_service';
    const existing=fields.querySelector('.http-v22-field');
    if(!active){
      if(existing)for(const element of fields.querySelectorAll('.http-v22-field'))element.remove();
      return;
    }
    // The underlying Quick Add renderer replaces #fields whenever the preset
    // changes. Rehydrate only when that renderer removed our controls; do not
    // mutate in response to our own append and create an observer loop.
    if(existing)return;
    fields.append(...definitions.map(makeField));
    const note=document.getElementById('secretNote');
    if(note){
      note.classList.remove('hidden');
      note.textContent='HTTP(S) is a first-class Connection. Accepted non-200 responses are valid when configured. Optional request-header values are stored as protected local credentials and never written into canonical configuration.';
    }
  }

  let queued=false;
  const schedule=()=>{
    if(queued)return;
    queued=true;
    queueMicrotask(()=>{queued=false;apply();});
  };
  const observer=new MutationObserver(schedule);
  observer.observe(fields,{childList:true});
  preset.addEventListener('change',schedule);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});
  else schedule();
})();
