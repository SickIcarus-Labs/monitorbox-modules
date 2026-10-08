# Successor paired stable promotion: protected transaction contract

**Status:** normative design and **offline model only**. This document does not authorize or implement any GHCR write. Tracks Modules #157 and MonitorBox #635.

## Authority preconditions (mandatory, independently proved)

1. A qualified immutable release manifest names the exact Core/Modules/Python source commits, the protected public signing identity, both separately built OCI digests, three signed catalog bytes, complete ZIP closure and signed internal order.
2. Protected CI verifies source ancestry and required unskipped exact-commit test jobs, then obtains explicit authorized release approval. A candidate manifest's own approval claim, comment command, arbitrary workflow input or label is **not** approval.
3. The *sole* successor stable publisher holds an exclusive publication lock covering both channels. Old hardcoded sequence-specific issue-comment writers remain disabled, including emergency workflows that could race.
4. Under that lock, obtain trusted GHCR read-only double observation of both currently deployed stable tags and their signed catalogs and ZIP contents. Refuse unresolved drift, mixed signatures, rollback, alternate same-sequence releases or reuse of one old image with new internal sequence.
5. The candidate's immutable digests must already exist in GHCR and pass fresh readback. Publication signs and uploads immutable artifacts in a separate, qualified phase. No stable pointer may be mutated to repair an unqualified candidate.
6. Durably record the prior pair, approved target pair, source/CI evidence, operator authorization, publication identity, and full recovery intent **before** any mutation. This receipt must be tamper-evident and usable across runner crashes/restarts.

## Proposed two-pointer transition (requires separate review before activation)

The accepted historical order was Supervisor `stable` then full-feed `stable`. There is no GHCR API for an atomic transaction spanning two distinct OCI tags. Thus **every** order has a transient possible mixed-pair window; this proposal keeps historical order but does not claim atomicity.

For each step, read back the entire observed state and refuse unexpected third-party changes. Under the exclusive lock, move Supervisor stable to its immutable target digest; confirm its readback while full remains prior. Then move full stable to the target and confirm the two final digest references. Verify their underlying signed catalog and ZIP identity again before recording durable success. A re-read of just the tag used for the last write is **not sufficient**.

Appliance clients reading both pointers during the transition must reject incomplete/mixed signed internal sequences and retry within a bounded, specified transient window, without installing a partial release. That client behavior still needs explicit acceptance tests. Lock serialization alone cannot eliminate the intermediate mismatch.

## Interrupted write, ambiguous timeout and recovery

All operations are **at-least-once** and a timeout does not prove that a previous tag write failed. On an error, stop forward promotion; query both tags again. The pure model `tools/successor_promotion_recovery_model.py` enumerates all old/new states:

| Observed full | Observed Supervisor | Compensation proposal |
| --- | --- | --- |
| Previous | Previous | Already restored; verify complete prior pair |
| Previous | Target | Restore Supervisor to previous; verify |
| Target | Previous | Restore full to previous; verify |
| Target | Target, before durable success | Restore full then Supervisor to previous; verify |

The compensator writes a pointer **only** if it still equals our exact previous or target digest, and checks the expected old digest immediately before each action. Unknown third-party refs, missing registry evidence, an incomplete compensation or an unverifiable prior signed pair **must** enter `manual-recovery-required` and block all further promotions. Do not blindly overwrite a third-party release or mark a partial recovery successful.

After restoring prior refs, validate the complete prior signed pair and durable recovery receipt. After successful promotion, validate both exact target refs and record an externally approved durable success receipt. A subsequent process must be able to resume repair of an uncommitted transaction using the prior receipt.

**Important:** The pure model only computes steps and validates synthetic observations. Its `approved_and_audited` argument does not perform authorization and must not be exposed as a production caller-supplied Boolean.

## Excluded from the current implementation

- No GHCR tag writer, protected signing job, release builder, registry write-scoped token, workflow that enables promotion, or successful physical fresh-publication run exists yet.
- This model does not provide the exclusive lock, durable receipt store, operator authorization, verified expected-state conditional registry writes, cross-run crash recovery, compensation execution, or protection from out-of-band writers.
- Once authorized publication exists, acceptance must include fault injection **before/after each tag write**, readback failures, unexpected external writers, runner termination and retry, incomplete compensation, and subsequent physical in-app update/rollback.
- No automatic container image pull or Compose revision is ever required for in-app module package updates. Signed internal catalog order remains independent of appliance product versioning, which is deferred to P1 #647.
