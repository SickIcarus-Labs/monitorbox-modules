"""Read-only promotion admission tests. No GHCR login, registry writes or secret access."""
import base64
import copy
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from successor_release_pairing import Feed, ReleaseRefusal, evaluate_promotion, verified_pair
from verify_platform_index import canonical

NOW = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"


def artifact(name, arch, *, sha_digit="a"):
    return {
        "artifact_id": name,
        "kind": "scaffold-manager" if name == MANAGER else "runtime",
        "version": "1.0.0",
        "build": 4,
        "platform": {"os": "linux", "arch": arch, "abi": "static"},
        "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
        "dependencies": [],
        "package": {
            "url": "platform/packages/" + ("manager" if name == MANAGER else "runtime") + "-" + arch + ".zip",
            "sha256": sha_digit * 64,
            "size": 1234,
            "signature": {"algorithm": "ed25519", "identity": "official-ed25519-1",
                          "value": base64.b64encode(b"s" * 64).decode()},
        },
    }


def fixtures(seq, *, key, full_digit="1", supervisor_digit="2",
             issue=None, expires=None, manager_digit="a"):
    issue = issue or (NOW - timedelta(hours=1))
    expires = expires or (NOW + timedelta(days=1))
    managers = [artifact(MANAGER, arch, sha_digit=manager_digit) for arch in ("amd64", "arm64")]
    full = managers + [artifact("com.sickicarus.monitorbox.python-runtime", "amd64")]
    def sign(items):
        signed = {"repository_id": "official-platform", "channel": "stable",
                  "sequence": seq,
                  "generated_at": issue.isoformat(),
                  "expires_at": expires.isoformat(),
                  "artifacts": items}
        sig = base64.b64encode(key.sign(canonical(signed))).decode()
        return canonical({"schema": 1, "signed": signed,
                          "signature": {"algorithm": "ed25519",
                                        "identity": "official-ed25519-1", "value": sig}})
    return (Feed("sha256:" + full_digit * 64, sign(full)),
            Feed("sha256:" + supervisor_digit * 64, sign(managers)))


@pytest.fixture
def trusted():
    key = Ed25519PrivateKey.generate()
    keys = {"official-ed25519-1": key.public_key()}
    return key, keys


def evaluate(trusted, *, target_seq=10, current_seq=9,
             target_digits=("3", "4"), current_digits=("1", "2")):
    key, keys = trusted
    target = fixtures(target_seq, key=key, full_digit=target_digits[0],
                      supervisor_digit=target_digits[1])
    current = fixtures(current_seq, key=key, full_digit=current_digits[0],
                       supervisor_digit=current_digits[1])
    return evaluate_promotion(candidate_full=target[0], candidate_supervisor=target[1],
                              current_full=current[0], current_supervisor=current[1],
                              keys=keys, now=NOW)


def test_qualified_signed_newer_pair_may_be_proposed_but_does_not_publish(trusted):
    decision, pair = evaluate(trusted)
    assert decision == "promote"
    assert pair.sequence == 10
    assert pair.full_digest == "sha256:" + "3" * 64
    assert pair.supervisor_digest == "sha256:" + "4" * 64


def test_idempotent_exact_pair_is_not_republished(trusted):
    decision, pair = evaluate(trusted, target_seq=9,
                              target_digits=("1", "2"))
    assert decision == "already-current"
    assert pair.sequence == 9


@pytest.mark.parametrize("candidate,previous", [(8, 9), (1, 12)])
def test_reject_catalog_rollback_even_when_validly_signed(trusted, candidate, previous):
    with pytest.raises(ReleaseRefusal, match="downgrade"):
        evaluate(trusted, target_seq=candidate, current_seq=previous)


def test_reject_same_sequence_alternate_digest(trusted):
    with pytest.raises(ReleaseRefusal, match="same-sequence"):
        evaluate(trusted, target_seq=9)


def test_reject_mixed_sequence_pair_even_if_separately_signed(trusted):
    key, keys = trusted
    full = fixtures(10, key=key)[0]
    sup = fixtures(9, key=key)[1]
    with pytest.raises(ReleaseRefusal, match="mismatch"):
        verified_pair(full, sup, keys=keys, now=NOW)


def test_reject_supervisor_manager_package_disagreement(trusted):
    key, keys = trusted
    full = fixtures(10, key=key)[0]
    sup = fixtures(10, key=key, manager_digit="f")[1]
    with pytest.raises(ReleaseRefusal, match="does not exactly match"):
        verified_pair(full, sup, keys=keys, now=NOW)


def test_reject_missing_supervisor_architecture(trusted):
    key, keys = trusted
    full, supervisor = fixtures(10, key=key)
    doc = __import__("json").loads(supervisor.signed_index)
    doc["signed"]["artifacts"].pop()
    doc["signature"]["value"] = base64.b64encode(key.sign(canonical(doc["signed"]))).decode()
    supervisor = Feed(supervisor.digest, canonical(doc))
    with pytest.raises(ReleaseRefusal, match="only its two"):
        verified_pair(full, supervisor, keys=keys, now=NOW)


def test_reject_invalid_catalog_signature(trusted):
    key, keys = trusted
    full, supervisor = fixtures(10, key=key)
    doc = __import__("json").loads(full.signed_index)
    doc["signed"]["sequence"] = 12  # signature deliberately not regenerated
    with pytest.raises(ReleaseRefusal, match="untrusted"):
        verified_pair(Feed(full.digest, canonical(doc)), supervisor, keys=keys, now=NOW)


def test_reject_untrusted_malformed_image_digest(trusted):
    key, keys = trusted
    full, sup = fixtures(10, key=key)
    with pytest.raises(ReleaseRefusal, match="immutable"):
        verified_pair(Feed("stable", full.signed_index), sup, keys=keys, now=NOW)
    with pytest.raises(ReleaseRefusal, match="immutable"):
        verified_pair(Feed("sha256:" + "f" * 63, full.signed_index), sup, keys=keys, now=NOW)


def test_expired_target_fails_but_old_signed_current_still_orders(trusted):
    key, keys = trusted
    expired = fixtures(10, key=key, issue=NOW - timedelta(days=10),
                       expires=NOW - timedelta(days=3))
    current = fixtures(9, key=key, issue=NOW - timedelta(days=10),
                       expires=NOW - timedelta(days=3))
    with pytest.raises(ReleaseRefusal, match="untrusted"):
        verified_pair(*expired, keys=keys, now=NOW)
    fresh = fixtures(11, key=key)
    decision, result = evaluate_promotion(
        candidate_full=fresh[0], candidate_supervisor=fresh[1],
        current_full=current[0], current_supervisor=current[1],
        keys=keys, now=NOW)
    assert decision == "promote" and result.sequence == 11


def test_reject_current_pair_divergence_before_promotion(trusted):
    key, keys = trusted
    target = fixtures(10, key=key)
    current_full = fixtures(9, key=key)[0]
    current_sup = fixtures(8, key=key)[1]
    with pytest.raises(ReleaseRefusal, match="mismatch"):
        evaluate_promotion(candidate_full=target[0], candidate_supervisor=target[1],
                           current_full=current_full, current_supervisor=current_sup,
                           keys=keys, now=NOW)
