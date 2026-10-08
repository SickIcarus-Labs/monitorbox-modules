"""Read-only, double-observed, signed current GHCR stable pair witness.

This is not a mutex, write authorization or a two-tag atomic transaction.
A publisher MUST separately obtain exclusive authority, re-observe both
pointers immediately before writing, and compensate on partial failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tempfile
from typing import Mapping, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from successor_registry_extract import (
    FULL_REPO, SUPERVISOR_REPO, CATALOG, MAX_JSON,
    ReadOnlyRegistry, _verified_platform_image, _compare_full_architectures,
)
from successor_release_pairing import (
    ARCHES, Feed, SupervisorFeed, Pair, ReleaseRefusal, verified_pair,
)
from successor_release_manifest import _verify_package_closure
from verify_platform_index import _parse


class StableReader(ReadOnlyRegistry, Protocol):
    def resolve_stable_digest(self, repository: str) -> str: ...


@dataclass(frozen=True)
class StableWitness:
    pair: Pair
    full: Feed
    supervisor: SupervisorFeed


def _pointers(provider: StableReader) -> tuple[str, str]:
    return (
        provider.resolve_stable_digest(FULL_REPO),
        provider.resolve_stable_digest(SUPERVISOR_REPO),
    )


def _check_current_provenance(labels: Mapping, pair: Pair) -> None:
    full = labels["full"]
    supervisor = labels["supervisor"]
    if set(full) != ARCHES or set(supervisor) != ARCHES:
        raise ReleaseRefusal("current stable OCI image lacks an architecture")
    for arch in ARCHES:
        a, b = full[arch], supervisor[arch]
        for role, observed, expected in (
            ("full", a, "successor-physical-acceptance-feed"),
            ("supervisor", b, "successor-supervisor-bootstrap-feed"),
        ):
            if (observed.get("com.sickicarus.monitorbox.catalog-sequence") !=
                    str(pair.sequence) or
                    observed.get("com.sickicarus.monitorbox.artifact-class") != expected):
                raise ReleaseRefusal("current stable OCI provenance/sequence mismatch")
        for identity in (
            "org.opencontainers.image.revision",
            "com.sickicarus.monitorbox.core-source",
        ):
            if not a.get(identity) or a[identity] != b.get(identity):
                raise ReleaseRefusal("current full/Supervisor source provenance differs")
    for role in (full, supervisor):
        if role["amd64"].get("org.opencontainers.image.revision") != (
                role["arm64"].get("org.opencontainers.image.revision")):
            raise ReleaseRefusal("current stable architectures have different source revisions")


def observe_current_stable_pair(provider: StableReader, *,
                                keys: Mapping[str, Ed25519PublicKey],
                                now: datetime | None = None) -> StableWitness:
    """Witness current full/Supervisor stable identities; no tag mutation.

    Historical current signed catalogs may be expired; signatures, signed
    publication ordering, exact per-arch manager closure and ZIP bytes must
    remain verifiable. Double read detects ordinary concurrent pointer drift,
    but not all ABA races. Exclusive publication serialization is still needed.
    """
    start = _pointers(provider)
    with tempfile.TemporaryDirectory(prefix="mb-stable-readonly-") as temp:
        root = Path(temp)
        full_labels, full_roots = _verified_platform_image(
            provider, FULL_REPO, start[0], root / "full")
        supervisor_labels, sup_roots = _verified_platform_image(
            provider, SUPERVISOR_REPO, start[1], root / "supervisor")
        _compare_full_architectures(full_roots)

        signed_full = (full_roots["amd64"] / CATALOG).read_bytes()
        if len(signed_full) > MAX_JSON:
            raise ReleaseRefusal("current stable signed index too large")
        indexes = {}
        for arch in ARCHES:
            index = sup_roots[arch] / CATALOG
            if index.stat().st_size > MAX_JSON:
                raise ReleaseRefusal("current Supervisor index too large")
            indexes[arch] = index.read_bytes()
        full = Feed(start[0], signed_full)
        supervisor = SupervisorFeed(start[1], indexes)
        pair = verified_pair(full, supervisor, keys=keys, now=now, historical=True)
        _check_current_provenance({"full": full_labels, "supervisor": supervisor_labels}, pair)

        _verify_package_closure(_parse(full.signed_index), full_roots["amd64"], keys)
        for arch in ARCHES:
            _verify_package_closure(_parse(indexes[arch]), sup_roots[arch], keys)
        end = _pointers(provider)
        if end != start:
            raise ReleaseRefusal("current stable pointers changed during read-only observation")
        return StableWitness(pair, full, supervisor)
