# Successor runtime upstream provenance lock (#112 / #419)

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

## Explicit remaining mutable supply-chain inputs

`apt-get update && apt-get install` still resolves Debian Bookworm security
and ABI support packages at build time, rather than an immutable snapshot with
individually reviewed .deb SHA-256 digests. CA certificates also originate
from those mutable package sources. Thus two builds from the same pinned
upstream OCI indexes at different dates can differ. The generated ZIP is
deterministic only when all input bytes are identical; pinning both upstream
OCI indexes alone does **not** qualify a reproducible official release.

The archive manifest explicitly declares
`packaging_stage: "digest-pinned-upstream-runtime-proof"`,
`upstream.os_packages: "unpinned-debian-bookworm-apt-prototype"`, and
`release_eligible: false`. No step in the development workflow may rewrite
that approval flag, upload an official package, sign with the release root,
or change Broad Leaf.

Before the next publisher acceptance: freeze the complete Debian ABI/CA
package closure and verify exact checksums for both native architectures,
review vulnerabilities and update strategy, pin every Core wheel transitively,
make independently distributable Core and Agent packages, and run full
signed-package offline install and actual supervised activation with durable
configuration-plus-software rollback. These are separate release gates.
