# MonitorBox Modules

The signed first-party distribution repository for independently updateable MonitorBox modules.

> **Two distribution contracts coexist during the successor migration.** The root [`index.json`](index.json) and `catalog.source.json` describe the historical HTTPS module catalog (including still-supported 2.x consumers). The modular successor has separately signed, multi-architecture full-feed and Supervisor-bootstrap OCI images in GHCR. Do not treat the root `index.json` or the fixed first-stage image as a replacement for the successor's signed package authority. See [successor release pairing](docs/successor-release-pairing-contract.md) and the [read-only GHCR verification contract](docs/successor-readonly-ghcr-evidence.md).

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

## Issue and PR ownership

Create new engineering tickets **only in [`SickIcarus-Labs/monitorbox` Issues](https://github.com/SickIcarus-Labs/monitorbox/issues)**, with the appropriate module ownership metadata. Keep source, tests, and PRs for independently versioned modules in **this** repository. Do not duplicate a Core issue here simply because the work affects a module. Existing historical `monitorbox-modules` tickets are being reconciled in a separate audit; avoid moving or closing them as an incidental part of code or repository cleanup.

## Successor release-safety boundary

The archived sequence-specific successor signing and stable-pointer commands are **not executable publication paths**. Current tooling can **read** signed GHCR feed pairs by immutable digest, verify both architecture-specific Supervisor catalogs and full ZIP closure, check source/CI evidence, and model two-tag interrupted promotion/compensation. That does not grant permission to create a new signed release or modify mutable channel tags. A real publisher still needs separately reviewed source/build provenance, protected approval, exclusive serialization, post-write readback, failure compensation, and physical acceptance. The two independent GHCR `stable` tags are not an atomic registry transaction.

A green CI run, a merged source PR, or a successful GET-only GHCR inspection must not be described as an installed appliance update, release promotion, or version increment. Normal Core/Agent/UI/Supervisor updates belong to the in-app package lifecycle, not a new Portainer pull.
