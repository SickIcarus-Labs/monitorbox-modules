"""Current moving-pointer observation: 2x GET, pinned layer proof, no tag writes."""
from datetime import timedelta
from types import MethodType

import pytest

from successor_registry_extract import FULL_REPO, SUPERVISOR_REPO, ReleaseRefusal
from successor_stable_witness import observe_current_stable_pair
from test_successor_registry_extract import registry_candidate, NOW


def provider_from_candidate(value):
    provider, manifest, fixture = value
    stable = {
        FULL_REPO: manifest["images"]["full"]["digest"],
        SUPERVISOR_REPO: manifest["images"]["supervisor"]["digest"],
    }
    observed = []
    def resolve(repo):
        observed.append(repo)
        return stable[repo]
    provider.resolve_stable_digest = resolve
    return provider, fixture, stable, observed


def test_readonly_current_two_tag_pair_is_cryptographically_verified(registry_candidate):
    provider, fixture, stable, observed = provider_from_candidate(registry_candidate)
    witness = observe_current_stable_pair(provider, keys=fixture["keys"], now=NOW)
    assert witness.pair.sequence == 10
    assert witness.pair.full_digest == stable[FULL_REPO]
    assert witness.pair.supervisor_digest == stable[SUPERVISOR_REPO]
    assert observed == [FULL_REPO, SUPERVISOR_REPO, FULL_REPO, SUPERVISOR_REPO]
    assert all(call[0] in ("GET_MANIFEST", "GET_BLOB") for call in provider.calls)


def test_expired_but_genuinely_signed_previous_catalog_can_establish_order(registry_candidate):
    provider, fixture, _, _ = provider_from_candidate(registry_candidate)
    historical = NOW + timedelta(days=90)
    witness = observe_current_stable_pair(provider, keys=fixture["keys"], now=historical)
    assert witness.pair.sequence == 10


def test_reject_concurrent_mutable_tag_change(registry_candidate):
    provider, fixture, stable, _ = provider_from_candidate(registry_candidate)
    n = [0]
    def resolving(repo):
        n[0] += 1
        if n[0] == 3:
            return "sha256:" + "f" * 64  # second full stable GET drifts
        return stable[repo]
    provider.resolve_stable_digest = resolving
    with pytest.raises(ReleaseRefusal, match="changed during"):
        observe_current_stable_pair(provider, keys=fixture["keys"], now=NOW)


def test_reject_architecture_package_tampering_in_existing_stable(registry_candidate):
    provider, fixture, _, _ = provider_from_candidate(registry_candidate)
    for (repo, digest), data in list(provider.blobs.items()):
        if repo == FULL_REPO and data[:2] == b"\x1f\x8b":
            provider.blobs[(repo, digest)] = data + b"tamper"
            break
    with pytest.raises(ReleaseRefusal):
        observe_current_stable_pair(provider, keys=fixture["keys"], now=NOW)


def test_reject_missing_second_current_pointer(registry_candidate):
    provider, fixture, stable, _ = provider_from_candidate(registry_candidate)
    def broken(repo):
        if repo == SUPERVISOR_REPO:
            raise ReleaseRefusal("missing current stable Supervisor")
        return stable[repo]
    provider.resolve_stable_digest = broken
    with pytest.raises(ReleaseRefusal, match="missing current"):
        observe_current_stable_pair(provider, keys=fixture["keys"], now=NOW)


def test_stable_witness_has_no_mutating_registry_capabilities():
    from pathlib import Path
    raw = (Path(__file__).parent / "successor_stable_witness.py").read_text()
    assert "docker buildx imagetools create" not in raw
    assert "subprocess" not in raw
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in raw
