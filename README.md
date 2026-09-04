# MonitorBox Modules

The signed first-party distribution repository for independently updateable MonitorBox modules.

MonitorBox consumes [`index.json`](index.json) over HTTPS. Both the catalog and every module ZIP are signed with the repository's Ed25519 key; Core pins the public trust root and rejects unsigned, modified, or incorrectly identified content.

## Versioning

Module releases follow the canonical [`VERSIONING.md`](VERSIONING.md) policy: independent `MAJOR.MINOR.PATCH` semantic versions plus monotonically increasing per-module build numbers. First independently versioned module releases start at `1.0.0`; build numbers identify exact immutable artifacts but do not substitute for semantic version progression.

## Publishing

1. Choose the semantic version required by [`VERSIONING.md`](VERSIONING.md) and increment the module build number.
2. Add the immutable module ZIP under `packages/`.
3. Add its manifest and package filename to `catalog.source.json`.
4. Merge to `main`. The publish workflow calculates the digest, signs the package and catalog, and commits the regenerated `index.json`.

The private signing key exists only as the Actions secret `MONITORBOX_MODULE_SIGNING_KEY`. Never commit it. Public trust material is in [`trust/official-ed25519-1.pub`](trust/official-ed25519-1.pub).

Module packages are inert distribution artifacts. Installation, compatibility checks, activation preflight, rollback, and LKG recovery remain Core responsibilities.
