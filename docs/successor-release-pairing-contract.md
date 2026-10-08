# Successor release pairing: actual signed transport contract

**Status:** Read-only verifier corrected for the accepted sequence-9 artifact layout. Not a release permission, publisher, or product-version decision. Tracking: issue #157.

## Actual accepted topology

The **full** immutable signed-feed OCI image is multi-architecture but serves one stable signed platform catalog containing the complete release package set. Accepted sequence 9 declares 22 signed artifacts across AMD64/ARM64, including one scaffold-manager for each architecture.

The **Supervisor** bootstrap OCI image is independently multi-architecture:
- Its Linux/AMD64 platform image has one signed catalog and exactly **one** AMD64 scaffold-manager ZIP.
- Its Linux/ARM64 platform image has a **different signed catalog** with exactly **one** ARM64 scaffold-manager ZIP.
- Both Supervisor catalogs and the full catalog require matching signed channel and internal release order.
- Each Supervisor manager artifact must exactly equal the matching full-catalog manager artifact (version, build, platform, dependencies, package digest, size, and signature).

The earlier #163 prototype expected one combined Supervisor signed index containing both managers. It was valid in synthetic tests but incompatible with the actual sequence-9 format; the correction makes the architecture-specific evidence mandatory.

## Safe admission gates (not yet an executable publisher)

1. A reviewed immutable release manifest names exact qualified source commits, source provenance and full/Supervisor OCI digests; independent module versions are preserved.
2. The trusted job retrieves both OCI indexes by pinned immutable digest, verifies both Linux/AMD64 and Linux/ARM64 platform descriptors, and extracts content from platform-specific images by immutable reference.
3. Exact image labels, approved source SHAs, package eligibility and complete package closure must be verified against trusted registry contents and actual GitHub qualifications—not requester-provided assertions.
4. The signed catalog verifier authenticates the full signed index and both separate Supervisor indexes, matches release order and both manager artifacts, then the package verifier checks every signed ZIP byte, signature, length and hash.
5. The protected promotion job reads **both** current GHCR stable pointers, validates them as a coherent signed pair and rejects stale, mixed or alternate same-order requests. Catalog expiry may prevent an old catalog from being installed; its valid historical signature can still establish ordering.
6. Operator approval and exclusive workflow serialization precede pointer movement. GHCR has no atomic two-tag transaction: a failed partial write requires compensating restoration of the verified previous pair and final readback. An authoritative single-pointer model would remove this two-tag atomicity problem but is not implemented.
7. Mark success only after current full/Supervisor registry readbacks prove the intended coherent pair. Never modify accepted sequence-9 stable pointers as part of repository cleanup.

The helper implements **only** catalog authenticity, architecture-specific pairing and monotonic ordering. It does **not** retrieve OCI manifests, prove image labels, verify package bytes, validate CI source qualifications, authorize a release, or write registry tags. These are blocking follow-up gates.

Catalog sequence is **internal anti-rollback metadata**, not MonitorBox's product version. Routine updates remain package-management operations inside the running appliance; they must not require fresh container pulls.

## Read-only observation of the current moving stable pair

The stable observation helper resolves the two independent GHCR `stable` pointers with **GET**, downloads both immutable OCI images by returned content digest, verifies the full OCI layer/catalog/ZIP chains and the signed architecture-specific Supervisor manager pair, then rereads both mutable pointers. It refuses a torn/mixed signed state and detectable mid-read tag movement. The historical current signed indexes may have expired, but must have authentic signatures and internally consistent historical issue/expiry timestamps and package signatures.

**This is a witness, not a transaction.** A two-read snapshot cannot detect every ABA flip and does not serialize writers. Before any stable promotion, a separate protected actor must hold exclusive release authority, reread current digests immediately before committing, refuse rollback and alternate same-sequence releases, and implement a compensating rollback on partial failure with final dual-tag registry readback. This new read-only helper never changes a tag or contacts Portainer.
