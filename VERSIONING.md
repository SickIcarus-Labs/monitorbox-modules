# MonitorBox Module Versioning

This document is the canonical versioning policy for MonitorBox modules published through the official module repository.

## Release identity

Every module has two independent release identifiers:

- `version` — the human-meaningful semantic release version in `MAJOR.MINOR.PATCH` form.
- `build` — a monotonically increasing per-module artifact/build number used for exact provenance, diagnostics, rollback, and immutable package identity.

Example manifest identity:

```text
version: 1.4.2
build: 47
```

Operator-facing shorthand may render the same exact artifact as `v1.4.2 · build 47`; support fingerprints may render it as `1.4.2+47`.

The build number never substitutes for semantic version progression.

## Semantic version rules

### MAJOR

Increment `MAJOR` for an intentionally incompatible or breaking module change, including changes such as:

- incompatible public module/facet/API behavior;
- incompatible configuration or durable-state contract requiring migration;
- removal or incompatible change of exported capabilities consumed by other modules or Core;
- a fundamental module-boundary redesign that makes the prior contract unsafe to treat as compatible.

Example: `1.8.4 -> 2.0.0`.

### MINOR

Increment `MINOR` for a backwards-compatible new capability or material feature.

Examples include:

- a provider module gains a new independently useful monitoring capability;
- an existing module gains a new discovery/action/detail facet;
- the UI module gains a substantial new operator workflow or screen;
- a module adds new supported behavior without intentionally breaking existing installations.

Example: `1.3.2 -> 1.4.0`.

### PATCH

Increment `PATCH` for backwards-compatible corrections or refinements to existing capability.

Examples include:

- bug fixes;
- UI polish or presentation corrections;
- performance or resource-use improvements;
- compatibility fixes for an upstream provider/product;
- logging/diagnostic improvements;
- emergency hotfixes.

Example: `1.4.0 -> 1.4.1`.

A hotfix is a patch release; urgency does not create a separate fourth semantic component.

## Initial module version

The first independently versioned release of every MonitorBox module starts at `1.0.0`.

MonitorBox does not use `0.x` versions for first-party modules merely because a module is new or simple. A small stable module such as NUT may remain on a low `1.x` version for a long time if it does not require substantial evolution.

## Build-number rules

`build` is monotonically increasing per module and identifies the exact immutable package artifact.

A build-only increment is permitted only when the module's externally observable behavior and compatibility semantics have not changed—for example, a packaging/signing/reproducibility correction that produces a new immutable artifact from semantically identical module code.

A published module behavior/code change must advance the semantic version according to the rules above in addition to receiving a new build number. Do not ship a succession of behavior changes as `1.0.0 build 5`, `1.0.0 build 6`, `1.0.0 build 7`, and so on.

## Existing historical packages

Previously published immutable packages retain their historical identities. Do not rewrite, rename, or replace signed artifacts solely to retrofit this policy.

At policy adoption, the official repository already contains historical UI and Portainer packages published as `1.0.0` with several build numbers. Those remain valid provenance records. The next behavior-changing release from each module must choose the appropriate semantic bump from its current released behavior:

- correction/polish only -> `1.0.1`;
- new backwards-compatible capability -> `1.1.0`;
- incompatible change -> `2.0.0`.

## Independent module progression

Module versions are independent of MonitorBox Core and of one another. They are not required to align with the MonitorBox appliance version.

A valid installation may therefore contain identities such as:

```text
MonitorBox Core       2.3.0 build 0547
MonitorBox UI         1.3.2 build 18
Portainer             1.5.1 build 22
SNMP                  1.2.0 build 7
NUT                   1.0.2 build 4
Configuration         1.1.0 build 5
```

This independence is intentional: provider/UI fixes and features should normally ship without a Core rebuild when public contracts remain compatible.

## Compatibility is separate from module version

A module's semantic version does not replace explicit compatibility metadata. Manifests must continue to declare the supported MonitorBox Core and Module Runtime API ranges.

Conceptually:

```text
module version:       1.4.2
module build:         47
requires Core:        >=2.3.0 <3.0.0
requires Runtime API: >=1 <2
```

The Module Runtime API version describes the extension contract between Core and modules. A module may receive many semantic releases while remaining compatible with the same Runtime API generation.

## UI presentation

Normal operator-facing UI should treat the semantic version as the primary release identity and the build number as secondary provenance.

Preferred summary:

```text
Portainer
v1.5.1
Latest: v1.6.0
```

Expanded technical detail may include:

```text
Version        1.5.1
Build          22
Module API     1
Requires Core  >=2.3.0 <3.0.0
```

Support/debug fingerprints must retain exact version + build identity.

## Release decision table

| Change | Example | Version action |
| --- | --- | --- |
| First independently versioned release | Initial NUT publication | `1.0.0` |
| Bug fix / polish / performance correction | Fix false degraded state | `1.0.0 -> 1.0.1` |
| Backwards-compatible new capability | Add UPS-detail diagnostics | `1.0.1 -> 1.1.0` |
| Breaking contract/config/state change | Incompatible module API redesign | `1.8.4 -> 2.0.0` |
| Packaging-only correction, no behavior change | Rebuilt immutable ZIP/signing metadata | semantic version unchanged; build increments |

This policy applies to all first-party modules and should be treated as the default requirement for compatible third-party repositories unless a repository explicitly documents a stricter policy.
