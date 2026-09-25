'use strict';

// #94: One read-only source and item catalog for *every* dashboard card.
// Store stable references in opaque UI preferences, not snapshots of health.
(()=>{
  const GROUPS=Object.freeze([
    ['hosts','Hosts'],['network','Network'],['power','Power'],
    ['cameras','Cameras'],['internet','Internet'],
    ['services','Services'],['other','Other monitored sources'],
  ]);
  const KINDS={
    host:'hosts',network_device:'network',remote_site:'network',
    ups:'power',camera:'cameras',service:'services',
  };
  const LABELS=new Map(GROUPS);
  // Ephemeral Core /api/v2/live output. Do not store samples in card preferences.
  let liveSeries=[];
  function setLiveSeries(payload){
    const rows=Array.isArray(payload)?payload:payload?.series;
    liveSeries=Array.isArray(rows)?rows.filter(row=>row&&typeof row==='object'):[];
  }
  const nonEmpty=value=>typeof value==='string'&&value.length>0&&value.length<=160;
  const token=value=>nonEmpty(value)?value:null;
  const makeKey=(sourceKind,sourceId,type,componentId='',metricKey='')=>
    JSON.stringify([sourceKind,sourceId,type,componentId,metricKey]);
  function parseKey(key){
    if(typeof key!=='string'||key.length>640)return null;
    let parts;
    try{parts=JSON.parse(key);}catch{return null;}
    return Array.isArray(parts)&&parts.length===5&&
      ['object','family'].includes(parts[0])&&token(parts[1])&&
      ['status','check','metric','live'].includes(parts[2])&&
      parts.slice(3).every(v=>typeof v==='string'&&v.length<=160)
      ?parts:null;
  }
  function title(value){
    return String(value||'')
      .replace(/[_-]/g,' ').replace(/\./g,' · ').trim()||'Unnamed metric';
  }
  function numeric(value){return typeof value==='number'&&Number.isFinite(value);}
  function sourceGroup(object){
    return KINDS[String(object.kind||'')]||'other';
  }
  function catalog(site){
    const matchingLive=liveSeries.filter(row=>row.site_id===site?.id&&
      token(row.object_id)&&token(row.check_id)&&token(row.id)&&
      ['gauge','counter_pair'].includes(row.kind));
    const sources=[],items=new Map(),seenSources=new Set();
    const objects=Array.isArray(site?.objects)?site.objects:[];
    const byObject=new Map(objects.filter(o=>o&&token(o.id)&&
      o.kind!=='appliance'&&o.retired!==true)
      .map(o=>[o.id,o]));
    function insert(item){
      if(items.has(item.key))return;
      items.set(item.key,item);
    }
    function source(sourceKind,sourceId,label,group,owner,components){
      if(!token(sourceId))return;
      const identity=sourceKind+':'+sourceId;
      if(seenSources.has(identity))return;
      seenSources.add(identity);
      const result={id:identity,label:String(label||sourceId),group,
        kind:sourceKind,sourceId,items:[]};
      function append(type,componentId,metricKey,display,unit,read){
        const key=makeKey(sourceKind,sourceId,type,componentId,metricKey);
        const item={key,type,sourceKind,sourceId,componentId,metricKey,
          label:display,unit:unit||null,group,sourceLabel:result.label,
          drilldownObjectId:owner?.id||null};
        insert(item);result.items.push(item);
      }
      if(sourceKind==='object')
        append('status','','',result.label+' · status',null);
      const projectedComponents=Array.isArray(components)?components:[];
      for(const component of projectedComponents){
        if(!component||!token(component.id))continue;
        const componentLabel=String(component.label||component.id);
        append('check',component.id,'',componentLabel+' · status',null);
        const measurements=component.metrics;
        if(!measurements||typeof measurements!=='object'||Array.isArray(measurements))
          continue;
        const units=component.metric_units||component.metadata?.metric_units||{};
        for(const [metric,value] of Object.entries(measurements)){
          if(!token(metric)||!numeric(value))continue;
          const inferred=/(?:^|[._\\s])percent$/i.test(metric)?'%':
            /(?:^|[._\\s])kib$/i.test(metric)?'KiB':
            /(?:^|[._\\s])bytes$/i.test(metric)?'B':null;
          append('metric',component.id,metric,title(metric),
            typeof units[metric]==='string'?units[metric]:inferred);
        }
      }
      // The live stream has its own checked, site-scoped source identity.
      // It exposes actual rates/measurements; a network health check is NOT
      // a network utilization value.
      if(sourceKind==='object')for(const series of matchingLive){
        if(series.object_id!==sourceId)continue;
        const name=String(series.label||series.id);
        const display=series.kind==='counter_pair'
          ?name+' · throughput':name+' · live';
        append('live',series.check_id,series.id,display,
          typeof series.unit==='string'?series.unit:null);
      }
      if(result.items.length)sources.push(result);
    }
    for(const obj of objects){
      if(!obj||!token(obj.id)||obj.retired===true||obj.kind==='appliance')
        continue;
      source('object',obj.id,obj.label||obj.id,sourceGroup(obj),obj,obj.components);
    }
    // Some family checks (e.g. Internet probes) do not belong to an
    // independently projected public object. Expose them as a family source.
    for(const family of Array.isArray(site?.cards)?site.cards:[]){
      if(!family||family.kind!=='dashboard_card'||!token(family.family||family.id))
        continue;
      const id=String(family.family||family.id);
      const independent=(family.components||[]).filter(c=>
        c&&(!c.owner_object_id||!byObject.has(c.owner_object_id)));
      if(!independent.length)continue;
      const group=LABELS.has(id)?id:'other';
      source('family',id,family.label||id,group,null,independent);
    }
    const groups=GROUPS.map(([id,label])=>({
      id,label,sources:sources.filter(s=>s.group===id)
        .sort((a,b)=>a.label.localeCompare(b.label)),
    })).filter(g=>g.sources.length);
    return {groups,items};
  }
  function matchingLiveFor(site,objectId,checkId,seriesId){
    return liveSeries.find(row=>row.site_id===site?.id&&
      row.object_id===objectId&&row.check_id===checkId&&row.id===seriesId);
  }
  function liveReading(item,series){
    const points=Array.isArray(series.points)?series.points:[];
    const last=points[points.length-1];
    const age=last?Date.now()-Date.parse(last.timestamp):Infinity;
    // Active graph viewers ordinarily sample each second. If the producer
    // stops, mark the reading unavailable rather than retaining stale green.
    if(!last||!last.valid||!Number.isFinite(age)||age< -2000||age>6000)
      return {...item,available:false,state:'unknown',value:null,
        unavailableReason:age>6000?'Live sample stale':'Waiting for live sample',
        liveKind:series.kind,maximum:series.maximum};
    if(series.kind==='counter_pair'){
      const rx=Number(last.rx),tx=Number(last.tx);
      if(!Number.isFinite(rx)||!Number.isFinite(tx)||rx<0||tx<0)
        return {...item,available:false,state:'unknown',value:null,
          unavailableReason:'Invalid throughput sample'};
      const maximum=Number(series.maximum);
      const hasCapacity=Number.isFinite(maximum)&&maximum>0&&series.unit==='bit/s';
      // An Ethernet link is normally full duplex: use the busiest direction
      // relative to per-direction line speed, not rx+tx divided by one lane.
      const utilization=hasCapacity?Math.max(rx,tx)/maximum*100:null;
      return {...item,available:true,state:'healthy',value:utilization,
        unit:hasCapacity?'%':series.unit||'bit/s',liveKind:'counter_pair',
        rx,tx,maximum:hasCapacity?maximum:null,sampledAt:last.timestamp};
    }
    const value=Number(last.value);
    if(!Number.isFinite(value))
      return {...item,available:false,state:'unknown',value:null,
        unavailableReason:'Invalid live sample'};
    return {...item,available:true,state:'healthy',value,
      liveKind:'gauge',unit:series.unit||item.unit||null,
      sampledAt:last.timestamp};
  }
  function resolve(site,key,index){
    const parts=parseKey(key);
    if(!parts)return null;
    const found=(index||catalog(site).items).get(key);
    if(!found)return null;
    const [sourceKind,sourceId,type,componentId,metricKey]=parts;
    const source=sourceKind==='object'
      ?(site?.objects||[]).find(o=>o.id===sourceId)
      :(site?.cards||[]).find(c=>String(c.family||c.id)===sourceId);
    if(!source)return {...found,available:false,state:'unknown',value:null};
    if(type==='live'){
      const series=matchingLiveFor(site,sourceId,componentId,metricKey);
      if(!series)return {...found,available:false,state:'unknown',value:null,
        unavailableReason:'Live series unavailable'};
      return liveReading(found,series);
    }
    if(type==='status')
      return {...found,available:true,state:source.state||'unknown',value:null};
    const component=(source.components||[]).find(c=>c.id===componentId);
    if(!component)return {...found,available:false,state:'unknown',value:null};
    if(type==='check'){
      // Existing UI43 network-status selections acquire genuine throughput
      // only when their exact producing check advertises ONE counter series.
      // Never guess an interface when more than one series matches.
      const candidates=liveSeries.filter(row=>row.site_id===site?.id&&
        row.object_id===sourceId&&row.check_id===componentId&&
        row.kind==='counter_pair');
      if(candidates.length===1&&/eth|network|traffic|throughput|interface/i
          .test(String(component.label||component.id))){
        const live=liveReading({...found,type:'live',
          label:'Ethernet throughput'},candidates[0]);
        return {...live,key:found.key};
      }
      return {...found,available:true,state:component.state||'unknown',value:null};
    }
    const value=component.metrics?.[metricKey];
    return {...found,available:numeric(value),state:component.state||'unknown',
      value:numeric(value)?value:null};
  }
  // Resolve saved references independently of catalog membership. A missing
  // item remains visibly unavailable instead of vanishing or appearing healthy.
  function display(site,key,index){
    const found=resolve(site,key,index);
    if(found)return found;
    const parts=parseKey(key);
    const object=(site?.objects||[]).find(row=>row.id===parts?.[1]);
    return {key,type:parts?.[2]||'unknown',
      sourceLabel:object?.label||parts?.[1]||'Unavailable source',
      label:parts?.[4]||parts?.[3]||'Unavailable item',
      available:false,state:'unknown',value:null,unit:null,
      unavailableReason:parts?.[2]==='live'?'Live series unavailable':'Source unavailable',
      drilldownObjectId:object?.id||null};
  }
  globalThis.MonitorBoxCardItems=Object.freeze({
    GROUPS,makeKey,parseKey,catalog,resolve,display,setLiveSeries,
  });
})();