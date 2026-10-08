"""Pure, I/O-free release transaction and compensation policy.

This contains no GHCR adapter and cannot move a tag. All inputs must be
separately proven by signed immutable candidate verification and live current
dual-tag witnesses. A future authorized publisher must apply the planned
operations under a true exclusive lock, re-check each precondition against
fresh registry readback, and produce a durable signed release audit receipt.

Two GHCR tags cannot be changed atomically. This model describes fail-closed
recovery after interruption but does not make the partial-write window safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from successor_release_pairing import (
    Pair, ReleaseRefusal, compare_verified_pair_freshness,
)

Role = Literal["supervisor", "full"]
Intent = Literal["target", "previous"]

@dataclass(frozen=True)
class PointerSnapshot:
    full_digest: str
    supervisor_digest: str


@dataclass(frozen=True)
class ProposedStep:
    role: Role
    desired: Intent
    expected_previous_digest: str
    replacement_digest: str


@dataclass(frozen=True)
class TransactionPlan:
    previous: Pair
    target: Pair
    transition: tuple[ProposedStep, ...]
    no_op: bool


@dataclass(frozen=True)
class RecoveryPlan:
    state: Literal["already-previous", "requires-compensation"]
    recovery: tuple[ProposedStep, ...]


def _snapshot(pair: Pair) -> PointerSnapshot:
    return PointerSnapshot(pair.full_digest, pair.supervisor_digest)


def _step(role: Role, old: str, new: str, intent: Intent) -> ProposedStep:
    return ProposedStep(role, intent, old, new)


def prepare_transaction(previous: Pair, candidate: Pair,
                        fresh_current: PointerSnapshot) -> TransactionPlan:
    """Read-only, fully specified promotion intent after qualification.

    Caller MUST already hold exclusive publication authority and obtain
    fresh current GHCR evidence; candidate alone grants no permission.
    """
    if not isinstance(fresh_current, PointerSnapshot) or fresh_current != _snapshot(previous):
        raise ReleaseRefusal("current GHCR pointers drifted before proposed transaction")
    decision = compare_verified_pair_freshness(candidate, previous)
    if decision == "already-current":
        return TransactionPlan(previous, candidate, (), True)
    # Supervisor first matches accepted historical handoff, with explicit
    # recovery rather than the old one-way sequence-specific dispatcher.
    return TransactionPlan(previous, candidate, (
        _step("supervisor", previous.supervisor_digest, candidate.supervisor_digest, "target"),
        _step("full", previous.full_digest, candidate.full_digest, "target"),
    ), False)


def plan_interrupted_recovery(plan: TransactionPlan,
                              observed: PointerSnapshot) -> RecoveryPlan:
    """Compute conservative prior-state restoration, NEVER write anything.

    If a third-party writer changed either tag to anything other than our
    exact previous or target digest, refuse automatic compensation: we cannot
    prove which actor owns that change.
    """
    if not isinstance(plan, TransactionPlan) or not isinstance(observed, PointerSnapshot):
        raise ReleaseRefusal("missing verified recovery transaction evidence")
    p, t = _snapshot(plan.previous), _snapshot(plan.target)
    if plan.no_op and observed != p:
        raise ReleaseRefusal("no-op release unexpectedly changed stable pointers")
    for field in ("full_digest", "supervisor_digest"):
        value = getattr(observed, field)
        if value not in (getattr(p, field), getattr(t, field)):
            raise ReleaseRefusal("unknown concurrent pointer: stop for manual repair")
    if observed == p:
        return RecoveryPlan("already-previous", ())
    steps = []
    # Reverse the promotion order: first full then Supervisor, only when
    # that pointer currently equals our exact target digest.
    if observed.full_digest == t.full_digest:
        steps.append(_step("full", t.full_digest, p.full_digest, "previous"))
    if observed.supervisor_digest == t.supervisor_digest:
        steps.append(_step("supervisor", t.supervisor_digest, p.supervisor_digest, "previous"))
    return RecoveryPlan("requires-compensation", tuple(steps))


def confirm_compensation(previous: Pair, observed: PointerSnapshot) -> None:
    """Only exact prior pair readback completes recovery; no soft success."""
    if not isinstance(previous, Pair) or not isinstance(observed, PointerSnapshot):
        raise ReleaseRefusal("invalid compensation receipt evidence")
    if observed != _snapshot(previous):
        raise ReleaseRefusal("compensation incomplete: require manual repair and block releases")


def confirm_committed_target(plan: TransactionPlan,
                             observed: PointerSnapshot,
                             *, approved_and_audited: bool = False) -> None:
    """Final state alone cannot substitute for external approved audit receipt."""
    if not isinstance(plan, TransactionPlan) or not isinstance(observed, PointerSnapshot):
        raise ReleaseRefusal("invalid final release receipt evidence")
    if not approved_and_audited:
        raise ReleaseRefusal("no authorized durable release audit receipt")
    if observed != _snapshot(plan.target):
        raise ReleaseRefusal("both stable pointers must equal the approved immutable target")
