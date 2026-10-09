# MonitorBox Modules

The signed first-party distribution repository for independently updateable MonitorBox modules.

> **Current MonitorBox 3 distribution:** independently signed **full platform/module** and **Supervisor bootstrap** multi-architecture OCI feeds in GHCR, resolved and verified **inside** the installed appliance. The two signed-feed packages are publicly readable while the `monitorbox:latest` first-stage image/source remain private. Package publication, package activation, and Docker image distribution are separate authorities. See [current v3 architecture](https://github.com/SickIcarus-Labs/monitorbox/blob/main/design.md), [signed release pairing](docs/successor-release-pairing-contract.md) and [read-only GHCR verification](docs/successor-readonly-ghcr-evidence.md).

> **Historical 2.x distribution only:** the root [`index.json`](index.json), [`catalog.source.json`](catalog.source.json) and existing signed package ZIPs implement the legacy HTTPS `official` catalog. Older 2.x Core consumes `index.json` over HTTPS. These artifacts and their signatures are retained for compatibility/provenance, **not** as a v3 update feed or a replacement for the signed v3 Supervisor/package closure.

## Versioning

Module releases follow the canonical [`VERSIONING.md`](VERSIONING.md) policy: independent `MAJOR.MINOR.PATCH` semantic versions plus monotonically increasing per-module build numbers. First independently versioned module releases start at `1.0.0`; build numbers identify exact immutable artifacts but do not substitute for semantic version progression.

## Signed publishing and retained 2.x catalog

For **v3**, source merge or a generated root `index.json` does not publish a new Supervisor/full-feed generation. Independent module source changes must be qualified against the signed Core/Agent/runtime/module contract and exact multiarch closure; immutable signed package publication and coupled full/Supervisor channel movement require separately protected, reviewed release authority. **Do not invoke an old sequence-pinned publisher as a general release procedure.** See [read-only GHCR evidence](docs/successor-readonly-ghcr-evidence.md), [paired stable transaction design](docs/successor-stable-transaction-contract.md), and [production v3 lifecycle](https://github.com/SickIcarus-Labs/monitorbox/blob/main/design.md). This documentation does **not** authorize new release writes.

The following steps describe **legacy 2.x HTTPS catalog maintenance** only (preserved for reproducibility and older clients):

1. Select the module SemVer/build according to [`VERSIONING.md`](VERSIONING.md).
2. Add the immutable first-party source snapshot under `sources/` and maintain the deterministic builder under `tools/`.
3. Add the release manifest and ZIP reference to `catalog.source.json`.
4. Maintain legacy first-party acceptance/publication workflow coverage as required.
5. The historical publish path deterministically generated `packages/`, digests, signatures, and `index.json`; a merge to `main` must **not** be mistaken for authorized v3 stable publication.

Do not hand-author or hand-modify generated first-party package ZIP bytes. The immutable signed artifacts must remain reproducible from their approved source/builders.

The private signing key exists only as the Actions secret `MONITORBOX_MODULE_SIGNING_KEY`. Never commit it. Public trust material is in [`trust/official-ed25519-1.pub`](trust/official-ed25519-1.pub).

Module archives are inert transport artifacts. For v3, the **signed Supervisor/scaffold lifecycle** admits and activates the complete compatible generation, while Core/application modules own their appropriate semantics and settings; do not assign Supervisor/bootstrap or Core image-update authority to the legacy HTTPS module manager.

## Issue and PR ownership

Create new engineering tickets **only in [`SickIcarus-Labs/monitorbox` Issues](https://github.com/SickIcarus-Labs/monitorbox/issues)**, with the appropriate module ownership metadata. Keep source, tests, and PRs for independently versioned modules in **this** repository. Do not duplicate a Core issue here simply because the work affects a module. Existing historical `monitorbox-modules` tickets are being reconciled in a separate audit; avoid moving or closing them as an incidental part of code or repository cleanup.

## Successor release-safety boundary

The archived sequence-specific successor signing and stable-pointer commands are **not executable publication paths**. Current tooling can **read** signed GHCR feed pairs by immutable digest, verify both architecture-specific Supervisor catalogs and full ZIP closure, check source/CI evidence, and model two-tag interrupted promotion/compensation. That does not grant permission to create a new signed release or modify mutable channel tags. A real publisher still needs separately reviewed source/build provenance, protected approval, exclusive serialization, post-write readback, failure compensation, and physical acceptance. The two independent GHCR `stable` tags are not an atomic registry transaction.

A green CI run, a merged source PR, or a successful GET-only GHCR inspection must not be described as an installed appliance update, release promotion, or version increment. Normal Core/Agent/UI/Supervisor updates belong to the in-app package lifecycle, not a new Portainer pull.
