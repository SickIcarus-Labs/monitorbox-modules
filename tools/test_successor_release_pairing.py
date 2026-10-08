"""Exercise the ACTUAL successor release topology using ephemeral Ed25519 keys."""
import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from successor_release_pairing import (
    Feed, SupervisorFeed, Pair, ReleaseRefusal, evaluate_promotion, verified_pair,
    compare_verified_pair_freshness,
)
from verify_platform_index import canonical

NOW = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"


def artifact(name, arch, *, digit="a"):
    return {
        "artifact_id": name,
        "kind": "scaffold-manager" if name == MANAGER else "runtime",
        "version": "1.0.0", "build": 4,
        "platform": {"os": "linux", "arch": arch, "abi": "static"},
        "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
        "dependencies": [],
        "package": {
            "url": "platform/packages/" + ("manager" if name == MANAGER else "runtime") + "-" + arch + ".zip",
            "sha256": digit * 64,
            "size": 1234,
            "signature": {
                "algorithm": "ed25519", "identity": "official-ed25519-1",
                "value": base64.b64encode(b"s" * 64).decode(),
            },
        },
    }


def signed_index(key, seq, items, issue, expires):
    signed = {
        "repository_id": "official-platform", "channel": "stable",
        "sequence": seq, "generated_at": issue.isoformat(),
        "expires_at": expires.isoformat(), "artifacts": items,
    }
    return canonical({
        "schema": 1, "signed": signed,
        "signature": {
            "algorithm": "ed25519", "identity": "official-ed25519-1",
            "value": base64.b64encode(key.sign(canonical(signed))).decode(),
        },
    })


def fixtures(seq, *, key, full_digit="1", supervisor_digit="2",
             issue=None, expires=None, manager_digit="a", supervisor_manager_digit=None):
    issue = issue or (NOW - timedelta(hours=1))
    expires = expires or (NOW + timedelta(days=1))
    managers = {
        arch: artifact(MANAGER, arch, digit=manager_digit)
        for arch in ("amd64", "arm64")
    }
    full_artifacts = list(managers.values()) + [
        artifact("com.sickicarus.monitorbox.python-runtime", "amd64"),
    ]
    full = Feed("sha256:" + full_digit * 64,
                signed_index(key, seq, full_artifacts, issue, expires))
    # Production: each platform image carries ONLY its own signed manager index.
    sup_index = {
        arch: signed_index(
            key, seq,
            [artifact(MANAGER, arch, digit=supervisor_manager_digit or manager_digit)],
            issue, expires,
        )
        for arch in ("amd64", "arm64")
    }
    supervisor = SupervisorFeed("sha256:" + supervisor_digit * 64, sup_index)
    return full, supervisor


@pytest.fixture
def trusted():
    key = Ed25519PrivateKey.generate()
    return key, {"official-ed25519-1": key.public_key()}


def evaluate(trusted, *, target_seq=10, current_seq=9,
             target_digits=("3", "4"), current_digits=("1", "2")):
    key, keys = trusted
    full, sup = fixtures(target_seq, key=key, full_digit=target_digits[0],
                         supervisor_digit=target_digits[1])
    current_full, current_sup = fixtures(current_seq, key=key,
                                        full_digit=current_digits[0],
                                        supervisor_digit=current_digits[1])
    return evaluate_promotion(candidate_full=full, candidate_supervisor=sup,
                              current_full=current_full, current_supervisor=current_sup,
                              keys=keys, now=NOW)


def test_real_sequence9_shape_has_full_and_two_distinct_signed_manager_indexes(trusted):
    key, keys = trusted
    full, supervisor = fixtures(9, key=key)
    assert len(json.loads(full.signed_index)["signed"]["artifacts"]) == 3
    assert set(supervisor.signed_indexes) == {"amd64", "arm64"}
    for arch in supervisor.signed_indexes:
        record = json.loads(supervisor.signed_indexes[arch])["signed"]["artifacts"]
        assert len(record) == 1
        assert record[0]["platform"]["arch"] == arch
    assert verified_pair(full, supervisor, keys=keys, now=NOW).sequence == 9


def test_newer_valid_signed_pair_is_read_only_candidate(trusted):
    decision, pair = evaluate(trusted)
    assert decision == "promote"
    assert pair.sequence == 10
    assert pair.full_digest == "sha256:" + "3" * 64
    assert pair.supervisor_digest == "sha256:" + "4" * 64


def test_exact_same_pair_is_idempotent(trusted):
    decision, pair = evaluate(trusted, target_seq=9, target_digits=("1", "2"))
    assert decision == "already-current" and pair.sequence == 9


@pytest.mark.parametrize("new,old", [(8, 9), (1, 12)])
def test_signed_downgrade_rejected(trusted, new, old):
    with pytest.raises(ReleaseRefusal, match="downgrade"):
        evaluate(trusted, target_seq=new, current_seq=old)


def test_same_sequence_different_digest_rejected(trusted):
    with pytest.raises(ReleaseRefusal, match="same-sequence"):
        evaluate(trusted, target_seq=9)


@pytest.mark.parametrize("bad_arch", ["amd64", "arm64"])
def test_mixed_sequence_per_architecture_fails(trusted, bad_arch):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    _, old_sup = fixtures(9, key=key)
    corrupt = dict(sup.signed_indexes)
    corrupt[bad_arch] = old_sup.signed_indexes[bad_arch]
    with pytest.raises(ReleaseRefusal, match="sequence mismatch"):
        verified_pair(full, SupervisorFeed(sup.digest, corrupt), keys=keys, now=NOW)


@pytest.mark.parametrize("bad_arch", ["amd64", "arm64"])
def test_wrong_manager_package_per_architecture_rejected(trusted, bad_arch):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    _, other = fixtures(10, key=key, supervisor_manager_digit="f")
    mixed = dict(sup.signed_indexes)
    mixed[bad_arch] = other.signed_indexes[bad_arch]
    with pytest.raises(ReleaseRefusal, match="does not exactly match"):
        verified_pair(full, SupervisorFeed(sup.digest, mixed), keys=keys, now=NOW)


@pytest.mark.parametrize("missing", ["amd64", "arm64"])
def test_missing_architectural_index_fails_closed(trusted, missing):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    shortened = dict(sup.signed_indexes)
    del shortened[missing]
    with pytest.raises(ReleaseRefusal, match="exactly amd64 and arm64"):
        verified_pair(full, SupervisorFeed(sup.digest, shortened), keys=keys, now=NOW)


def test_forged_two_manager_supervisor_index_rejected(trusted):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    # Regression: old #163 synthetic-only topology was never a real OCI artifact.
    with pytest.raises(ReleaseRefusal, match="per-architecture"):
        verified_pair(full, Feed(sup.digest, full.signed_index), keys=keys, now=NOW)


def test_wrong_architecture_manager_in_platform_index_fails(trusted):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    index = sup.signed_indexes["amd64"]
    doc = json.loads(index)
    doc["signed"]["artifacts"][0]["platform"]["arch"] = "arm64"
    doc["signature"]["value"] = base64.b64encode(key.sign(canonical(doc["signed"]))).decode()
    bad = dict(sup.signed_indexes)
    bad["amd64"] = canonical(doc)
    with pytest.raises(ReleaseRefusal, match="wrong Supervisor manager"):
        verified_pair(full, SupervisorFeed(sup.digest, bad), keys=keys, now=NOW)


def test_reject_unsigned_catalog_mutation(trusted):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    doc = json.loads(sup.signed_indexes["arm64"])
    doc["signed"]["sequence"] = 11
    bad = dict(sup.signed_indexes)
    bad["arm64"] = canonical(doc)
    with pytest.raises(ReleaseRefusal, match="untrusted"):
        verified_pair(full, SupervisorFeed(sup.digest, bad), keys=keys, now=NOW)


def test_bad_digest_fails_before_any_promotion(trusted):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    with pytest.raises(ReleaseRefusal, match="immutable"):
        verified_pair(Feed("stable", full.signed_index), sup, keys=keys, now=NOW)
    with pytest.raises(ReleaseRefusal, match="immutable"):
        verified_pair(full, SupervisorFeed("sha256:" + "f" * 63, sup.signed_indexes),
                      keys=keys, now=NOW)


def test_expired_candidate_fails_but_expired_signed_current_orders(trusted):
    key, keys = trusted
    old = fixtures(9, key=key, issue=NOW - timedelta(days=10),
                   expires=NOW - timedelta(days=3))
    with pytest.raises(ReleaseRefusal, match="untrusted"):
        verified_pair(*old, keys=keys, now=NOW)
    new = fixtures(11, key=key)
    decision, pair = evaluate_promotion(
        candidate_full=new[0], candidate_supervisor=new[1],
        current_full=old[0], current_supervisor=old[1],
        keys=keys, now=NOW)
    assert decision == "promote" and pair.sequence == 11


def test_divergent_current_pair_fails_before_promotion(trusted):
    key, keys = trusted
    target = fixtures(10, key=key)
    old_a = fixtures(9, key=key)
    old_b = fixtures(8, key=key)
    with pytest.raises(ReleaseRefusal, match="sequence mismatch"):
        evaluate_promotion(candidate_full=target[0], candidate_supervisor=target[1],
                           current_full=old_a[0], current_supervisor=old_b[1],
                           keys=keys, now=NOW)


def test_readonly_exact_digest_pair_monotonic_preflight():
    old = Pair(9, "sha256:" + "1" * 64, "sha256:" + "2" * 64)
    new = Pair(10, "sha256:" + "3" * 64, "sha256:" + "4" * 64)
    assert compare_verified_pair_freshness(new, old) == "newer-candidate"
    assert compare_verified_pair_freshness(old, old) == "already-current"
    with pytest.raises(ReleaseRefusal, match="downgrade"):
        compare_verified_pair_freshness(old, new)
    with pytest.raises(ReleaseRefusal, match="same-sequence"):
        compare_verified_pair_freshness(
            Pair(9, "sha256:" + "3" * 64, old.supervisor_digest), old)
    with pytest.raises(ReleaseRefusal, match="reused"):
        compare_verified_pair_freshness(
            Pair(10, old.full_digest, new.supervisor_digest), old)
    with pytest.raises(ReleaseRefusal, match="reused"):
        compare_verified_pair_freshness(
            Pair(10, new.full_digest, old.supervisor_digest), old)


def test_operator_cli_labels_preflight_as_non_authorizing():
    from pathlib import Path
    source = (Path(__file__).parent / "successor_registry_readonly_cli.py").read_text("utf-8")
    assert "--check-current-stable" in source
    assert "compare_verified_pair_freshness" in source
    assert '"publication_authorized": False' in source
    assert '"channel_changed": False' in source
    assert '"stable_pair_checked": stable is not None' in source
