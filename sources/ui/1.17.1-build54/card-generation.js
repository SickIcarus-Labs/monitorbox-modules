'use strict';

// UI52: one provider-neutral *current capability -> card definition* projector.
// The first dashboard and explicit Reset both invoke generate(site, catalog).
// Never read historical card preferences, v1 front_page hints, or site names.
(()=>{
  const BUILTIN=['internet','network','cameras','power'];
  const RESERVED=new Set(['monitor','monitorbox']);
  const text=value=>String(value??'').toLowerCase();
  const stable=(a,b)=>String(a.label||a.id).localeCompare(String(b.label||b.id))||
    String(a.id).localeCompare(String(b.id));
  const eligibleHost=object=>{
    if(!object||object.retired===true||RESERVED.has(String(object.id))||
      object.explicit_front_page===false)return false;
    if(object.system_role==='site_gateway'&&
      ['host','network_device'].includes(object.kind))return true;
    return object.kind==='host'&&object.homepage_origin==='operator';
  };
  function members(site,family,card=null){
    const objects=(site?.objects||[]).filter(o=>o&&o.retired!==true);
    let pool;
    if(family==='network'){
      // A remote site owns a separate site/dashboard. Old UniFi front_page
      // metadata must NOT decide either candidate eligibility or visibility.
      pool=objects.filter(o=>o.kind==='network_device');
    }else if(family==='cameras')pool=objects.filter(o=>o.kind==='camera');
    else if(family==='power')pool=objects.filter(o=>o.kind==='ups');
    else{
      const present=new Set((card?.member_object_ids||[]).map(String));
      pool=objects.filter(o=>present.has(String(o.id)));
    }
    return pool.sort(stable).map(o=>({id:String(o.id),
      label:String(o.label||o.id),kind:String(o.kind),state:String(o.state||'unknown')}));
  }
  function sections(family){
    if(family==='internet')return ['diagnosis'];
    if(family==='cameras')return ['camera_counts','members'];
    if(family==='network'||family==='power')return ['members'];
    return ['status','members']; // provider-neutral third-party families
  }
  function available(site){
    const result=[],seen=new Set();
    for(const object of (site?.objects||[])){
      if(!eligibleHost(object))continue;
      const id='host:'+object.id;
      if(seen.has(id))continue;
      seen.add(id);
      result.push({id,kind:'host',label:object.label||object.id,value:object});
    }
    const families=new Map();
    for(const card of (site?.cards||[])){
      if(card?.kind!=='dashboard_card'||!card.family||card.family==='services')continue;
      if(!families.has(card.family))families.set(card.family,card);
    }
    const ordered=[...BUILTIN.filter(f=>families.has(f)),
      ...[...families.keys()].filter(f=>!BUILTIN.includes(f)).sort()];
    for(const family of ordered){
      const card=families.get(family);
      result.push({id:'family:'+family,kind:'family',
        label:card.label||family,value:card});
    }
    return result;
  }
  function liveCandidates(site,catalog){
    const groups=catalog?.groups||[];
    return groups.flatMap(g=>g.sources||[]).flatMap(source=>source.items||[])
      .filter(item=>item.type==='live'&&item.sourceKind==='object');
  }
  function liveDefaults(site,object,catalog){
    const list=liveCandidates(site,catalog).filter(x=>x.sourceId===object.id)
      .sort((a,b)=>String(a.key).localeCompare(String(b.key)));
    const pick=(pred)=>list.filter(pred)[0]||null;
    const name=item=>text([item.label,item.metricKey].join(' ')).replace(/[_./-]+/g,' ');
    const isPercent=item=>['%','percent'].includes(text(item.unit));
    const cpu=pick(x=>isPercent(x)&&/\bcpu\b/.test(name(x))&&
      /(usage|utilization|used|total)/.test(name(x))&&!/\b(user|system|idle)\b/.test(name(x)))||
      pick(x=>isPercent(x)&&/\bcpu\b/.test(name(x))&&!/\b(user|system|idle)\b/.test(name(x)));
    const mem=pick(x=>/\b(memory|ram|mem)\b/.test(name(x))&&
      /\b(used|usage|utilization)\b/.test(name(x))&&
      ['B','bytes','GiB','MiB','KiB'].includes(String(x.unit)))||
      pick(x=>/\b(memory|ram|mem)\b/.test(name(x))&&
        /\b(used|usage|utilization)\b/.test(name(x))&&isPercent(x));
    const throughput=pick(x=>x.liveKind==='counter_pair'||
      (/ethernet|nic|network|throughput/.test(name(x))&&x.type==='live'&&
        x.unit==='bit/s'));
    return {cpu,mem,throughput};
  }
  function stateDefaults(object,catalog){
    // Fallbacks use the validated observed-value source catalogue, never
    // invent a percentage from cumulative counters or link speed.
    const entries=[...(catalog?.groups||[])].flatMap(g=>g.sources||[])
      .flatMap(s=>s.items||[]).filter(x=>x.sourceKind==='object'&&
        x.sourceId===object.id&&x.type==='metric')
      .sort((a,b)=>String(a.key).localeCompare(String(b.key)));
    const named=x=>text(x.metricKey).replace(/[_./-]+/g,' ');
    const value=x=>{
      if(x.metricKey?.startsWith('@derived.'))return true;
      const component=(object.components||[]).find(c=>c.id===x.componentId);
      return Number.isFinite(component?.metrics?.[x.metricKey]);
    };
    const storagePattern=/(?:disk|storage|filesystem|fs|pool|volume).*(?:used|free|available)/;
    return {
      cpu:entries.find(x=>x.metricKey==='@derived.cpu_used_percent'&&value(x))||
        entries.find(x=>/\bcpu\b.*(?:used|usage|utilization)/.test(named(x))&&x.unit==='%'&&value(x))||null,
      mem:entries.find(x=>/\b(memory|ram|mem)\b.*(?:used|usage)/.test(named(x))&&
        ['B','bytes','GiB','MiB','KiB'].includes(String(x.unit))&&value(x))||
        entries.find(x=>x.metricKey==='@derived.memory_used_percent'&&value(x))||
        entries.find(x=>/\b(memory|ram|mem)\b.*(?:used|usage)/.test(named(x))&&x.unit==='%'&&value(x))||null,
      storage:entries.find(x=>storagePattern.test(named(x))&&value(x))||null,
      network:entries.find(x=>/\b(eth|ethernet|nic|network|interface|link)\b.*(?:used|usage|utilization)/.test(named(x))&&x.unit==='%'&&value(x))||null,
    };
  }
  function hostItems(site,object,catalog){
    const live=liveDefaults(site,object,catalog),state=stateDefaults(object,catalog);
    const selected=[live.cpu||state.cpu,live.mem||state.mem,
      state.storage,live.throughput||state.network].filter(Boolean);
    return [...new Map(selected.map(item=>[item.key,{key:item.key,mode:'value'}])).values()].slice(0,4);
  }
  function internetItems(site,catalog){
    // The WAN series is explicitly classified as WAN by the producer, not
    // inferred from a specific host name or a random interface.
    const series=(catalog?.groups||[]).flatMap(g=>g.sources||[])
      .flatMap(s=>s.items||[]).filter(item=>item.type==='live'&&
        item.liveKind==='counter_pair'&&item.trafficSubject==='wan');
    return series.length===1?[{key:series[0].key,mode:'value'}]:[];
  }
  function generate(site,catalog){
    const rows=[];
    for(const entry of available(site)){
      const kind=entry.kind,family=kind==='family'?
        String(entry.value.family||entry.value.id):'';
      const membership=kind==='family'?members(site,family,entry.value):[];
      const items=kind==='host'?hostItems(site,entry.value,catalog):
        family==='internet'?internetItems(site,catalog):[];
      rows.push({id:entry.id,visible:true,
        presentation:{schema_version:3,
          native_sections:kind==='host'?['status']:sections(family),
          member_ids:membership.map(m=>m.id),items}});
    }
    return rows;
  }
  globalThis.MonitorBoxCardGeneration=Object.freeze({
    BUILTIN,eligibleHost,members,sections,available,hostItems,generate,
  });
})();
