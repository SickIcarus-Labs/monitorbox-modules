'use strict';

// UI44: compact inline readings for ordinary cards, grouped rows for custom
// cards, and the same viewer-aware 1 Hz feed used by the accepted live graphs.
// Canonical health, object drill-downs and historical configuration are untouched.
(()=>{
  const registry=globalThis.MonitorBoxCardItems;
  const layout=globalThis.MonitorBoxCardLayout;
  if(!registry||!layout)throw Error('Dashboard composer runtime is missing');
  const previous=parityCoreCard;
  const text=value=>esc(String(value==null?'':value));
  const states=['healthy','degraded','failed','unknown','paused','disabled'];
  const knownState=value=>states.includes(value)?value:'unknown';
  const number=value=>new Intl.NumberFormat(undefined,{
    maximumFractionDigits:Math.abs(value)>=10?1:2,
  }).format(value);
  function quantity(value,unit){
    if(!Number.isFinite(value))return '—';
    const u=String(unit||'').trim();
    if(u==='%'||u==='percent')return number(value)+'%';
    if(u==='KiB'||u==='kib')return number(value/(1024*1024))+' GiB';
    if(u==='MiB')return number(value/1024)+' GiB';
    if(u==='B'||u==='bytes'){
      if(Math.abs(value)>=1024**4)return number(value/1024**4)+' TiB';
      if(Math.abs(value)>=1024**3)return number(value/1024**3)+' GiB';
      if(Math.abs(value)>=1024**2)return number(value/1024**2)+' MiB';
      if(Math.abs(value)>=1024)return number(value/1024)+' KiB';
      return number(value)+' B';
    }
    if(u==='bit/s'){
      const scale=['bit/s','Kbit/s','Mbit/s','Gbit/s','Tbit/s'];
      let n=value,index=0;
      while(Math.abs(n)>=1000&&index<scale.length-1){n/=1000;index++;}
      return number(n)+' '+scale[index];
    }
    return number(value)+(u?' '+u:'');
  }
  function labelFor(item){
    let label=String(item.label||'').replace(/[_.-]/g,' ').replace(/\s+/g,' ').trim();
    const source=String(item.sourceLabel||'');
    if(label.toLowerCase().startsWith(source.toLowerCase())&&
        /^[\s·:–-]/.test(label.slice(source.length)))
      label=label.slice(source.length).replace(/^[\s·:–-]+/,'');
    label=label.replace(/\s*·\s*(live|status)$/i,'').trim();
    const key=String(item.metricKey||'').toLowerCase();
    if(key==='@derived.cpu_used_percent')return 'CPU utilization';
    if(key==='@derived.memory_used_percent')return 'Memory utilization';
    if(/(?:^|[._ ])cpu[._ ]system[._ ]percent$/.test(key))return 'CPU (system)';
    if(/(?:^|[._ ])cpu[._ ](usage|used|total)[._ ]percent$/.test(key))
      return 'CPU';
    if(/memory[._ ]available[._ ]kib$/.test(key))return 'Available memory';
    if(/memory[._ ]used[._ ]percent$/.test(key))return 'Memory used';
    if(item.liveKind==='counter_pair')
      return /eth|nic|interface|enp|bond/i.test(label)?'Ethernet throughput':
        label.replace(/\s*·\s*throughput$/i,' throughput');
    if(/ethernet throughput/i.test(label))return 'Ethernet throughput';
    if(item.type==='check'&&/eth|network|interface|traffic/i.test(label))
      return label.replace(/\s*stats?\b/i,'')+' health';
    return label||'Measurement';
  }
  function reading(item){
    if(!item.available){
      const age=item.sampleAgeSeconds;
      return {value:item.unavailableReason||'Unavailable',
        detail:Number.isFinite(age)?'Last live sample '+Math.round(age)+' s ago':'',
        meta:item.type==='live'?'LIVE · delayed':'Unavailable'};
    }
    if(item.liveKind==='counter_pair'){
      const traffic='↓ '+quantity(item.rx,'bit/s')+' · ↑ '+quantity(item.tx,'bit/s');
      if(item.value!==null&&Number.isFinite(item.value)){
        const basis=item.basis==='link'?'of reported link speed':
          'of configured graph maximum';
        return {value:quantity(item.value,'%'),detail:traffic+' · '+basis,meta:'LIVE'};
      }
      return {value:traffic,detail:'Link capacity unavailable',meta:'LIVE'};
    }
    if(item.type==='metric'||item.liveKind==='gauge')
      return {value:quantity(item.value,item.unit),
        detail:item.fallback?'Live source delayed · using monitored state':'',
        meta:item.fallback?'STATE FALLBACK':item.liveKind?'LIVE':''};
    if(item.type==='check'&&/eth|network|interface|traffic/i.test(item.label))
      return {value:knownState(item.state).replace(/^./,s=>s.toUpperCase()),
        detail:'No matching live throughput series',meta:'Health only'};
    return {value:knownState(item.state).replace(/^./,s=>s.toUpperCase()),
      detail:'',meta:''};
  }
  function row(site,selection,index,object,custom=false){
    const item=registry.display(site,selection.key,index);
    // Built-in cards use low-profile native rows even for previously saved
    // tile selections. Custom-card tiles remain a deliberate distinct mode.
    const selected=selection.mode==='value'?'value':
      selection.mode==='list'?'list':'tile';
    const mode=custom?selected:selected==='tile'?'native-tile':selected;
    const data=reading(item),available=item.available;
    const kind=available?knownState(item.state):'unknown';
    const sameSource=object&&!custom&&item.sourceLabel===object.label;
    const drill=item.drilldownObjectId&&
      (site.objects||[]).some(obj=>obj.id===item.drilldownObjectId);
    // Only custom mixed-source cards retain per-source buttons. Every
    // ordinary host/family card is one accessible target for its usual drawer.
    const tag=custom&&drill?'button':'div';
    const action=custom&&drill?' type="button" data-mb-source-site="'+text(site.id)+
      '" data-mb-source-object="'+text(item.drilldownObjectId)+'"':'';
    return '<'+tag+' class="mb-card-item mb-item-mode-'+mode+' '+kind+
      (available?'':' unavailable')+'" data-mb-composer-site="'+text(site.id)+
      '" data-mb-composer-key="'+text(selection.key)+'"'+action+'>'+
      (sameSource?'':'<span class="mb-card-item-source">'+text(item.sourceLabel)+'</span>')+
      '<span class="mb-card-item-label">'+text(labelFor(item))+'</span>'+
      '<strong class="mb-card-item-value">'+text(data.value)+'</strong>'+
      '<small class="mb-card-item-detail"'+(data.detail?'':' hidden')+'>'+
        text(data.detail)+'</small>'+
      '<small class="mb-card-item-meta">'+text(data.meta)+'</small>'+
      '</'+tag+'>';
  }
  function contents(site,pref,object,custom){
    const selections=Array.isArray(pref?.items)?pref.items:[];
    if(!selections.length)return '';
    const index=registry.catalog(site).items;
    if(!custom){
      const showLive=selections.some(s=>registry.parseKey(s.key)?.[2]==='live');
      const showState=selections.some(s=>registry.parseKey(s.key)?.[2]==='metric');
      const timing=[showLive?'LIVE: 1 s when producer responds':'',
        showState?'State: ~15 s':''].filter(Boolean).join(' · ');
      return '<div class="mb-card-items mb-card-native" aria-label="Selected monitored readings">'+
        selections.map(item=>row(site,item,index,object,false)).join('')+
        (timing?'<p class="mb-card-timing">'+text(timing)+'</p>':'')+'</div>';
    }
    // Preserve user-selected order: only adjacent identical source references
    // share a heading; never reorder the persisted snapshot.
    let previousSource='',html='';
    const distinct=new Set(selections.map(s=>registry.display(site,s.key,index).sourceLabel));
    for(const selection of selections){
      const item=registry.display(site,selection.key,index);
      const source=String(item.sourceLabel||'Other');
      if(source!==previousSource&&distinct.size>1)
        html+='<div class="mb-card-source-heading">'+text(source)+'</div>';
      previousSource=source;
      html+=row(site,selection,index,object,true);
    }
    return '<div class="mb-card-items mb-custom-readings" aria-label="Selected monitored readings">'+html+'</div>';
  }
  function refreshLiveRows(){
    if(document.hidden||!app.state)return;
    registry.setLiveSeries(app.liveTelemetry);
    const sites=new Map((app.state.sites||[]).map(site=>[site.id,site]));
    const indexes=new Map();
    document.querySelectorAll('[data-mb-composer-key]').forEach(node=>{
      const site=sites.get(node.getAttribute('data-mb-composer-site'));
      if(!site)return;
      if(!indexes.has(site.id))indexes.set(site.id,registry.catalog(site).items);
      const item=registry.display(site,node.getAttribute('data-mb-composer-key'),
        indexes.get(site.id));
      const data=reading(item);
      node.classList.remove(...states,'unavailable');
      node.classList.add(item.available?knownState(item.state):'unknown');
      if(!item.available)node.classList.add('unavailable');
      const label=node.querySelector('.mb-card-item-label');
      if(label)label.textContent=labelFor(item);
      const value=node.querySelector('.mb-card-item-value');
      if(value)value.textContent=data.value;
      const detail=node.querySelector('.mb-card-item-detail');
      if(detail){detail.textContent=data.detail;detail.hidden=!data.detail;}
      const meta=node.querySelector('.mb-card-item-meta');
      if(meta)meta.textContent=data.meta;
    });
  }

  // UI52: schema-v5 native content is rendered HERE from the same explicit
  // card definition used by the editor. No v1 family renderer is consulted.
  const metric=(object,key)=>{
    for(const component of object?.components||[]){
      const value=component?.metrics?.[key];
      if(Number.isFinite(value))return Number(value);
    }
    return null;
  };
  const chip=value=>{
    const state=knownState(value);
    return '<span class="parity-state '+text(state)+'"><i></i>'+
      text(stateLabel(state))+'</span>';
  };
  const memberList=(site,pref)=>{
    const byId=new Map((site.objects||[]).map(o=>[String(o.id),o]));
    return (pref.member_ids||[]).map(id=>{
      const object=byId.get(id);
      return object&&object.retired!==true?object:
        {id,label:id,state:'unknown',summary:'Source currently unavailable'};
    });
  };
  function nativeContents(site,object,pref){
    const family=String(object.family||object.id||'');
    const sections=new Set(pref.native_sections||[]);
    const members=memberList(site,pref);
    let html='';
    if(sections.has('camera_counts')){
      const actual=(site.objects||[]).filter(o=>o.kind==='camera'&&o.retired!==true);
      const counts=object.camera_counts||{};
      const expected=Number.isFinite(counts.expected)?counts.expected:actual.length;
      const healthy=Number.isFinite(counts.healthy)?counts.healthy:
        actual.filter(o=>o.state==='healthy').length;
      html+='<div class="mb-native-camera-total"><strong>'+healthy+' / '+
        expected+'</strong><small>cameras healthy across the site</small></div>';
    }
    if(sections.has('diagnosis')){
      const diag=object.diagnosis||{};
      const wan=String(diag.wan_path||'unknown');
      const dns=String(diag.dns_resolution||'unknown');
      html+='<div class="mb-native-diagnosis" aria-label="Internet diagnosis">'+
        '<span>WAN <b>'+text(wan)+'</b></span>'+
        '<span>DNS <b>'+text(dns)+'</b></span></div>';
      // Canonical Core supplies the diagnosis; no frontend health inference.
      html+='<span class="parity-card-copy">'+text(object.summary||'No diagnosis yet')+'</span>';
    }
    if(sections.has('status')){
      html+='<span class="parity-card-copy">'+
        text(object.summary||'Monitoring state not available')+'</span>';
    }
    if(sections.has('members')){
      const power=family==='power',camera=family==='cameras';
      html+='<div class="mb-native-members" aria-label="Selected monitored members">';
      for(const m of members){
        const source=(m.components||[]).map(c=>c.metadata||{})
          .find(x=>x.power_source||x['ups.status'])||{};
        if(power){
          const charge=metric(m,'battery.charge'),runtime=metric(m,'battery.runtime'),
            load=metric(m,'ups.load'),voltage=metric(m,'input.voltage');
          const sourceLabel=source.power_source==='utility'?'Utility':
            source.power_source==='battery'?'On battery':'Source unknown';
          const detail=[sourceLabel,source['ups.status'],
            Number.isFinite(load)?Math.round(load)+'% load':null,
            Number.isFinite(voltage)?Math.round(voltage)+' V':null]
            .filter(Boolean).join(' · ');
          const telemetry=[Number.isFinite(charge)?Math.round(charge)+'%':null,
            Number.isFinite(runtime)?Math.round(runtime/60)+' min':null]
            .filter(Boolean).join(' · ')||'—';
          html+='<span class="mb-native-member mb-native-power-row" data-mb-member="'+
            text(m.id)+'"><span><b>'+text(m.label||m.id)+'</b>'+
            '<small>'+text(detail)+'</small></span><strong>'+text(telemetry)+'</strong></span>';
        }else{
          html+='<span class="mb-native-member" data-mb-member="'+text(m.id)+'">'+
            (camera?chip(m.state):'')+
            '<b>'+text(m.label||m.id)+'</b>'+
            (camera?'':chip(m.state))+'</span>';
        }
      }
      html+='</div>';
      if(!members.length)
        html+='<span class="parity-card-copy">No members selected</span>';
    }
    return html;
  }
  function modernCard(site,object,pref,custom){
    const state=knownState(object.state),body=contents(site,pref,object,custom);
    const title=text(pref.title||object.label||'Monitoring card');
    const key=text(object.id);
    const native=nativeContents(site,object,pref);
    const compact=pref.compact===true?' mb-card-compact':'';
    return '<button type="button" class="mb-card-shell mb-card-v5 '+text(state)+
      '" data-site="'+text(site.id)+'" data-object="'+key+'">'+
      '<div class="parity-card '+text(state)+compact+'">'+
      '<span class="parity-card-head"><strong>'+title+'</strong>'+chip(state)+'</span>'+
      native+'</div>'+body+'</button>';
  }

  parityCoreCard=function composedCard(site,object){
    registry.setLiveSeries(app.liveTelemetry);
    const custom=object.kind==='ui_custom_card';
    const key=custom?String(object.id):object.kind==='dashboard_card'
      ?'family:'+String(object.family||object.id)
      :'host:'+String(object.id);
    const pref=layout.displayFor(site,key);
    if(!custom&&layout.isModern(site,key)&&pref)
      return modernCard(site,object,pref,false);
    // Only old v1–v4 snapshots retain legacy rendering. New generated v5
    // cards never call parityCoreCard(v1) to choose their contents.
    if(!custom&&(!pref||!pref.items?.length))return previous(site,object);
    const body=contents(site,pref,object,custom);
    if(custom){
      const title=text(pref?.title||object.label||'Custom card');
      return '<article class="parity-card mb-custom-card" data-mb-custom-card-id="'+
        text(object.id)+'" data-site="'+text(site.id)+'">'+
        '<span class="parity-card-head"><strong>'+title+
        '</strong><span class="mb-card-display-label">Display only</span></span>'+
        (body||'<p class="mb-card-item-empty">Add an item in Dashboard → Cards.</p>')+
        '</article>';
    }
    // Reuse the accepted canonical card's content and state, but make its
    // entire composed surface ONE native button. Its data-object is on the
    // outer button only, so existing bindCards opens exactly one drawer.
    const canonical=previous(site,object)
      .replace(/^<button\b/,'<div').replace(/<\/button>$/,'</div>')
      .replace(/\sdata-site="[^"]*"/,'').replace(/\sdata-object="[^"]*"/,'');
    return '<button type="button" class="mb-card-shell" data-site="'+
      text(site.id)+'" data-object="'+text(object.id)+'">'+
      canonical+body+'</button>';
  };

  // Row-major admission retains the original first-row intent. Later cards
  // flow into the shortest independent column so one expanded host never
  // forces adjacent Network/Cameras/Power panels below all its 24 readings.
  function columnCount(){
    if(typeof window==='undefined'||typeof window.matchMedia!=='function')return 3;
    return window.matchMedia('(max-width:650px)').matches?1:
      window.matchMedia('(max-width:980px)').matches?2:3;
  }
  // UI52: pack on the browser's measured card height (same CSS as Arrange).
  // Cache by structural card signature and column width: 1-Hz samples can
  // change the numbers but cannot reshuffle columns while being viewed.
  const heightCache=new Map();
  function cardKey(site,object,width){
    const kind=object.kind==='dashboard_card'?'family:'+
      String(object.family||object.id):object.kind==='ui_custom_card'
      ?String(object.id):'host:'+String(object.id);
    const saved=layout.cardRow(site,kind);
    return JSON.stringify([site.id,kind,Math.round(width),saved?.presentation||null]);
  }
  function measuredHeight(site,object,html,columnWidth){
    if(typeof document==='undefined')return 100;
    const key=cardKey(site,object,columnWidth);
    if(heightCache.has(key))return heightCache.get(key);
    const probe=document.createElement('div');
    probe.className='mb-card-column';
    probe.style.cssText='position:absolute;visibility:hidden;pointer-events:none;'+
      'left:-100000px;top:0;width:'+columnWidth+'px;z-index:-1';
    probe.innerHTML=html;
    document.body.append(probe);
    const box=probe.firstElementChild?.getBoundingClientRect();
    const height=Number.isFinite(box?.height)&&box.height>0?box.height:100;
    probe.remove();
    if(heightCache.size>512)heightCache.clear();
    heightCache.set(key,height);
    return height;
  }
  parityCoreMarkup=function composedMasonry(){
    const sites=app.state?.sites||[],multi=sites.length>1;
    const columns=columnCount();
    // Capability selection must see the same advertised live catalogue
    // used by selected readings, not the state-only Core projection.
    registry.setLiveSeries(app.liveTelemetry);
    const grid=document.querySelector('#core-grid');
    const totalWidth=grid?.getBoundingClientRect().width||1200;
    const columnWidth=Math.max(175,(totalWidth-9*(columns-1))/columns);
    return sites.map(site=>{
      const groups=Array.from({length:columns},()=>[]);
      const heights=Array(columns).fill(0);
      const spatial=layout.spatialFor(site);
      if(spatial){
        for(const entry of [...spatial].sort((a,b)=>a.column-b.column)){
          const column=Math.min(entry.column,columns-1);
          groups[column].push(parityCoreCard(site,entry.object));
        }
      }else{
        // First row admits one card per lane, subsequent cards go to the
        // shortest *actually measured* natural-height column. No old
        // Network/Power/Cameras special-case estimates.
        parityCoreObjects(site).forEach((object,index)=>{
          const html=parityCoreCard(site,object);
          const column=index<columns?index:heights.indexOf(Math.min(...heights));
          groups[column].push(html);
          heights[column]+=measuredHeight(site,object,html,columnWidth)+9;
        });
      }
      const heading=multi?'<div class="parity-site-label">'+text(site.label)+'</div>':'';
      return '<section class="mb-masonry-site" data-mb-site="'+text(site.id)+'">'+
        heading+'<div class="mb-card-columns" data-mb-columns="'+columns+'">'+
        groups.map((items,index)=>'<div class="mb-card-column" data-mb-column="'+
          index+'">'+items.join('')+'</div>').join('')+'</div></section>';
    }).join('');
  };
  if(typeof window!=='undefined'&&typeof window.addEventListener==='function'){
    let previousColumns=columnCount();
    window.addEventListener('resize',()=>{
      const next=columnCount();
      if(next===previousColumns)return;
      previousColumns=next;
      layout.refreshGrid();
    });
  }
  document.addEventListener('click',event=>{
    const node=event.target.closest?.('[data-mb-source-object]');
    if(!node)return;
    const siteId=node.getAttribute('data-mb-source-site');
    const objectId=node.getAttribute('data-mb-source-object');
    const site=(app.state?.sites||[]).find(s=>s.id===siteId);
    if(!site?.objects?.some(o=>o.id===objectId))return;
    openDrawer(siteId,objectId);
  });
  // /api/v2/state refreshes every 15s; /api/v2/live is already polled
  // each second by the existing graph renderer. Repaint only the readings,
  // never rebuild the card or initiate another network request.
  document.addEventListener('DOMContentLoaded',()=>refreshLiveRows());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshLiveRows();});
  setInterval(refreshLiveRows,1000);
  function visibleLiveDetails(){
    if(document.hidden||!app.state)return [];
    const sites=new Map((app.state.sites||[]).map(site=>[
      site.id,new Set((site.objects||[]).map(obj=>obj.id)),
    ]));
    const details=new Set();
    // The dashboard already renders only selected items. Do not activate
    // unrelated gauges merely because an operator has opened the homepage.
    document.querySelectorAll('[data-mb-composer-key]').forEach(node=>{
      const parts=registry.parseKey(node.getAttribute('data-mb-composer-key'));
      if(parts?.[0]!=='object'||parts[2]!=='live')return;
      const site=node.getAttribute('data-mb-composer-site');
      const object=parts[1];
      if(sites.get(site)?.has(object))details.add(site+'/'+object);
    });
    return [...details].slice(0,32);
  }
  globalThis.MonitorBoxCardComposer=Object.freeze({refresh:refreshLiveRows,
    quantity,reading,visibleLiveDetails});
})();