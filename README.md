# MonitorBox Modules

The signed first-party distribution repository for independently updateable MonitorBox modules.

MonitorBox consumes [`index.json`](index.json) over HTTPS. Both the catalog and every module ZIP are signed with the repository's Ed25519 key; Core pins the public trust root and rejects unsigned, modified, or incorrectly identified content.

## Versioning

Module releases follow the canonical [`VERSIONING.md`](VERSIONING.md) policy: independent `MAJOR.MINOR.PATCH` semantic versions plus monotonically increasing per-module build numbers. First independently versioned module releases start at `1.0.0`; build numbers identify exact immutable artifacts but do not substitute for semantic version progression.

## Publishing

1. Choose the semantic version required by [`VERSIONING.md`](VERSIONING.md) and increment the module build number.
2. Add the immutable first-party source snapshot under `sources/` and update or add its deterministic package builder under `tools/`.
3. Add the release manifest and generated package filename to `catalog.source.json`.
4. Extend first-party acceptance and publication workflow coverage when introducing a new independently published first-party module.
5. Merge to `main`. The publish workflow deterministically rebuilds `packages/`, calculates package digests, signs the packages and catalog, and commits changed generated artifacts plus the regenerated `index.json`.

Do not hand-author or hand-modify first-party package ZIPs. Their checked-in bytes are generated publication artifacts and must reproduce exactly from the immutable source snapshots and builders.

The private signing key exists only as the Actions secret `MONITORBOX_MODULE_SIGNING_KEY`. Never commit it. Public trust material is in [`trust/official-ed25519-1.pub`](trust/official-ed25519-1.pub).

Module packages are inert distribution artifacts. Installation, compatibility checks, activation preflight, rollback, and LKG recovery remain Core responsibilities.
