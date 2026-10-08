# MonitorBox 3 — Derived Appliance Version (Design v1)

**Decision date:** 2026-10-08  
**Status:** Agreed design, **implementation deferred**.  
**Implementation tracking:** [MonitorBox #647 — P1](https://github.com/SickIcarus-Labs/monitorbox/issues/647).

This is the normative proposed product-version contract for the modular successor. It is **documentation only**: publication tooling, installed UI, signed feeds, Compose, runtime software, GitHub Releases and production installations are unchanged by adopting this document. Do not implement until the parked P1 task is explicitly scheduled after repository/process cleanup and the issue audit.

Related authority: [module versioning](VERSIONING.md), [module release channels](RELEASE-CHANNELS.md), and [successor architecture](https://github.com/SickIcarus-Labs/monitorbox/blob/main/docs/NEXT-PLATFORM-ARCHITECTURE.md). The historical 2.x Core-only product-version model is not retroactively changed.

## 1. Scope and intent

The appliance version is a **short, human-readable reference for the activated application composition**, not a package identifier, catalog sequence, update ordering mechanism, qualification certificate, or trust/compatibility assertion.

Only three independently versioned packages define that shorthand:

| Role | Defining? | Why |
| --- | --- | --- |
| Core | **Yes** | Application architecture, API and central coordination; its MAJOR defines the appliance MAJOR |
| Agent | **Yes** | Acquisition and execution engine |
| UI | **Yes** | Operator-facing application features |
| Supervisor / scaffold-management runtime | No | Required independent lifecycle infrastructure |
| Configuration / Bootstrap | No | Required application module, independent version |
| Backup / Restore | No | Required application module, independent version |
| Python, Node, wheelhouse, fixed first-stage scaffold | No | Dependencies / foundation with independent provenance |
| Optional monitoring/provider integrations | No | Independently versioned extensions |

Required components continue to participate in dependency/ABI compatibility admission and recovery, even though they do not all change the product's short version.

The local UI and repository-side publication tooling each implement **the same pure version function**. The UI computes from the **actual activated Core/Agent/UI artifact semantic versions** obtained from the lifecycle system, not staged, newest-available, catalog-selected, or assumed GitHub versions. The repository tool computes from the explicitly selected accepted module composition. Given the same three component semantic versions, both compute the same appliance version, regardless of installation order, available feed, selected channel, network connectivity, or GitHub Release cadence.

**No central issuance ledger, custom-version suffix for unmatched local compositions, runtime publisher/UI cross-check service, or in-app “Latest GitHub release” status.** Any supported compatible local composition can have a derived shorthand that GitHub has never published.

## 2. Exact derived-version function — v1

Input is a tuple of stable numerical semantic versions:

    Core  = (cMajor, cMinor, cPatch)
    Agent = (aMajor, aMinor, aPatch)
    UI    = (uMajor, uMinor, uPatch)

Output is three unsigned decimal integers rendered as:

    MonitorBox = cMajor . M . P

The v1 radix is **R = 1000**. Normalize the starting successor composition Core 3.0.0, Agent 3.0.0, UI 1.17.1 to MonitorBox 3.0.0:

    agentMinorScore = R * (aMajor - 3) + aMinor
    uiMinorScore    = R * (uMajor - 1) + uMinor - 17
    M               = cMinor + agentMinorScore + uiMinorScore

    uiPatchOffset   = 1 if (uMajor == 1 and uMinor == 17), otherwise 0
    P               = cPatch + aPatch + uPatch - uiPatchOffset

    applianceMajor  = cMajor

The conditional patch offset preserves the reference baseline without producing negative patches when UI advances from 1.17.x to 1.18.0 or 2.0.0. It is **not** a release count, date, feed sequence, or operator policy.

### Supported domain (v1)

- Core semantic version is **at least 3.0.0** and Agent at least **3.0.0**.
- UI semantic version is **at least 1.17.1**.
- Agent and UI **minor** fields are each in the inclusive range **0..999**. This range must be enforced at every major-line transition; the formula permits their major fields to advance.
- Core minor, and all three patch fields, are nonnegative integers and are not limited to 999.
- All input fields and calculated output fields must fit the precise integer range of both the repository and UI implementations (at minimum, reject values outside JavaScript's nonnegative safe integer range). Reject integer overflow.
- Current package manifests carry three stable numerical fields. Release channel is separate; do not strip unrecognized prerelease syntax or guess how it should contribute. Unsupported module-version syntax or values **fail explicitly**, rather than coercing, wrapping or silently truncating.
- Compatibility and signature checks are separate and remain mandatory. Successful arithmetic does not make an incompatible combination admissible.

The radix **cannot be casually changed** when a component reaches minor 1000. A future v2 algorithm/domain migration requires a separate reviewed policy preserving stable version identities, including offline and mixed-version behavior. Do not quietly produce a different version for unchanged installed packages.

### Reference vectors (illustrative package versions)

| Core | Agent | UI | Derived MonitorBox |
| --- | --- | --- | --- |
| 3.0.0 | 3.0.0 | 1.17.1 | **3.0.0** |
| 3.0.1 | 3.0.0 | 1.17.1 | **3.0.1** |
| 3.0.0 | 3.0.1 | 1.17.1 | **3.0.1** |
| 3.0.0 | 3.0.0 | 1.17.2 | **3.0.1** |
| 3.0.0 | 3.0.1 | 1.17.2 | **3.0.2** |
| 3.0.0 | 3.0.0 | 1.18.0 | **3.1.0** |
| 3.0.0 | 3.1.0 | 1.18.0 | **3.2.0** |
| 3.0.0 | 3.0.0 | 2.0.0 | **3.983.0** |
| 3.0.0 | 4.0.0 | 1.17.1 | **3.1000.0** |
| 4.0.0 | 3.0.0 | 1.17.1 | **4.0.0** |
| 3.0.0 | 3.0.0 | 1.999.9999 | **3.982.9999** |
| 3.0.0 | 3.0.0 | 2.0.0 | **3.983.0** |

The large numerical steps at non-Core major transitions are an **accepted readability tradeoff** for a stateless monotonic function with 1000 minor-version slots per Agent/UI major line. The shorthand need not carry meaningful feature-vs-fix SemVer semantics for its own minor/patch components; **module** SemVer remains the true software ordering and compatibility basis.

## 3. Ordering guarantees and limitations

Within the supported domain:

1. If Core, Agent and UI each remain unchanged or increase in SemVer precedence, and at least one strictly increases, the calculated appliance version **strictly increases** in numeric SemVer tuple order.
2. If exactly one defining module is downgraded to a lower semantic version and the other two are unchanged, the calculated appliance version **strictly decreases**.
3. A change involving both upgrades and downgrades across the defining modules has no prescribed direction; it depends on the resulting tuple.
4. A build-only rebuild, channel promotion, nondefining-package change or digest-only replacement **does not change the shorthand** when defining-module semantic versions are unchanged.
5. Two different compositions **may share a shorthand**, for example a Core patch versus an Agent patch. The shorthand is deliberately not an injective artifact identity.

**Reasoning:** A patch-only increment raises P with M unchanged. Increasing a module minor raises M, which dominates any patch reset. For Agent/UI, the 1000-slot radix makes a major increment raise M even when the prior minor was 999 and the next minor resets to zero. Increasing Core major raises the appliance's leading component. Sums preserve componentwise monotonicity. These statements apply only to accepted input ranges and comparable numeric stable SemVer triples.

The v1 formula was evaluated in design with 470,000 generated transitions (including 150,000 single-component tests, 200,000 mixed upgrade/rollback tests, and 120,000 comparative-radix trials) without monotonicity failures. Those results are **design evidence, not shipped automated regression coverage**; implementation must add persistent and exhaustive boundary fixtures.

## 4. Local state, channels and operator presentation

- Core/Supervisor already control authoritative **committed active-generation** package identities. The UI consumes that read-only projection and computes the version locally, including on offline restarts.
- Installed version, selected update channel and available module versions are distinct. Merely switching between Stable, Beta and Dev must not change the product-version calculation.
- Mixed Stable/Beta/Dev installations are legitimate; locally calculate the shorthand even if no identical GitHub Release exists.
- UI header eventually shows the derived MonitorBox version and separately presents the selected channel. Do not display “Latest GitHub release.”
- Module Management retains each module's exact semantic version, build, channel provenance where known, release selectors and compatibility information.
- The existing Core-only identity such as “v3.0.0 · build 0003 · dev” is **not** the derived platform version; build 0003 is artifact provenance. Builds and digests must never be substituted into M or P.

## 5. Fingerprints and GitHub publication

The **exact generation fingerprint** is distinct from the shorthand version. Build a deterministic digest from a canonical ordered inventory of signed activated artifact IDs, versions, builds, architecture where relevant and immutable package digests (including nondefining installed modules). The technical/diagnostic display can abbreviate it, but preserve the full input receipts and digest. Exact fingerprint format and canonical serialization are part of future issue #647, not product-version arithmetic.

GitHub release tooling independently derives the *same displayed MonitorBox version* from the accepted selected Core/Agent/UI semantic versions, and records the entire qualified package closure and exact fingerprint. GitHub Releases may be published on a monthly cadence and/or immediately following sufficiently important stable promotions, after existing acceptance/approval gates. A GitHub release is a **snapshot**, not the authority from which an installed appliance determines its current version; locally installed Stable packages can therefore produce a newer shorthand than the last GitHub Release.

Because the shorthand can collide between distinct package sets, **immutable GitHub tags must include collision-safe exact composition provenance**, for example a SemVer build-metadata fingerprint suffix. Do not retag or overwrite a prior different release. The human-readable release title may remain “MonitorBox v3.2.1.” Product version and release fingerprint are two separate fields.

No changes to fixed scaffold/Compose, Docker pulls, module repackaging, signed channel pointers or stable authorization should occur simply to change or calculate the product version.

## 6. Deferred implementation / qualification scope

P1 issue [#647](https://github.com/SickIcarus-Labs/monitorbox/issues/647) owns:

- Pure publisher-side and UI-side functions matching this specification, using a shared cross-language fixture suite.
- Baseline and transition-vector tests, boundary tests (minor 999→next major, huge patches, Core major changes), mixed-channel/offline tests, rollback tests, out-of-domain failures and semantic-version-only behavior.
- Signed feed/publication integration that does **not** change release-confidence policy or invent new package releases.
- Activated-generation UI projection and application-header change; fingerprint diagnostics.
- Collision-safe immutable GitHub release tagging and cumulative release notes; no in-app GitHub release indicator.

**Do not implement in this documentation task.** Any policy change to the formula, radix, baseline, package nucleus or supported domain requires explicit review, not opportunistic implementation adjustment.
