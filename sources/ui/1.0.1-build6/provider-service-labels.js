// UI 1.0.1 build 6 presentation polish over the provider-backed hierarchy.
// Prefer the canonical application label for a Compose parent when exactly one
// canonical service participates; otherwise preserve provider project identity.
const providerHierarchyBuild6BaseComposeProvenance=serviceComposeProvenance;
const providerHierarchyBuild6BasePresentationEntries=servicePresentationEntries;

serviceComposeProvenance=function(service){
  const provenance=providerHierarchyBuild6BaseComposeProvenance(service);
  const workload=service?._provider_workload;
  if(provenance&&workload&&typeof workload==='object'){
    provenance.environmentLabel=String(
      workload.environment_name||workload.environment||provenance.environmentLabel||provenance.environmentKey
    ).trim()||provenance.environmentKey;
  }
  return provenance;
};

function providerStackDisplayBase(entry){
  const canonical=entry.group.services.filter(service=>service.kind==='service');
  if(canonical.length===1&&String(canonical[0].label||'').trim()){
    return String(canonical[0].label).trim();
  }
  return String(entry.group.project||entry.label||'Docker stack').trim()||'Docker stack';
}

servicePresentationEntries=function(services){
  const entries=providerHierarchyBuild6BasePresentationEntries(services);
  const stacks=entries.filter(entry=>entry.kind==='stack');
  const preferred=new Map();
  const counts=new Map();
  for(const entry of stacks){
    const label=providerStackDisplayBase(entry);
    preferred.set(entry,label);
    const key=label.toLocaleLowerCase();
    counts.set(key,(counts.get(key)||0)+1);
  }
  for(const entry of stacks){
    const label=preferred.get(entry);
    const duplicate=(counts.get(label.toLocaleLowerCase())||0)>1;
    entry.label=duplicate?`${label} · ${entry.group.environmentLabel}`:label;
  }
  return entries.sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
};
