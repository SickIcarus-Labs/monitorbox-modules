# MonitorBox Module Release Channels

**Status (2026-10-09): module artifact/version/channel invariants are current; the `official*` HTTPS catalog mechanics and Core-image gating later in this file are **legacy 2.x**.** They are not v3 publication instructions. For MonitorBox 3, the current [scaffold-first architecture](https://github.com/SickIcarus-Labs/monitorbox/blob/main/docs/NEXT-PLATFORM-ARCHITECTURE.md), [signed release pairing](docs/successor-release-pairing-contract.md), [paired transaction contract](docs/successor-stable-transaction-contract.md) and [application-owned channel policy #539](https://github.com/SickIcarus-Labs/monitorbox/issues/539) control intent; the [channel ceiling defect #630](https://github.com/SickIcarus-Labs/monitorbox/issues/630) remains active.

## Module release identity and channel are separate

A module artifact has one immutable release identity:

```text
module_id + semantic version + build + package digest + signature
```

`dev`, `beta`, and `stable` do not create new module builds. They describe confidence in the same exact signed package.

Promotion therefore means making the same package identity visible through a stricter signed repository channel. It never means rebuilding, renumbering, resigning altered bytes under the same version/build, or manufacturing a new package merely to move channels.

## V3 signed feed channel policy

- Stable/Beta/Dev select a **signed OCI full-feed catalog** and matched signed Supervisor-bootstrap feed; a release candidate is then resolved by platform/ABI and dependency compatibility and committed by an atomic local generation activation. The two independently movable GHCR channel tags are **not** one atomic registry transaction.
- Module semantic version/build/digest/signature identify the immutable artifact. Changing channel confidence does **not** rebuild or renumber the package. Signed catalog sequence is feed authority, **not** the appliance's human-readable version or an individual module build.
- The operator's durable `release.preferredChannel` is application configuration. Normal Compose does **not** pick the channel by repulling a Core image. A separate, *explicit* optional administrative ceiling is allowed; a Docker image's inherited `MONITORBOX_CHANNEL=stable` is not an intended implicit maximum (#630).
- A runtime's signed, committed **installed generation** is distinct from whatever newer packages a mutable Stable/Beta/Dev pointer currently advertises. No merge, workflow badge, signature verification or channel update alone proves physical installation.

## Historical 2.x signed official HTTPS catalogs

- `stable` — signed `official` catalog; production/final authority.
- `beta` — signed `official-beta` catalog; phase-accepted cumulative campaign checkpoint.
- `dev` — signed `official-dev` catalog; current exact-head development/physical-acceptance candidates.

The package bytes and exact release identity may appear in more than one channel as confidence increases.

## Historical 2.x Core-image channel eligibility

The consuming MonitorBox Core release channel bounds which official module catalogs are eligible:

| Core channel | Eligible module channels |
| --- | --- |
| `dev` | `dev`, `beta`, `stable` |
| `beta` | `beta`, `stable` |
| `stable` / `latest` | `stable` only |

The newest compatible semantic version/build across the eligible signed catalogs wins under normal Module Management ordering.

## Historical 2.x campaign lifecycle

Before a multi-phase campaign, the current accepted first-party module set is frozen in the signed stable `official` catalog.

During each phase:

1. only touched modules receive new semantic version/build identities;
2. automated-green exact candidates publish to `dev`;
3. physical/operator acceptance is performed through the normal Module Manager UI when module behavior or presentation changes;
4. failed dev candidates may be superseded or yanked without disturbing beta/stable;
5. after explicit phase acceptance, the exact accepted package is promoted to `beta` without rebuilding;
6. beta is cumulative across phases;
7. stable remains frozen throughout the campaign.

After the final cumulative beta passes campaign acceptance, every changed module's exact accepted package is promoted to the signed stable `official` catalog. Untouched modules simply remain at their prior stable identities.

## `main` is not stable

Merging release source to `main` is source/trunk progression, not release-confidence progression.

A merge to `main` must not by itself publish a module into the stable `official` catalog. Stable publication requires explicit campaign-level promotion of an already accepted exact package.

This separation allows later phases to build on accepted earlier-phase source while preserving the pre-campaign stable module baseline as a verifiable fallback.
