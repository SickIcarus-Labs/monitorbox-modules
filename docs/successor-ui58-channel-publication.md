# Core 3 UI58 channel-selector release — signed application package update

**Primary ticket:** [MonitorBox #630](https://github.com/SickIcarus-Labs/monitorbox/issues/630).  
**Source:** UI module v1.18.0 build 58, already merged into Modules main via PR #183.

**Outcome updated 2026-10-09:** The signed full/Supervisor Stable/Beta/Dev catalogs were promoted to sequence **10**, and UI58 was installed/active on the operator appliance, as recorded in [#630](https://github.com/SickIcarus-Labs/monitorbox/issues/630). **Do not re-run the historical sequence-9-to-10 publication procedure below.** A separate image-default/Supervisor bug still constrains the UI to Stable without a temporary explicit `MONITORBOX_CHANNEL_MAX=dev` workaround. The accepted long-term application preference/optional-ceiling fix is **not yet complete**; see #630/#539.

## Intended result

The permanent `ghcr.io/sickicarus-labs/monitorbox:latest` **scaffold is untouched**.
The currently accepted Core, Agent, Python/Node runtimes, Supervisor manager
executables, and nine unrelated application modules retain exactly their existing
immutable ZIP digests. **One UI module** changes.

The publisher derives and signs a complete replacement official catalog from
the existing verified 22-package Stable baseline: 21 unchanged ZIPs plus UI58.
For the initial Core3 release, it publishes the same accepted package set to
the signed **Stable/Beta/Dev** indexes, allowing the operator to switch channels
inside the Modules page. Future development can publish a differing Dev catalog
without an image rebuild of the fixed scaffold.

**The signed full-feed and Supervisor indexes must both move from sequence 9 to
10.** The release pairing contract requires a matching sequence and exact
manager-entry identity even for a UI-only package update. This therefore
produces a new *metadata* image for Supervisor, but **does not rebuild or change
the manager executable ZIP**. Do not substitute the old sequence-9 Supervisor
image under a new tag: that breaks signed pairing.

## Trust and release admission

1. On an isolated feature PR, negative tests assert exactly one allowed module
   delta, no Core/Agent/Supervisor/other module mutation, and monotonic sequence
   ordering. The protected publisher cannot run on a pull-request event.
2. Trusted-main, authenticated owner command begins with **read-only** GHCR
   observation of both actual stable pointers and the complete Ed25519-signed
   package closure. The operator supplies exact expected prior SHA256 pointers
   (or uses the scoped owner command with reviewed sequence-9 digests).
3. Rebuild all ten first-party module candidates as **reproducibility evidence**
   but insert *only* the new UI ZIP into the copied 22-package set. All nine
   other first-party ZIPs must compare byte-for-byte against the previous
   published feed. The twelve native packages are retained as verified bytes.
4. Protected Ed25519 signing verifies the configured public key against the
   permanent fixed trust root. Independently verify every newly signed catalog,
   every package, all supported platform ZIPs, both OCI architectures, and the
   full/Supervisor signed pairing before moving tags.
5. Publish immutable `ui58-seq10-<source-sha>` full/Supervisor images and refuse
   any existing immutable tag. Do not overwrite an independently advanced Beta
   or Dev pointer.
6. Upload a durable previous/target pointer receipt as a GitHub Actions
   artifact **before any moving-tag write**. Enforce exact baseline re-observation
   and promote the signed channel refs in a guarded, serialized section.
   Compensation may revert only known old/target stable digests; unknown
   third-party state requires manual recovery, not blind overwrites.

## Authorized publication

After PR #184 is reviewed, green, and merged, an authorized owner can comment
`/publish-successor-ui58-stable` on that **merged PR**, or run the
`Protected UI58 successor release publisher` workflow from `main` with
`publish-ui58-signed-channels` and both exact current stable digests.

Any unexpected catalog sequence, installed source release, signing identity,
prior OCI digest, Beta/Dev authority, source drift, package digest, or failed
verification must **refuse publication**. Do not recover by pulling, changing
or rebuilding the scaffold image.

## Physical acceptance after signed Stable promotion

1. On the existing `:latest` deployment, authenticate the Modules page and
   check that `Repositories enabled: [Stable]` reflects saved authority.
2. Check for Updates, install the independently signed UI58 package, verify
   the header remains Stable, and verify normal monitoring and configuration.
3. Switch to Dev, accept the explicit warning, wait for committed Supervisor
   activation, verify the UI shows Dev, then restart Core/Supervisor and verify
   persistence without Portainer intervention.
4. Check for Updates again; verify it reads the Dev OCI tag and signed
   Dev/Beta/Stable indexes, even if all three currently select UI58.
5. Switch back to Stable; confirm no invented rollback or downgrade,
   installed package receipts remain intact, and normal health/readiness pass.

## Follow-up release engineering

Current signer schema caps catalog freshness at **168 hours**. Release signing
must be accompanied by a separately qualified ongoing refresh/renewal mechanism
before declaring the platform's online update channel permanently autonomous.
Retained signed generations provide offline boot, but an expired *discovery*
catalog is not suitable for new update admission. Do not silently disable
signature expiry checking as a workaround.
