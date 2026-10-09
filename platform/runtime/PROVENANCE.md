# Successor runtime upstream provenance lock (#112 / #419)

> **Historical pre-production runtime-package provenance proof.** Any 'candidate-only', 'unreleasable', staged-PR or not-yet-published statement below describes the original test at that date, not the current signed v3 Python/Node/runtime availability. Preserve exact ABI/supply-chain evidence; use accepted signed full-feed package receipts for current authority.


**Candidate-only, non-production.** Stacked on unreleaseable Python/Node
self-contained package proof #116. This records an exact immutable
multi-architecture OCI image index digest for both upstream build stages.
It does not authorize publication of an eligible signed runtime, Core or Agent.

## Verified upstream references

Official Docker Hub references were resolved by the [independent GitHub
Actions digest-evidence run](https://github.com/SickIcarus-Labs/monitorbox-modules/actions/runs/36350552704)
on 2026-09-27. For each reference `docker buildx imagetools inspect` returned
a SHA-256 index digest containing **linux/amd64 and linux/arm64** variants.

| Upstream image | Immutable multiarch index |
| --- | --- |
| Python 3.13 slim Bookworm | `python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26` |
| Node 24 slim Bookworm | `node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6` |

The checked-in `platform/runtime/upstream-lock.json` is the single manifest
record. Both `FROM` stages in `platform/runtime/Dockerfile` use those exact
`tag@sha256` references; there is no build ARG to choose a floating replacement.
The Python packager reads a locked, copied version of the JSON and Dockerfile
inside the builder and refuses to emit a package if either is missing,
symlinked, malformed, ambiguous, floating, wrong repository or inconsistent.
All Docker-built packages embed the same digests in their signed-manifest-
shaped `upstream` object. CI checks both embedded runtime ZIPs against the
committed lock on independently native AMD64/ARM64 runners.

Digest discovery continues to record the latest upstream tag versions for
future *deliberate* lock updates. The runtime Dockerfile does not follow a
moved tag automatically.

## Exact Debian ABI and CA bytes; remaining mutable metadata

The original Debian apt installation has been replaced by the reviewed
[architecture-specific native ABI/CA lock](./DEBIAN-ABI-PROVENANCE.md).
Only `libatomic1` is absent from the fixed Python OCI base image. CI
downloads the exact native Debian-signed .deb SHA256 on AMD64/ARM64, and the
runtime Dockerfile verifies its embedded dpkg metadata and SHA256 **before
any offline installation**. The two other requested ABI distributions are
already present at the exact expected versions. The pinned OCI base's
CA-certificate bundle retains the identical reviewed SHA256 before and after
installation. No runtime Docker stage uses apt or resolves packages online.

The runtime manifests record the upstream image index digests, the
source-committed native Debian lock SHA256, installed ABI package versions,
exact new .deb hash and CA hash. These remain explicitly
`release_eligible:false` with the
`sha256-locked-oci-base-abi-prototype` OS package stage.

**The Debian signed apt index used by CI to retrieve these immutable .deb
bytes is still live rather than an immutable archived snapshot.** If the
approved version disappears or the signed metadata differs, the build
must fail rather than select a newer version. Official reproducible
publication requires independent archival of the Debian signed index and
immutable reviewed .deb object storage, plus the independent signed
Core/Agent package publisher, full appliance and last-known-good rollback
acceptance. This work does not publish, sign, promote or alter Broad Leaf.
