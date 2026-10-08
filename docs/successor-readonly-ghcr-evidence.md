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

## Remaining release blockers

A manifest's claims are **not independent release authorization**, and this command does not verify whether the source commits passed required GitHub CI checks, who reviewed them, or whether a protected approver authorized publication. The command does not verify the build process used to produce the signed ZIPs beyond cryptographic package identity and embedded archive eligibility admission; that requires qualified build provenance. GHCR availability and access to private images have **not** yet been physically exercised through this runner.

There is no publishing, tag update, registry serialization or safe two-pointer rollback in this code. Both mutable `stable` pointers need a separate live readback/anti-rollback check; GHCR cannot atomically update two independent tags. The signed sequence is internal anti-rollback metadata, **not** MonitorBox's operator-facing product version. Ordinary appliance updates must remain in-app package transactions without a new container pull.

No existing sequence-9 stable pointer, installed appliance, Portainer Compose, signer key or archived release artifact is changed by this work.
