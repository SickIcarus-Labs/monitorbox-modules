"""Exhaustive two-pointer read-only intent/compensation model tests."""
from itertools import product
from pathlib import Path

import pytest

from successor_release_pairing import Pair, ReleaseRefusal
from successor_promotion_recovery_model import (
    PointerSnapshot, prepare_transaction, plan_interrupted_recovery,
    confirm_compensation, confirm_committed_target,
)

PREVIOUS = Pair(9, "sha256:" + "1"*64, "sha256:" + "2"*64)
TARGET = Pair(10, "sha256:" + "3"*64, "sha256:" + "4"*64)
CURRENT = PointerSnapshot(PREVIOUS.full_digest, PREVIOUS.supervisor_digest)
SUCCESS = PointerSnapshot(TARGET.full_digest, TARGET.supervisor_digest)


def test_qualified_newer_pair_has_explicit_supervisor_then_full_sequence():
    p = prepare_transaction(PREVIOUS, TARGET, CURRENT)
    assert not p.no_op
    assert tuple(x.role for x in p.transition) == ("supervisor", "full")
    assert tuple(x.desired for x in p.transition) == ("target", "target")
    assert p.transition[0].expected_previous_digest == PREVIOUS.supervisor_digest
    assert p.transition[1].replacement_digest == TARGET.full_digest


@pytest.mark.parametrize("full_new,supervisor_new", list(product((False, True), repeat=2)))
def test_all_four_possible_interrupted_pointer_states_restore_prior(
    full_new, supervisor_new,
):
    intent = prepare_transaction(PREVIOUS, TARGET, CURRENT)
    observed = PointerSnapshot(
        TARGET.full_digest if full_new else PREVIOUS.full_digest,
        TARGET.supervisor_digest if supervisor_new else PREVIOUS.supervisor_digest,
    )
    recovery = plan_interrupted_recovery(intent, observed)
    assert recovery.state == (
        "requires-compensation" if full_new or supervisor_new else "already-previous"
    )
    assert [x.role for x in recovery.recovery] == (
        (["full"] if full_new else []) + (["supervisor"] if supervisor_new else [])
    )
    final = {"full": observed.full_digest, "supervisor": observed.supervisor_digest}
    for step in recovery.recovery:
        assert final[step.role] == step.expected_previous_digest
        final[step.role] = step.replacement_digest
    confirm_compensation(PREVIOUS, PointerSnapshot(final["full"], final["supervisor"]))


@pytest.mark.parametrize("role", ["full", "supervisor"])
def test_third_party_unknown_pointer_is_not_overwritten_during_compensation(role):
    intent = prepare_transaction(PREVIOUS, TARGET, CURRENT)
    state = dict(full_digest=PREVIOUS.full_digest,
                 supervisor_digest=TARGET.supervisor_digest)
    state[role + "_digest"] = "sha256:" + "f"*64
    with pytest.raises(ReleaseRefusal, match="unknown concurrent pointer"):
        plan_interrupted_recovery(intent, PointerSnapshot(**state))


def test_stale_prior_readback_refuses_proposed_promotion():
    with pytest.raises(ReleaseRefusal, match="drifted"):
        prepare_transaction(PREVIOUS, TARGET,
                            PointerSnapshot(TARGET.full_digest, PREVIOUS.supervisor_digest))


@pytest.mark.parametrize("other", [
    Pair(8, TARGET.full_digest, TARGET.supervisor_digest),
    Pair(9, TARGET.full_digest, TARGET.supervisor_digest),
    Pair(10, PREVIOUS.full_digest, TARGET.supervisor_digest),
    Pair(10, TARGET.full_digest, PREVIOUS.supervisor_digest),
])
def test_refuse_rollback_equivocation_and_old_image_reuse(other):
    with pytest.raises(ReleaseRefusal):
        prepare_transaction(PREVIOUS, other, CURRENT)


def test_exact_current_pair_is_noop():
    p = prepare_transaction(PREVIOUS, PREVIOUS, CURRENT)
    assert p.no_op and p.transition == ()
    assert plan_interrupted_recovery(p, CURRENT).state == "already-previous"
    with pytest.raises(ReleaseRefusal, match="no-op"):
        plan_interrupted_recovery(p, SUCCESS)


def test_torn_compensation_never_gets_success_receipt():
    for observed in (
        PointerSnapshot(TARGET.full_digest, PREVIOUS.supervisor_digest),
        PointerSnapshot(PREVIOUS.full_digest, TARGET.supervisor_digest),
        SUCCESS,
    ):
        with pytest.raises(ReleaseRefusal, match="compensation incomplete"):
            confirm_compensation(PREVIOUS, observed)


def test_final_promoted_pair_does_not_count_without_external_approval_and_audit():
    intent = prepare_transaction(PREVIOUS, TARGET, CURRENT)
    with pytest.raises(ReleaseRefusal, match="durable release audit"):
        confirm_committed_target(intent, SUCCESS)
    with pytest.raises(ReleaseRefusal, match="both stable pointers"):
        confirm_committed_target(intent, CURRENT, approved_and_audited=True)
    confirm_committed_target(intent, SUCCESS, approved_and_audited=True)


def test_model_is_pure_with_no_oci_registry_writer_or_signer_access():
    raw = (Path(__file__).parent / "successor_promotion_recovery_model.py").read_text()
    for forbidden in ("subprocess", "urllib", "requests", "imagetools create",
                      "docker push", "packages: write", "MONITORBOX_MODULE_SIGNING_KEY"):
        assert forbidden not in raw
