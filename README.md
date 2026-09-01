# MonitorBox Modules

The signed first-party distribution repository for independently updateable MonitorBox modules.

MonitorBox consumes [`index.json`](index.json) over HTTPS. Both the catalog and every module ZIP are signed with the repository's Ed25519 key; Core pins the public trust root and rejects unsigned, modified, or incorrectly identified content.

## Publishing

1. Add the immutable module ZIP under `packages/`.
2. Add its manifest and package filename to `catalog.source.json`.
3. Merge to `main`. The publish workflow calculates the digest, signs the package and catalog, and commits the regenerated `index.json`.

The private signing key exists only as the Actions secret `MONITORBOX_MODULE_SIGNING_KEY`. Never commit it. Public trust material is in [`trust/official-ed25519-1.pub`](trust/official-ed25519-1.pub).

Module packages are inert distribution artifacts. Installation, compatibility checks, activation preflight, rollback, and LKG recovery remain Core responsibilities.
