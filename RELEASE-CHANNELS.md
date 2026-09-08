# MonitorBox Module Release Channels

The canonical cross-component release-channel policy lives in the MonitorBox Core repository at `docs/RELEASE-CHANNELS.md`.

This file records the module-specific projection of that policy.

## Module release identity and channel are separate

A module artifact has one immutable release identity:

```text
module_id + semantic version + build + package digest + signature
```

`dev`, `beta`, and `stable` do not create new module builds. They describe confidence in the same exact signed package.

Promotion therefore means making the same package identity visible through a stricter signed repository channel. It never means rebuilding, renumbering, resigning altered bytes under the same version/build, or manufacturing a new package merely to move channels.

## Signed official channels

- `stable` — signed `official` catalog; production/final authority.
- `beta` — signed `official-beta` catalog; phase-accepted cumulative campaign checkpoint.
- `dev` — signed `official-dev` catalog; current exact-head development/physical-acceptance candidates.

The package bytes and exact release identity may appear in more than one channel as confidence increases.

## Core-channel eligibility

The consuming MonitorBox Core release channel bounds which official module catalogs are eligible:

| Core channel | Eligible module channels |
| --- | --- |
| `dev` | `dev`, `beta`, `stable` |
| `beta` | `beta`, `stable` |
| `stable` / `latest` | `stable` only |

The newest compatible semantic version/build across the eligible signed catalogs wins under normal Module Management ordering.

## Campaign lifecycle

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
