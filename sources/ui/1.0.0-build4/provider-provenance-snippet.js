  function safeCandidateName(value){
    const text=String(value||'').trim().replace(/\s+/g,' ');
    if(!text||text.length>160||/[\u0000-\u001f\u007f]/.test(text))return'';
    return text;
  }

  function providerProvenance(item){
    const output=[];
    const seen=new Set();
    for(const evidence of item?.evidence||[]){
      const metadata=evidence?.metadata;
      if(!metadata||typeof metadata!=='object')continue;
      const environment=safeCandidateName(metadata.environment_name||metadata.environment);
      const stack=safeCandidateName(metadata.stack_name||metadata.compose_project);
      const service=safeCandidateName(metadata.compose_service);
      const deployment=safeCandidateName(metadata.deployment_kind);
      if(!environment&&!stack&&!service&&!deployment)continue;
      const parts=[];
      if(environment)parts.push(`Environment/System · ${environment}`);
      if(stack)parts.push(`Stack · ${stack}`);
      if(service)parts.push(`Service · ${service}`);
      if(deployment&&!stack)parts.push(`Deployment · ${deployment}`);
      const text=parts.join(' · ');
      if(!text||seen.has(text))continue;
      seen.add(text);
      output.push(text);
    }
    return output;
  }

  function renderProviderProvenance(row,item){
    row.querySelectorAll('.provider-provenance').forEach(element=>element.remove());
    const evidenceCell=row.querySelector('.wide');
    if(!evidenceCell)return;
    const provenance=providerProvenance(item);
    for(const text of provenance){
      const line=document.createElement('div');
      line.className='provider-provenance muted';
      line.style.marginTop='6px';
      line.textContent=text;
      evidenceCell.append(line);
    }
  }
