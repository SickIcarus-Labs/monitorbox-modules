# Reviewed archived Debian signed-index provenance (#112 / #419)

**Draft, development-only; all runtime packages remain `release_eligible:false`.**

The original successor Python/Node candidate used the immutable official
Python 3.13 and Node 24 multiarch OCI images, exact reviewed native Debian
`libatomic1` .deb bytes and frozen CA, but native CI still ran
`apt-get update` against a **live, changing repository**. This branch
removes live apt as the source of reviewed Debian package bytes and fixes
the **signed Debian package index itself** to a dated externally archived
snapshot. It is not yet an independently retained official release supply
chain.

## Verified exact archived source

[Native AMD64 and ARM64 discovery run
36361576510](https://github.com/SickIcarus-Labs/monitorbox-modules/actions/runs/36361576510)
confirmed that the date-specific Debian archive
`https://snapshot.debian.org/archive/debian/20260926T000000Z/`
contains the previously reviewed exact native
`libatomic1=12.2.0-14+deb12u1` packages. The independently reviewed
signed `dists/bookworm/InRelease` bytes have SHA-256:

`77737fa4b34f2693e982cc9ee35736816c35a7778fc2d326cc1bbf5b301fe1aa`

Its signed `Date` is 2026-07-11T10:16:37Z, before the selected snapshot
checkpoint. Its 151,075 bytes were verified on both architectures with
`gpgv` and the **real Debian archive keyring extracted from the exact
reviewed Python OCI base**. The keyring's approved SHA256 is:

`506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017`

The signed Release binds the architecture-specific index:

| Native CPU | Signed `Packages.xz` SHA-256 | Exact approved `.deb` SHA-256 |
| --- | --- | --- |
| AMD64 | `9e0b5aabb2465b3d2e7a7fe27f9913846277833f7a2826e7767acccff5b588c5` | `fbd4e154a6b444229ea002cc209df099209c0adc09102e5fd21239a3d2b55e2d` |
| ARM64 | `2ddb1737692e8c45c53e8d57c0ce4cd21c78c5703b830c3226b1423566a06c00` | `1693aa13ce2b30d061a519fc28b77b9bab8c8e45804ced5969d99821e1bc2159` |

The entire compressed index and its decompressed form have separate
reviewed SHA256 hashes, exact sizes and the native package's signed
Filename/Version/Architecture/Size/SHA256 are fixed in
`platform/runtime/debian/snapshot-{amd64,arm64}.json`. These source locks
are checked against independent hardcoded review constants, rather than
accepting an internally consistent publisher-controlled manifest.

## Fail-closed acquisition

Both native CI platforms extract the approved Debian archive keyring from
the immutable OCI base and verify its exact SHA256 before contacting the
dated archive. Each build retrieves **only the one approved snapshot URL**
(no alternative mirrors, live apt or fallback release), independently
verifies its actual Debian signature with `gpgv`, then compares the raw
signed `InRelease` digest to the committed review. It authenticates the
downloaded `Packages.xz` against **both** the signed Release index record
and the separate source-reviewed SHA256/size, checks the fully decompressed
index SHA256, and extracts the exact native `libatomic1` record. The
selected package bytes must match the signed index, reviewed native
`lock-{arch}.json` and approved package size. Any unavailable archived
object, expired-at-checkpoint signed Release, changed signature,
different native index, new package version, cross-origin/HTTP redirect,
duplicate manifest key or unapproved byte fails the entire build.

The index/Release and exact downloaded `.deb` are retained as
**short-lived, unreleasable CI evidence**, not in production images. Runtime
Docker builds still receive only the single verified native `.deb` and
execute **no apt, remote package fetch or network-based package
resolution**. Python/Node candidate manifests now additionally declare
the source snapshot-lock SHA256, immutable checkpoint, reviewed keyring
SHA256 and signed Release/Packages digests alongside the installed Debian
ABI/CA and OCI evidence. Their OS package stage is distinct:
`snapshot-locked-oci-base-abi-prototype`.

## Remaining independent release gates

This work eliminates **live-index drift** in normal CI and fixes exact
network-retrieved bytes to Debian's verified signed historical record.
However, `snapshot.debian.org` is **externally hosted** and a dated URL
plus source-committed hashes do not guarantee perpetual availability.
An official reproducible publisher still requires independently retained,
durably accessible copies of Debian's exact signed `InRelease`, native
`Packages.xz`, Debian keyring and native `.deb`, and must re-verify all
signatures and SHA256s offline before publishing. GitHub Actions artifacts
have expiration dates and **must not be treated as the durable release
archive**.

The current Go scaffold's strict [#444/#445](https://github.com/SickIcarus-Labs/monitorbox/pull/445)
runtime policy continues to reject these development-only runtime ZIPs.
Any future qualified publisher must separately review its expanded
snapshot-provenance schema and have independent eligible Core3/Agent3,
wheelhouse, native runtime and module release evidence. Production
interpreted process supervision, immutable separate-UID software generation
and coupled software-plus-canonical JSON active/LKG recovery are separate
acceptance work. **No official signing, release image, channel promotion
or Broad Leaf configuration mutation is performed here.**
