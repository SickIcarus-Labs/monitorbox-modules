# Successor platform package contract — Phase 0

**Candidate contract for review, not a published catalog.** Tracks [modules #112](https://github.com/SickIcarus-Labs/monitorbox-modules/issues/112) and [native scaffold #414](https://github.com/SickIcarus-Labs/monitorbox/issues/414). Existing released 2.x signed module catalogs, immutable ZIP bytes, promotion actions and trust roots must not change in this PR.

## Signed feed separation

The successor has dedicated candidate endpoints platform/channels/stable/index.json, platform/channels/beta/index.json and platform/channels/dev/index.json. Raw immutable artifacts live at relative platform/packages/ paths. The index envelope is schema 1 plus a signed object and a signature descriptor. The signed object binds repository_id=official-platform, channel, monotonic sequence, generated_at, expires_at and the complete artifact list. The descriptor includes algorithm=ed25519, key identity and base64 signature.

Preserve existing repository signing canonicalization: UTF-8 JSON of the signed object with sort_keys=True, separators=(',', ':'), ensure_ascii=False and allow_nan=False, then Ed25519 signature over those bytes. Package signatures cover **raw package bytes**, exactly as current first-party module publisher does; package metadata also includes SHA-256 and length. An index signature cannot substitute for a package signature.

The permanent launcher embeds a public trust root. New keys must be authenticated by overlapping signatures or an explicit threshold protocol, never merely downloaded from a writable configuration file. Catalog channel, sequence and expiry must be verified; reject wrong-channel replay, stale index, unsafe package URL/path and unsigned or tampered artifact. Expired catalogs cannot authorize fresh installation, but installed verified packages must remain bootable during offline subsequent restarts.

## Artifact manifest and dependencies

See platform/schema/index-v1.schema.json. Every candidate has artifact_id, SemVer, independent build number, kind (scaffold-manager, runtime, module), OS and architecture (Linux amd64, arm64, or architecture-neutral only for pure packages), ABI (static, glibc, musl, pure), explicit scaffold API compatibility, dependency ranges and package digest/signature. An exact pin names a version/build and immutable digest; unsupported or unavailable pins fail before authority mutation. Channel promotion reuses identical signed package bytes rather than recompiling.

New initial IDs: com.sickicarus.monitorbox.core, com.sickicarus.monitorbox.agent, com.sickicarus.monitorbox.scaffold-manager and qualified runtime.python/runtime.node. Preserve existing UI, Bootstrap, Backup/Recovery and provider module identities where already established.

A **critical dependency**: the existing immutable 2.x modules often declare requires_core below 3.0.0. They are not magically eligible for a successor v3 Core. Publish compatible independent builds or prove compatible version/API contracts. Never bypass manifest compatibility merely to make the bootstrap appear successful. Full resolution of Core, Agent, essential UI/Bootstrap/Backup modules, runtime packages and selected providers must occur before a generation is activated.

## Self-contained runtime requirement

The permanent platform image does not bundle Python or Node. Architecture-specific signed runtime packages must carry their interpreter plus a verified, self-contained userland dynamic dependency closure (including loader and shared libraries as needed); a glibc-linked host binary cannot assume glibc exists in a scratch platform image. Test package activation on native Linux/amd64 and Linux/arm64 images. The first-stage launcher stays statically linked.

Runtime package identity and requested versions are saved in Core-module portable JSON policy; the launcher retains known-good pinned defaults, verifies updates and activates a compatible set on restart. The signed catalog is a distribution format, not an excuse to place application policy in the fixed launcher.

## Backup and delivery

Downloaded package caches may retain historical releases for the version selector, but full archives include only the exact installed package closure (including disabled installed modules) and explicitly bounded LKG artifacts, **never** the entire download cache (Core #424). Daily portable JSON includes no executable artifacts.

This is a **Phase-0 schema contract**. The next module-repo implementation must add real signing/verifier tests using ephemeral test keys, then deterministic builders and official channel publication only via the existing isolated signing workflow. No production keys or operator backup material belong in a PR. Keep #112 open until an actual trusted Core/Agent, scaffold-manager and Python/Node feed is available with arm64/amd64 acceptance.