# Successor first-party module requalification

Tracks [modules #114](https://github.com/SickIcarus-Labs/monitorbox-modules/issues/114), package authority [#120](https://github.com/SickIcarus-Labs/monitorbox-modules/issues/120), and the scaffold-first architecture in [MonitorBox #413](https://github.com/SickIcarus-Labs/monitorbox/issues/413).

## Verified compatibility barrier

The accepted Broad Leaf package set contains ten independently managed application modules whose immutable 2.x manifests all exclude Core 3.0.0. Those existing signed ZIPs remain valid historical 2.x artifacts and must never be relabeled, edited or re-signed as successor releases.

The successor therefore creates **new package identities** by retaining each accepted version and incrementing its independent build number. The accepted 2.x ZIP is a cryptographically pinned read-only implementation input. The successor wrapper preserves every predecessor implementation-file payload byte-for-byte, retains safe predecessor directory entries, and adds only the new successor authority members:

- `package.json`: exact successor artifact identity, Core/Module Runtime compatibility, existing module entrypoint contract and predecessor provenance;
- `portable-config.json`: exact package-owned portable configuration authority from #120.

The ten candidates are Backup/Restore, Configuration Bootstrap, HTTP, NUT, Portainer, Scrypted, SNMP, UI, UniFi and WOL.

## Compatibility claim

The first successor application-module authority declares:

- Linux architecture-neutral pure Python/application packages;
- Module Runtime API `>=1 <2`;
- Core `>=3.0.0 <4.0.0`;
- a mandatory platform dependency on `com.sickicarus.monitorbox.core >=3.0.0 <4.0.0`;
- the same module type, lifecycle policy, permissions, capability-detection declaration and executable entrypoint target as the accepted predecessor;
- the same implementation members as the predecessor, byte for byte.

This is not a version-string shortcut. The dedicated cross-repository qualification job checks the exact package bytes against the exact Core API source authority at MonitorBox PR #482 HEAD `c7532b86bb61ceb3eab34ba97b430602a4b60a82`. It imports every declared entrypoint from the generated ZIPs, exercises Core's ModuleLoader under Core 3.0.0 / Module Runtime API v1, proves the same candidates reject Core 2.7.0, and registers all seven integration modules together through Plugin API v1 to detect facet/ownership collisions.

That gate establishes **package/API compatibility only**. Network/provider behavior, full UI/Bootstrap/Backup readiness, imported Broad Leaf credentials, monitoring output and physical host-network behavior remain later integration/physical acceptance gates.

## Publication safety

The checked-in authority and normal builder currently set `release_eligible=false`. This is intentional.

The successor candidate publisher independently opens any of these ten module ZIPs before signing and requires:

1. exactly one package-owned `portable-config.json` matching the first-party authority and exact outer identity;
2. exactly one strict `package.json`;
3. `packaging_stage=successor-module-requalification`;
4. exact artifact ID/version/build agreement;
5. Core 3 / Module Runtime API v1 compatibility;
6. immutable predecessor provenance; and
7. explicit `release_eligible=true`.

Therefore the current development candidates cannot accidentally enter a signed successor catalog. Turning eligibility on is a separate reviewed step after Core3 package/runtime closure and integrated successor startup are ready.

## Transactional installation target

The target clean-install path remains one generation transaction:

1. scaffold resolves and verifies the complete signed successor package/runtime graph;
2. portable import validates/migrates the JSON through the exact selected Core and package-owned contracts;
3. exact selected application-module ZIPs are materialized into the inactive candidate state/module authority;
4. Core starts using only those exact retained package bytes;
5. UI, Bootstrap, Backup/Recovery, selected required modules and administrator authentication satisfy complete readiness;
6. only then does scaffold commit the generation.

Failure at any point leaves the previous generation intact, or on a pristine installation leaves only independent scaffold recovery active.

No file in this work changes the existing 2.x stable/beta/dev catalogs, accepted package ZIPs or Broad Leaf.
