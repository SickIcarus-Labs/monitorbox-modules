'use strict';

(()=>{
  const path=location.pathname;
  const sourceHints=[
    ['scrypted','Scrypted'],
    ['portainer','Portainer'],
    ['docker','Portainer'],
    ['unifi','UniFi Network'],
    ['nut','NUT'],
    ['snmp','SNMP'],
    ['ping','Ping'],
  ];
  let scheduled=false;
  let credentialProjection=null;
  let credentialFetch=null;

  function styleOnce(){
    if(document.getElementById('followupBetaPolishStyle'))return;
    const style=document.createElement('style');
    style.id='followupBetaPolishStyle';
    style.textContent=`
      .connection-group{border-top:1px solid #1e3048;background:#0c1828}
      .connection-group>summary{cursor:pointer;padding:10px 15px;font-weight:750;color:#dce9f9;list-style:none}
      .connection-group>summary::-webkit-details-marker{display:none}
      .connection-group>summary::before{content:'▸';display:inline-block;width:17px;color:var(--muted)}
      .connection-group[open]>summary::before{content:'▾'}
      .connection-group-body>.item{padding-left:28px;background:#0a1524}
      .semantic-context{color:var(--muted);font-size:11px;margin-left:5px}
      .advanced-semantic-index{margin:0 0 10px;padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:#0b1726;color:var(--muted);font-size:11px}
      .already-monitored-hint{margin-top:6px;color:#a9efbf;font-size:11px}
      .credential-bundle{border-top:1px solid var(--line);padding:14px 0}
      .credential-bundle:first-child{border-top:0}
      .credential-bundle-head{display:flex;gap:10px;align-items:flex-start;justify-content:space-between;margin-bottom:5px}
      .credential-bundle-title{font-size:15px;font-weight:800;color:var(--text)}
      .credential-bundle-used{font-size:12px;color:var(--muted);margin-top:3px}
      .credential-bundle-fields{margin-top:8px;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#0b1726}
      .credential-bundle-fields>.credential{border-top:1px solid var(--line);padding:11px 12px;background:#0b1726}
      .credential-bundle-fields>.credential:first-child{border-top:0}
      .credential-bundle-fields .credential-title{font-size:13px}
      .credential-bundle-fields .credential-kind{font-size:11px}
    `;
    document.head.append(style);
  }

  function humanKind(raw){
    const text=String(raw||'').trim();
    const key=text.toLowerCase();
    return ({
      host:'Host',appliance:'Appliance',network_device:'Network device',remote_site:'Remote site',
      service:'Service',camera:'Camera',cameras:'Cameras',ups:'UPS',integration:'Integration',
      docker_container:'Docker workload',docker_workload:'Docker workload',grouped_object:'Grouped Object',
    })[key]||text.replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase());
  }

  function sourceFromText(text){
    const lower=String(text||'').toLowerCase();
    for(const [needle,label] of sourceHints)if(lower.includes(needle))return label;
    return '';
  }

  function polishSemanticRow(row,{object=false}={}){
    if(row.dataset.followupSemantic==='true')return;
    const small=row.querySelector(':scope > div:first-child > small');
    if(!small)return;
    const original=String(small.textContent||'').trim();
    const parts=original.split(' · ');
    const rawKind=String(parts[0]||'').trim();
    const kindKey=rawKind.toLowerCase();
    if(rawKind)parts[0]=humanKind(rawKind);
    let source=sourceFromText(row.querySelector('.abilities')?.textContent||'');
    if(object&&!source){
      if(kindKey==='ups')source='NUT';
      else if(kindKey==='camera'||kindKey==='cameras')source='Scrypted';
      else if(kindKey.includes('docker'))source='Portainer';
    }
    if(source&&!parts.some(part=>part.toLowerCase()===`via ${source.toLowerCase()}`))parts.push(`via ${source}`);
    const next=parts.filter(Boolean).join(' · ');
    if(small.textContent!==next)small.textContent=next;
    row.dataset.followupSemantic='true';
  }

  function groupConnections(){
    const root=document.getElementById('connectionRows');
    if(!root||root.dataset.followupBusy==='true')return;
    const rows=[...root.children].filter(node=>node.classList?.contains('item'));
    if(rows.length<3)return;
    const byLabel=new Map();
    for(const row of rows){
      const label=String(row.querySelector('strong')?.textContent||'Connection').trim();
      if(!byLabel.has(label))byLabel.set(label,[]);
      byLabel.get(label).push(row);
    }
    const grouped=new Map([...byLabel].filter(([,items])=>items.length>=3));
    if(!grouped.size)return;
    root.dataset.followupBusy='true';
    try{
      const emitted=new Set();
      for(const row of [...rows]){
        const label=String(row.querySelector('strong')?.textContent||'Connection').trim();
        const items=grouped.get(label);
        if(!items||emitted.has(label))continue;
        emitted.add(label);
        const details=document.createElement('details');
        details.className='connection-group';
        details.dataset.followupConnectionGroup=label;
        const summary=document.createElement('summary');
        summary.textContent=`${label} · ${items.length}`;
        const body=document.createElement('div');
        body.className='connection-group-body';
        details.append(summary,body);
        root.insertBefore(details,row);
        for(const item of items)body.append(item);
      }
    }finally{
      root.dataset.followupBusy='false';
    }
  }

  function polishRefresh(){
    if(path!=='/settings')return;
    const button=document.getElementById('refresh');
    const mode=document.getElementById('mode');
    if(!button||!mode)return;
    const modeText=String(mode.textContent||'').trim();
    const live=modeText==='Live Configuration';
    const setup=modeText==='Setup Draft';
    if(!live&&!setup){
      if(button.dataset.setupRefreshDisabled!=='true'){
        button.dataset.setupRefreshDisabled='true';
        button.disabled=true;
      }
      const title='Run all checks is available after Finish. Use Discovery tools to test staged Connections.';
      if(button.title!==title)button.title=title;
      if(button.getAttribute('aria-label')!=='Refresh unavailable before monitoring is active')button.setAttribute('aria-label','Refresh unavailable before monitoring is active');
      return;
    }
    if(setup){
      if(button.dataset.setupRefreshDisabled!=='true')button.dataset.setupRefreshDisabled='true';
      if(!button.disabled)button.disabled=true;
      const title='Run all checks is available after Finish. Use Discovery tools to test staged Connections.';
      if(button.title!==title)button.title=title;
      if(button.getAttribute('aria-label')!=='Refresh unavailable during Setup Draft')button.setAttribute('aria-label','Refresh unavailable during Setup Draft');
      return;
    }
    if(button.dataset.setupRefreshDisabled==='true'){
      delete button.dataset.setupRefreshDisabled;
      button.disabled=false;
    }
    if(button.title!=='Run all checks now')button.title='Run all checks now';
    if(button.getAttribute('aria-label')!=='Refresh — run all checks')button.setAttribute('aria-label','Refresh — run all checks');
  }

  function polishWorkspace(){
    if(path!=='/settings')return;
    for(const row of document.querySelectorAll('#systemRows > .item'))polishSemanticRow(row);
    for(const row of document.querySelectorAll('#objectRows > .item'))polishSemanticRow(row,{object:true});
    groupConnections();
    polishRefresh();
  }

  function polishAdvanced(){
    if(path!=='/settings/advanced')return;
    const objects=document.getElementById('objects');
    if(!objects)return;
    for(const summary of objects.querySelectorAll('.tree-group > summary')){
      const current=String(summary.textContent||'');
      let text=current.replace(/^Hosts & devices\b/,'Systems')
        .replace(/^Integrations\b/,'Connections')
        .replace(/^Power\b/,'Objects · UPS')
        .replace(/^Cameras\b/,'Objects · Cameras')
        .replace(/^Standalone services\b/,'Objects · Services')
        .replace(/^Other\b/,'Objects · Other');
      const group=summary.parentElement;
      const total=group?.querySelectorAll('.tree-node').length||0;
      const match=text.match(/\((\d+)\)$/);
      const roots=match?Number(match[1]):0;
      if(total>roots&&!text.includes('incl. nested'))text+=` · ${total} shown incl. nested`;
      if(current!==text)summary.textContent=text;
    }
    let index=document.getElementById('advancedSemanticIndex');
    if(!index){
      index=document.createElement('div');
      index.id='advancedSemanticIndex';
      index.className='advanced-semantic-index';
      objects.insertAdjacentElement('beforebegin',index);
    }
    const kinds=[...objects.querySelectorAll('.object-button span')].map(node=>String(node.textContent||'').split(' · ')[0].trim().toLowerCase());
    const systems=kinds.filter(kind=>['host','appliance','network_device'].includes(kind)).length;
    const connections=kinds.filter(kind=>kind==='integration').length;
    const ups=kinds.filter(kind=>kind==='ups').length;
    const cameras=kinds.filter(kind=>kind==='camera'||kind==='cameras').length;
    const otherObjects=Math.max(0,kinds.length-systems-connections);
    const indexText=`Systems ${systems} · Connections ${connections} · Objects ${otherObjects} (UPS ${ups}, Cameras ${cameras}) · select any item to inspect Abilities / Metrics`;
    if(index.textContent!==indexText)index.textContent=indexText;
    for(const heading of document.querySelectorAll('#editor h3')){
      if(heading.textContent.trim()==='Capabilities & providers')heading.textContent='Abilities / Metrics';
    }
  }

  function polishDiscovery(){
    if(path!=='/settings/discover')return;
    for(const row of document.querySelectorAll('#results .candidate')){
      if(row.querySelector('.already-monitored-hint'))continue;
      const choose=row.querySelector('input[type=checkbox][data-id]');
      if(!choose?.disabled)continue;
      const candidateId=choose.dataset.id;
      const item=(typeof candidates!=='undefined'&&Array.isArray(candidates))
        ?candidates.find(candidate=>candidate.candidate_id===candidateId)
        :null;
      const explicit=Array.isArray(item?.already_monitored_via)?item.already_monitored_via.filter(Boolean):[];
      const inferred=sourceFromText(row.textContent);
      const evidence=row.querySelector('.wide')||row.lastElementChild;
      if(!evidence)continue;
      const note=document.createElement('div');
      note.className='already-monitored-hint';
      note.textContent=explicit.length
        ?`Already monitored via ${explicit.join(' + ')}`
        :inferred?`Already monitored via ${inferred}`:'Already represented in configured monitoring';
      evidence.append(note);
    }
  }

  async function loadCredentialProjection(){
    if(credentialProjection)return credentialProjection;
    if(!credentialFetch){
      credentialFetch=fetch('/api/v2/config/appliance/credentials',{headers:{Accept:'application/json'}})
        .then(async response=>{
          if(!response.ok)throw new Error(`credential inventory HTTP ${response.status}`);
          const payload=await response.json();
          credentialProjection=new Map((payload.credentials||[]).map(item=>[String(item.id),item]));
          return credentialProjection;
        })
        .catch(()=>null)
        .finally(()=>{credentialFetch=null;});
    }
    return credentialFetch;
  }

  async function polishCredentialBundles(){
    if(path!=='/settings/appliance')return;
    const root=document.getElementById('credentials');
    if(!root||root.querySelector('[data-followup-credential-bundle]'))return;
    const rows=[...root.children].filter(node=>node.classList?.contains('credential'));
    if(rows.length<2)return;
    const projection=await loadCredentialProjection();
    if(!projection)return;
    const grouped=new Map();
    for(const row of rows){
      const item=projection.get(String(row.dataset.credentialId||''));
      const group=item?.logical_group;
      if(!group||Number(group.field_count||0)<2)continue;
      if(!grouped.has(group.id))grouped.set(group.id,{group,entries:[]});
      grouped.get(group.id).entries.push({row,item});
    }
    for(const {group,entries} of grouped.values()){
      if(entries.length<2)continue;
      const first=entries[0].row;
      const bundle=document.createElement('section');
      bundle.className='credential-bundle';
      bundle.dataset.followupCredentialBundle=group.id;
      bundle.setAttribute('data-followup-credential-bundle','true');
      const head=document.createElement('div');
      head.className='credential-bundle-head';
      const identity=document.createElement('div');
      const title=document.createElement('div');
      title.className='credential-bundle-title';
      title.textContent=group.title||'MonitorBox credential';
      const used=document.createElement('div');
      used.className='credential-bundle-used';
      const uses=Array.isArray(group.used_for)?group.used_for.filter(Boolean):[];
      used.textContent=uses.length?`Used for: ${uses.join(' · ')}`:'Protected Connection credential';
      identity.append(title,used);
      head.append(identity);
      const fields=document.createElement('div');
      fields.className='credential-bundle-fields';
      bundle.append(head,fields);
      root.insertBefore(bundle,first);
      for(const {row,item} of entries){
        const fieldTitle=row.querySelector('.credential-title');
        const fieldKind=row.querySelector('.credential-kind');
        if(fieldTitle)fieldTitle.textContent=item.logical_group?.field_label||item.kind||'Credential field';
        if(fieldKind)fieldKind.textContent='Protected field';
        fields.append(row);
      }
    }
  }

  function polishRecovery(){
    if(path!=='/settings/recovery')return;
    const nextTitle=document.title.replace('MonitorBox Recovery','MonitorBox Backup & Restore');
    if(document.title!==nextTitle)document.title=nextTitle;
    const heading=document.querySelector('.top h1');
    if(heading?.textContent.trim()==='Recovery')heading.textContent='Backup & Restore';
  }

  function polish(){
    scheduled=false;
    styleOnce();
    polishWorkspace();
    polishAdvanced();
    polishDiscovery();
    polishCredentialBundles();
    polishRecovery();
  }
  function schedule(){
    if(scheduled)return;
    scheduled=true;
    queueMicrotask(polish);
  }

  const observer=new MutationObserver(schedule);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener('monitorbox-workspace-authenticated',schedule);
  const reloadCredentials=document.getElementById('reloadCredentials');
  reloadCredentials?.addEventListener('click',()=>{credentialProjection=null;setTimeout(schedule,100)});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});
  else schedule();
})();
