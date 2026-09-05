# MonitorBox Modules — development agent charter

This repository contains independently versioned MonitorBox module source, package metadata, publication tooling, signed catalog inputs, and immutable published artifacts.

The project-wide development policy is canonically defined by `SickIcarus-Labs/monitorbox/AGENTS.md`. This repository-local contract carries the rules that must remain visible to agents working directly in `monitorbox-modules`, especially module scope, dividend, versioning, publication, and production-safety requirements. If these documents ever diverge, stop and reconcile them rather than silently choosing the weaker rule.

## Source of truth and scope

Use GitHub as durable development state. The active issue/PR contract defines the bounded task. Module-specific behavior belongs in the owning module; do not use this repository as a route to widen MonitorBox Core.

For module releases:

- preserve independent semantic version + monotonically increasing build identity according to `VERSIONING.md`;
- keep package artifacts immutable once published;
- preserve manifest/runtime/Core compatibility declarations truthfully;
- use the repository's existing signed publication pipeline rather than manually manufacturing catalog/package state;
- do not modify unrelated modules merely because publication tooling touches the same repository.

## Development discipline

- Create or use the intended branch immediately and keep durable branch/PR state current.
- Work in coherent, reviewable chunks and commit/push useful checkpoints during longer work.
- Treat the current issue/PR acceptance contract as the bounded implementation scope.
- Prefer targeted module tests while iterating, then run the appropriate repository acceptance/publication gates before declaring readiness.
- Do not weaken, delete, skip, or rewrite a failing test merely to make CI green; establish whether the test is stale or the code is wrong.
- A reproducible bug fix should gain permanent regression coverage when practical.
- Never commit production credentials, tokens, cookies, private keys, recovered secrets, or live private data.

## Module touch dividend

**Every substantive module visit should normally pay a backlog dividend. The dividend is a required pre-implementation scope decision.**

Before writing substantive implementation code for any module:

1. search the current MonitorBox backlog for open issues owned by that same module (`owner:<module>` or the current equivalent ownership marker);
2. compare candidates by adjacency and value against the code paths, fixtures, provider surface, acceptance flow, and tests already expected for the primary work;
3. record the decision in durable issue/PR scope **before implementation begins** using one of these forms:
   - `Primary: #<issue>` and `Dividend: #<issue>`; or
   - `Primary: #<issue>` and `Dividend waived: <specific allowed reason>`;
4. only then implement the bounded primary + dividend scope.

A missing dividend declaration is a scope-preflight failure. Do not choose the dividend after the primary patch has already been written.

The default operating pattern is:

- **normal module visit:** 1 primary item + 1 additional backlog item;
- **mature module with several small, adjacent items:** up to 2 bugs/debt items + 1 polish/feature item;
- **feature-driven visit:** requested feature + 1 adjacent bug/debt/polish item;
- **P0/emergency regression or architectural surgery:** dividend may be waived so the recovery/structural change remains minimal.

A waiver is exceptional. Allowed reasons are:

- P0/emergency recovery where extra scope would increase restoration risk;
- architectural surgery where preserving a minimal structural change radius is itself the safety constraint;
- no safely adjacent same-module backlog item exists **after the backlog scan is recorded**.

Choose by **adjacency and value**, not issue number alone. Prefer work sharing the same code paths, fixtures, provider surface, acceptance flow, or tests. Generally prioritize release blockers/regressions, correctness bugs, operational annoyances, polish, then new features, while favoring a tightly related lower-priority item over an unrelated higher-priority item when that keeps the change radius smaller.

The dividend is a backlog-burn mechanism, not permission for scope creep:

- identify/link the dividend before implementing it;
- do not cross module boundaries to satisfy a quota;
- close the module visit when primary + agreed dividend are complete, tested, and publishable;
- tiny same-surface corrections may be documented in the PR without manufacturing bookkeeping issues, but deferred/risky/independently testable/cross-module findings require durable issue tracking;
- **the dividend policy never authorizes Core changes.** A Core change requires a separate minimal provider-blind reproducer and explicit Core-owned scope.

## Module architecture boundaries

- Provider/module-specific interpretation, discovery, validation, runtime intent, and provider semantics remain module-owned.
- Generic MonitorBox Core must remain provider-blind.
- Module code must consume approved bounded runtime/module APIs rather than importing private Core implementation merely for convenience.
- Provider unavailability is observation loss, not authoritative evidence that all provider-owned subjects failed or disappeared.
- Preserve truthful raw/provider evidence when normalizing vendor-specific semantics.
- Do not add unrestricted shell, SSH, Docker socket, or production-admin authority to solve a monitoring problem.
- Normal UI contributions must use the supported bounded contribution/presentation contracts; do not introduce arbitrary browser code injection as an implicit module privilege.

## Publication and release safety

Repository write access is development authority, not production authority.

Unless the current task contains explicit human authorization for the exact action, do not:

- deploy or mutate Broad Leaf, Turnberry, or another production environment;
- promote/retag MonitorBox stable/latest or a production release;
- bypass physical acceptance gates;
- use production credentials or live administrative APIs for mutation.

It is acceptable to publish development module artifacts through the repository's explicitly authorized signed CI/publication contract when the task requires it. Green publication CI is not equivalent to physical production acceptance.

## PR completion standard

Before calling module work ready for review:

- the PR records the pre-implementation `Primary` + `Dividend` decision, or an allowed explicit `Dividend waived` reason;
- primary and dividend acceptance criteria are addressed explicitly;
- targeted tests pass;
- required broader module/package/catalog gates have run or are clearly identified as pending;
- semantic version/build identity matches `VERSIONING.md`;
- regression coverage is appropriate to the risk;
- no unauthorized production deployment or stable promotion occurred;
- meaningful architecture decisions, limitations, and deferred findings are durable in the PR/issue rather than only in commit history.

When blocked, leave durable state: commit safe progress, push it, and update the PR/issue with the precise blocker and next executable step.
