// #220: keep semantic Network children provider-blind.
// Provider modules may enrich or remove these objects, but presentation eligibility
// must not depend on a particular adapter's metadata contract.
parityNetworkChildren=function(site){
  return parityObjects(site)
    .filter(object=>object?.kind==='network_device'&&object.retired!==true)
    .sort((a,b)=>stateRank(b.state)-stateRank(a.state)||String(a.label).localeCompare(String(b.label)));
};
