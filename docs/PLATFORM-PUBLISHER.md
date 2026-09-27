# Successor platform signed catalog candidate builder

**Development tooling only.** This is the next slice of [modules #112](https://github.com/SickIcarus-Labs/monitorbox-modules/issues/112), stacked on the schema and verifier in draft PR #113. It generates a **candidate index**; it does not publish a channel, promote any packages, or alter the existing 2.x official module catalogs. Real signing must run in the existing isolated, approval-gated signing environment after the native scaffold and package contracts are accepted.

## Separate source of intent

The input JSON (`schema: 1`, `repository_id: official-platform`, `artifacts: [...]`) is intentionally unsigned. Each source artifact contains the exact fields required by `platform/schema/index-v1.schema.json` **except** `package`; instead it has `package_file`, a simple filename under `platform/packages/` in the package-root directory. No source-supplied absolute URL or path is accepted. Package files must exist and must not be symlinks. The builder reads their **actual** bytes to compute SHA-256, byte size, and a raw-byte Ed25519 signature.

A typical synthetic Core source artifact is:

```json
{
  "artifact_id": "com.sickicarus.monitorbox.core",
  "kind": "module",
  "version": "3.0.0",
  "build": 1,
  "platform": {"os": "linux", "arch": "any", "abi": "pure"},
  "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
  "dependencies": [
    {"artifact_id": "com.sickicarus.monitorbox.runtime.python", "version_range": ">=3.13.0 <3.14.0"}
  ],
  "package_file": "synthetic-core-3.0.0-1.zip"
}
```

The example is **not** an accepted real Core build. The actual Core implementation/runtime ABI and compatible first-party module releases remain gated by Core #416 and modules #114. Native Python/Node packages must be self-contained for the scratch platform, not merely distro-linked binaries.


**Core/Agent release-admission safeguard:** these two executable module identities must now be ZIPs with a bounded internal `package.json`, explicit `release_eligible: true`, and an `artifact_id`/`version`/`build` exactly matching the candidate catalog metadata. A transitional Core source ZIP from Core PR #429 deliberately has `release_eligible: false` and is rejected by this signer; being able to stage it with an ephemeral *test* key does not make it an approved release. The unit tests' ZIPs are clearly synthetic and do not exercise runtime execution. Actual eligibility also requires the protected signing workflow, complete Python/wheel runtime closure, independent process/readiness checks and #421 physical acceptance.

## Signing interface

The isolated publisher receives a 32-byte Ed25519 private seed **via an environment variable**, never from an argv secret or committed file. Candidate output uses a new path and refuses to overwrite an existing signed index. The signing service chooses an explicitly approved channel (`stable`, `beta`, or `dev`), monotonic sequence and expiry window. The returned signed index binds channel, generated/expiry timestamps, package manifest, digest, package signature and envelope signature in the same canonical JSON format as the existing 2.x signer.

The separate scaffold runtime must trust a pinned public root, verify signed catalog metadata and *each package*, then resolve a complete compatible dependency set before staging. Copying an unsigned candidate source or merely downloading a `*.zip` is never activation authority.

For an isolated test fixture only:

```bash
python -m unittest discover -s tools -p 'test_*platform_index.py' -v
```

Synthetic fixtures create ephemeral Ed25519 keys in memory and non-executable fake package bytes. These tests do not exercise private release secrets or write production channel indexes. The builder still needs a dedicated protected signing/promotion workflow and architecture-specific executable package builders before #112 can be closed. Preserve the existing signed stable/beta/dev **2.x** catalogs throughout the migration.
