'use strict';

(()=>{
  const editor=document.getElementById('editor');
  if(!editor)return;

  const systemKinds=new Set(['host','appliance','network_device']);
  const adapterLabel=value=>({
    icmp:'Ping',
    icmp_group:'Ping',
    snmp:'SNMP',
    http:'HTTP(S)',
    tcp:'TCP',
    dns:'DNS',
    nut:'NUT',
    portainer:'Docker / Portainer',
    scrypted:'Scrypted',
    unifi:'UniFi Network',
    host:'Local host telemetry',
  }[String(value||'').trim().toLowerCase()]||String(value||'Connection').replaceAll('_',' '));

  const credentialRoleLabel=value=>{
    const raw=String(value||'Credential').trim();
    const known={
      api_key_env:'API key',
      token_env:'API token',
      username_env:'Username',
      password_env:'Password',
      auth_password_env:'Authentication password',
      privacy_password_env:'Privacy password',
      community_env:'SNMP v2c community',
      request_header_value_env:'Request header value',
    };
    if(known[raw])return known[raw];
    if(!raw.endsWith('_env'))return raw;
    const words=raw.slice(0,-4).replaceAll('_',' ');
    return words.replace(/\bapi\b/gi,'API').replace(/\bsnmp\b/gi,'SNMP').replace(/^./,letter=>letter.toUpperCase());
  };

  function textLabel(label){
    const node=[...label.childNodes].find(item=>item.nodeType===Node.TEXT_NODE);
    return String(node?.textContent||'').trim();
  }

  function styleOnce(){
    if(document.getElementById('advancedV22PolishStyle'))return;
    const style=document.createElement('style');
    style.id='advancedV22PolishStyle';
    style.textContent=`
      .provider[data-v22-polished="true"]>.section-head>strong{font-weight:750}
      .credential-role{display:flex;flex-direction:column;gap:4px;align-self:center;min-width:0}
      .credential-role strong{font-size:12px;color:var(--text)}
      .credential-technical{grid-column:1/-1;color:var(--muted);font-size:11px}
      .credential-technical summary{cursor:pointer;user-select:none}
      .credential-technical code{display:block;overflow-wrap:anywhere;margin-top:4px;color:var(--muted)}
      .destructive-rerun-card{border-color:#673b42;background:#171218}
      .destructive-rerun-card .eyebrow{color:#f0a5ad}
      .destructive-rerun-card .button{display:inline-block;margin-top:9px;border-color:#7a3e47;color:#ffc7cd;background:#21151a}
    `;
    document.head.append(style);
  }

  function ensureCredentialMaintenanceEntry(){
    const button=document.getElementById('showSecrets');
    if(!button||button.dataset.v22CredentialMaintenance==='true')return;
    button.textContent='Manage credentials';
    button.onclick=()=>{location.href='/settings/appliance#credentials'};
    button.dataset.v22CredentialMaintenance='true';
    const card=button.closest('.card');
    const description=card?.querySelector('p.muted');
    if(description)description.textContent='Review credential associations and status, filter unused entries, replace active values at their Connection, or safely delete unreferenced active-store copies.';
  }

  function ensureDestructiveRerunEntry(){
    if(document.getElementById('destructiveRerunCard'))return;
    const nav=document.querySelector('#app > aside.nav');
    if(!nav)return;
    const card=document.createElement('div');
    card.id='destructiveRerunCard';
    card.className='card destructive-rerun-card';
    card.innerHTML=`<div class="eyebrow">Destructive appliance setup</div><h3>Re-run first-launch setup</h3><p class="muted">Build a replacement configuration from zero. MonitorBox creates a self-contained rollback snapshot first and keeps the current configuration live until Finish.</p><a class="button" href="/settings/advanced/rerun-first-launch">Re-run first-launch setup (destructive)</a>`;
    nav.append(card);
  }

  function polishOntologyNouns(){
    const configReady=typeof working!=='undefined'&&working&&typeof currentObject==='function';
    const obj=configReady?currentObject():null;
    const deleteButton=[...editor.querySelectorAll('.button.danger')].find(button=>/^Delete (?:object|system)$/i.test(button.textContent.trim()));
    if(deleteButton&&obj){
      const noun=systemKinds.has(String(obj.kind||'').toLowerCase())?'System':'Object';
      const nextLabel=`Delete ${noun}`;
      if(deleteButton.textContent.trim()!==nextLabel)deleteButton.textContent=nextLabel;
      if(deleteButton.dataset.advancedEntityNoun!==noun)deleteButton.dataset.advancedEntityNoun=noun;
    }
    for(const capability of editor.querySelectorAll('.capability')){
      const remove=capability.querySelector(':scope > .section-head > .button.danger');
      if(remove&&remove.textContent.trim()==='Remove')remove.textContent='Remove Ability';
    }
  }

  function polishProvider(provider){
    if(provider.dataset.v22Polished==='true')return;
    const capability=provider.closest('.capability');
    const capabilityTitle=String(capability?.querySelector(':scope > .section-head h4')?.textContent||'').trim();
    const head=provider.querySelector(':scope > .section-head');
    const title=head?.querySelector('strong');
    const pill=head?.querySelector('.pill');
    const adapter=String(pill?.textContent||'').trim();
    if(title)title.textContent=`Check method · ${adapterLabel(adapter)}`;

    const grid=provider.querySelector(':scope > .grid');
    const firstField=grid?.querySelector(':scope > .field');
    const input=firstField?.querySelector('input');
    if(firstField&&input&&textLabel(firstField)==='Provider label'){
      const providerLabel=String(input.value||'').trim();
      if(!providerLabel||providerLabel.localeCompare(capabilityTitle,undefined,{sensitivity:'accent'})===0){
        firstField.hidden=true;
        firstField.setAttribute('aria-hidden','true');
      }else{
        const labelNode=[...firstField.childNodes].find(item=>item.nodeType===Node.TEXT_NODE);
        if(labelNode)labelNode.textContent='Custom check-method label';
      }
    }
    provider.dataset.v22Polished='true';
  }

  function polishCredential(line){
    if(line.dataset.v22Polished==='true')return;
    const labels=[...line.querySelectorAll(':scope > label.field')];
    const envField=labels.find(label=>textLabel(label)==='Environment reference');
    const secretField=labels.find(label=>textLabel(label).endsWith(' secret ID'));
    if(!envField||!secretField)return;
    const envInput=envField.querySelector('input');
    const secretInput=secretField.querySelector('input');
    if(!envInput||!secretInput)return;

    const credentialName=credentialRoleLabel(textLabel(secretField).replace(/ secret ID$/,'')||'Credential');
    const envReference=String(envInput.value||'');
    const secretId=String(secretInput.value||'');
    envInput.disabled=true;envInput.readOnly=true;
    secretInput.disabled=true;secretInput.readOnly=true;

    const state=line.querySelector(':scope > .secret-state');
    const role=document.createElement('div');
    role.className='credential-role';
    const strong=document.createElement('strong');
    strong.textContent=credentialName;
    role.append(strong);
    if(state)role.append(state);

    const technical=document.createElement('details');
    technical.className='credential-technical';
    const summary=document.createElement('summary');
    summary.textContent='Technical identifiers';
    const env=document.createElement('code');
    env.textContent=`Environment reference · ${envReference}`;
    const secret=document.createElement('code');
    secret.textContent=`Secret ID · ${secretId}`;
    technical.append(summary,env,secret);

    envField.remove();
    secretField.remove();
    line.prepend(role);
    line.append(technical);
    line.dataset.v22Polished='true';
  }

  function polish(){
    styleOnce();
    ensureCredentialMaintenanceEntry();
    ensureDestructiveRerunEntry();
    polishOntologyNouns();
    for(const provider of editor.querySelectorAll('.provider'))polishProvider(provider);
    for(const line of editor.querySelectorAll('.secret-line'))polishCredential(line);
  }

  const observer=new MutationObserver(polish);
  observer.observe(editor,{childList:true,subtree:true});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',polish,{once:true});
  else polish();
})();
