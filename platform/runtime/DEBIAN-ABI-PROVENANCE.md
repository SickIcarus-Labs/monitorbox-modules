# Exact Debian ABI/CA inputs for successor runtime (#112/#419)

> **Historical pre-production runtime-package provenance proof.** Any 'candidate-only', 'unreleasable', staged-PR or not-yet-published statement below describes the original test at that date, not the current signed v3 Python/Node/runtime availability. Preserve exact ABI/supply-chain evidence; use accepted signed full-feed package receipts for current authority.


**Development-only, unreleaseable.** Stacked on [immutable Docker OCI
provenance #117](https://github.com/SickIcarus-Labs/monitorbox-modules/pull/117).
The independently native [signed Debian package discovery
run](https://github.com/SickIcarus-Labs/monitorbox-modules/actions/runs/36352194231)
identified the actual package changes when the approved pinned Python 3.13
Bookworm OCI base installs the runtime's original three requested packages.
A second native run recorded all requested baseline package versions and
CA bytes before and after the install. Only `libatomic1` was added. The
existing `libgcc-s1`, `libstdc++6` and CA bundle did not change.

| Input | AMD64 | ARM64 |
| --- | --- | --- |
| Signed Debian version of `libatomic1` | `12.2.0-14+deb12u1` | `12.2.0-14+deb12u1` |
| Exact .deb SHA-256 | `fbd4e154a6b444229ea002cc209df099209c0adc09102e5fd21239a3d2b55e2d` | `1693aa13ce2b30d061a519fc28b77b9bab8c8e45804ced5969d99821e1bc2159` |
| Exact .deb bytes | 9,376 | 9,568 |
| Existing `libgcc-s1` | `12.2.0-14+deb12u1` | same |
| Existing `libstdc++6` | `12.2.0-14+deb12u1` | same |
| Existing/installed CA SHA-256 | `714d457d580922dbf1d0be8bd35ba236a842b50b0072ae791582a19adef772a5` | same |

Native source lock files:
`platform/runtime/debian/lock-amd64.json` and
`platform/runtime/debian/lock-arm64.json`. Both require the exact
[official Python multiarch OCI index](./PROVENANCE.md), explicitly enumerate
all three ABI distributions, and retain `release_eligible:false`.

## Restricted acquisition and offline build

**CI fetch only:** first verify the pinned OCI image's baseline `dpkg`
versions and exact CA SHA256; only then allow `apt-get update` to retrieve
Debian-signed apt indexes *outside* the runtime builder. Require the exact
source-committed version, Debian Packages-index SHA256 and archive pool path.
Download only the reviewed `libatomic1` .deb and verify its length, full
SHA256 and embedded package name/version/architecture before copying bytes
into the native Docker build context. If that old version disappears from
the live signed Debian index, **stop the build**; never auto-upgrade.

**Runtime Dockerfile:** eliminate `apt-get update` and network package
installation entirely. Only copy the approved lock and the *single*
already verified .deb from the CI build context. The preinstall verifier
independently checks exact baseline `dpkg` versions, immutable CA bytes,
file shape/size/SHA256 and `dpkg-deb` identity; install with local
`dpkg -i` and require precisely one native package addition with no
other changes or changed CA. The runtime ZIP packaging process separately
rechecks those native installed bytes, references the SHA256 of its exact
source lock and includes an explicit Debian ABI/CA summary in each Python
and Node `package.json`.

## What remains mutable

OCI image indexes, downloaded .deb bytes, binary ABI versions and CA
contents are now pinned to reviewed hashes. However, CI's **discovery/fetch
step still consults the live Debian-signed apt Packages index** to find the
reviewed bytes. A future Debian mirror removing an old version can make the
build unavailable; the resulting ZIP must never substitute another package.
An immutable Debian signed archive/snapshot or retained fully verified
signed Release/Packages metadata and immutable reviewed .deb object storage
are still required for independently reproducible official publication.
Security/CVE review and intentional ABI package upgrades remain explicit
human release gates.

Every current runtime ZIP still has `release_eligible:false`. This work
does not sign an official runtime, Core or Agent; authorize production
scaffold application activation; qualify UI/Bootstrap/Backup modules; or
change the active Broad Leaf appliance.
