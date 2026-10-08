# Read-only GHCR immutable release evidence

Status: **candidate qualification only**, not authorization to publish or promote. Tracks Modules #157 and parent monitorbox #635.

## Contract

The fixed-origin transport contacts only `https://ghcr.io` through HTTPS GET. The two permitted package repositories are `sickicarus-labs/monitorbox-successor-signed-feed` and `sickicarus-labs/monitorbox-successor-supervisor-feed`. Requests use immutable SHA-256 digests, never `stable`, `dev`, `latest`, or another tag. Optional private-package authentication uses `GHCR_USERNAME` and `GHCR_READ_TOKEN` against the validated GHCR Bearer pull-token endpoint; provide a token with **read:packages only**. No token or response body is printed. HTTPS blob-CDN redirects do not inherit the Authorization header. Network transport never implements a registry write.

For **each** OCI image, the runner retrieves the index and exact AMD64/ARM64 image manifests and configs and checks all digest/size links. Every referenced layer is fetched by immutable SHA, hashed, size-bounded, decompressed without image execution or unsafe archive extraction, and inspected for a signed feed index and package ZIPs. Unsupported media types, whiteouts, links, traversal, duplicate/overlaid files, oversized blobs and mismatched architecture evidence fail closed.

Full feed content must be byte-identical across its two platform images. The Supervisor feed has **two independently signed one-manager catalogs** (one per architecture). All three catalogs and every signed ZIP are checked against their pinned manifest hashes, exact package inventories, official Ed25519 public root and OCI provenance labels. No Docker daemon, privileged container or remote code execution is involved.

## Explicit manual invocation

Run from `monitorbox-modules` source with Python 3.13+, `cryptography` and `jsonschema`:

```sh
# Leave GHCR_USERNAME and GHCR_READ_TOKEN unset for anonymous/public images.
# Set them only for a private package, using a read:packages-only token.
python tools/successor_registry_readonly_cli.py \
  --candidate /path/to/reviewed-qualified-release-candidate.json \
  --trust-root trust/official-ed25519-1.pub
```

The command outputs a compact JSON result with `status=validated-read-only`, exact full/Supervisor digests, internal catalog sequence and `publication_authorized=false`. Temporary extracted files are automatically deleted. It does not query or alter currently installed appliance state.

## Optional live GitHub source-CI evidence

Add `--require-source-ci` to the manual command to *also* require that each exact Core, Modules, and Python source commit is an ancestor of its corresponding accepted repository's `main` branch, and that the fixed required workflows ran on that exact commit with their **actual test jobs succeeding** (not skipped). This only uses HTTPS GET to `api.github.com` against the two fixed private repositories. For private source, provide `GH_SOURCE_READ_TOKEN` with read-only Contents and Actions permissions on both; the tool never forwards it to redirects.

The fixed minimum policy is: Core and reviewed Python source require the `monitorbox` CI workflow's `Validate MonitorBox` job; Modules source requires the integrated signer/source contract job, signed platform contract job, and signed-feed publication contract job, all at that exact Modules commit. A successful wrapper with the required job skipped is refused; a past success cannot hide a later failed run on the same workflow/source. PR head runs can count only when the exact source commit subsequently became a `main` ancestor.

The extended invocation is:

```sh
python tools/successor_registry_readonly_cli.py \
  --candidate /path/to/reviewed-qualified-release-candidate.json \
  --trust-root trust/official-ed25519-1.pub \
  --require-source-ci
```

Without this switch, output explicitly declares `source_ci_verified=false`. With it, qualification fails closed if the API has no permission, any exact-SHA check is absent, or a required test job was skipped/failed.

This evidence is necessary but not sufficient: it is **not** proof of protected main-branch rules, reviewed release approval, exact build recipe reproducibility or signed publisher authorization. Current private-repository branch protection remains blocked by GitHub plan/permission limitations.

## Optional signed-current stable monotonic preflight

Use `--check-current-stable` to read both existing GHCR `stable` tags **without writing**, verify the exact current full/Supervisor immutable signed feed pair (including expired-but-authentic historic catalogs) and reread both pointers after extraction to detect tag drift. The verifier then rejects an older candidate, rejects alternative artifacts with an identical signed sequence and rejects a purported newer candidate that reuses only one current image digest. A byte-identical same-sequence pair is reported as `already-current`; a strictly newer signed pair reports `newer-candidate`. Both outcomes are explicitly **read-only**.

The operator command can combine `--require-source-ci --check-current-stable` to check both source/CI evidence and the existing channel state, but output always retains `publication_authorized=false` and `channel_changed=false`. A double-read witness is not exclusive publication serialization, cannot prevent every ABA race, and is not an atomic two-tag transaction. No user has approved live promotion as part of cleanup.

## Live existing-stable acceptance (main only, no candidate)

A dedicated `.github/workflows/successor-live-stable-readonly.yml` executes the
existing signed-current feed witness against **actual GHCR** only after its
workflow/CLI changes reach trusted `main`, or when manually dispatched from
`main`. It cannot run arbitrary pull-request code with package-read access.

The job has only `contents: read` and `packages: read` permissions. It tries
`github.actor` + the ephemeral `github.token` as GHCR pull credentials;
there is no long-lived PAT or signing secret. If GitHub package access for this
repository has not been authorized, the run **must fail** and the missing
permission must be resolved separately. Do not expand to package-write access.

```sh
# From accepted monitorbox-modules source, after optional GHCR_READ_TOKEN
# read-only package credentials are configured locally:
python tools/successor_existing_stable_readonly.py \
  --trust-root trust/official-ed25519-1.pub
```

Unlike the candidate command, the stable observer requires **no new release
manifest** and does not reject an existing signed catalog solely because its
installation expiry has passed. It still requires official Ed25519 signatures,
consistent signed sequence, exact manager pairing, correct OCI platform
provenance and every ZIP's signature/byte closure. It double-reads both moving
stable pointers to detect observable tag changes during verification.

An Actions success proves a *specific* real-GHCR read-only observation was
successful at its execution time; it is not a release, a protected approval,
a new installable package, or proof of two-tag atomicity. A failed run is not
an excuse to repoint old stable tags or bypass artifact signing. The original
sequence-9 production pair and installed appliance remain unchanged.

## Remaining release blockers

A manifest's claims are **not independent release authorization**, and this command does not verify whether the source commits passed required GitHub CI checks, who reviewed them, or whether a protected approver authorized publication. The command does not verify the build process used to produce the signed ZIPs beyond cryptographic package identity and embedded archive eligibility admission; that requires qualified build provenance. GHCR availability and access to private images have **not** yet been physically exercised through this runner.

There is no publishing, tag update, registry serialization or safe two-pointer rollback in this code. Both mutable `stable` pointers need a separate live readback/anti-rollback check; GHCR cannot atomically update two independent tags. The signed sequence is internal anti-rollback metadata, **not** MonitorBox's operator-facing product version. Ordinary appliance updates must remain in-app package transactions without a new container pull.

No existing sequence-9 stable pointer, installed appliance, Portainer Compose, signer key or archived release artifact is changed by this work.
