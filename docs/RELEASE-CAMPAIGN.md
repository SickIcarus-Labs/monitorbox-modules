# MonitorBox module release campaign

This document projects the canonical cross-component release-channel policy into the first-party module repository.

Canonical cross-component authority: `SickIcarus-Labs/monitorbox/docs/RELEASE-CHANNELS.md`.

## Channel meaning

Module semantic version/build identity is independent from channel confidence.

- `official-dev` — active development/physical-acceptance candidate feed.
- `official-beta` — cumulative phase-accepted checkpoint feed.
- `official` — stable released module authority.

Moving a package between these repositories never changes its semantic version, build number, package digest, or signature identity.

## Campaign rules

1. Before a campaign, freeze the current accepted module tips in `official` as the stable baseline.
2. Exact-head automated-green candidates publish to `official-dev` without merging or altering `official-beta`/`official`.
3. After physical phase acceptance, promote the exact accepted package set to `official-beta` without rebuild.
4. Merge accepted release source to `main` so later phases build on it. This materializes source/catalog/package authority only; it must not alter the signed stable `official` index.
5. Each later phase begins from the previous cumulative beta checkpoint. Only touched modules advance through dev.
6. After the complete campaign passes final cumulative acceptance, re-sign/promote the exact cumulative beta package set as `official` stable authority.
7. Failed dev candidates may be replaced or yanked without changing beta or stable.

## Stable-source separation

`main` is trunk/source authority, not release confidence. A module release may be present in `main` and in `official-beta` while remaining absent from `official` until final campaign promotion.

The repository therefore keeps stable signed-index publication separate from normal main-branch materialization. Any workflow that signs the root `official` index merely because release source merged to `main` violates the campaign policy.
