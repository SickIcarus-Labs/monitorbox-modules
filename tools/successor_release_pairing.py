"""Read-only signed feed pairing and anti-rollback admission.

Real successor layout: one multi-architecture full signed catalog, plus ONE
independently signed Supervisor manager-only catalog PER architecture inside
the Supervisor multi-architecture OCI image. A synthetic two-manager Supervisor
index is NOT a production artifact and must never be accepted.

This module does not retrieve GHCR images, verify the OCI manifest or package
bytes, authorize a release, or write tags. Its caller must obtain all evidence
from immutable registry references and enforce the separate release gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from verify_platform_index import VerificationError, _parse, _date, verify_index

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"
ARCHES = frozenset(("amd64", "arm64"))


class ReleaseRefusal(ValueError):
    """Reject unsigned/mixed/incomplete/stale release selection."""


@dataclass(frozen=True)
class Feed:
    """Full OCI digest and the exact signed catalog retrieved from that image."""
    digest: str
    signed_index: bytes


@dataclass(frozen=True)
class SupervisorFeed:
    """OCI digest with exact architecture-specific signed catalog bytes.

    The caller MUST extract these from each platform of the same digest-pinned
    OCI image, not separate tags or requester-supplied paths.
    """
    digest: str
    signed_indexes: Mapping[str, bytes]


@dataclass(frozen=True)
class Pair:
    sequence: int
    full_digest: str
    supervisor_digest: str


def _catalog(feed: Feed, keys: Mapping[str, Ed25519PublicKey], *,
             now: datetime, historical: bool = False) -> dict:
    if not isinstance(feed.digest, str) or DIGEST.fullmatch(feed.digest) is None:
        raise ReleaseRefusal("feed reference must use one immutable sha256 digest")
    if not isinstance(feed.signed_index, bytes):
        raise ReleaseRefusal("signed index must be exact retrieved UTF-8 bytes")
    try:
        # Previous stable may be past its catalog expiry. Validate its Ed25519
        # signature and signed issue-time for monotonic ordering, WITHOUT
        # treating historical contents as a valid new installation candidate.
        check_time = now
        if historical:
            document = _parse(feed.signed_index)
            if not isinstance(document, dict):
                raise ReleaseRefusal("invalid historical signed index")
            check_time = _date(document["signed"]["generated_at"])
        return verify_index(feed.signed_index, keys=dict(keys),
                            channel="stable", now=check_time)
    except (VerificationError, KeyError, TypeError, IndexError, ValueError) as exc:
        raise ReleaseRefusal("untrusted, expired, or invalid signed catalog") from exc


def _full_managers(index: dict) -> dict:
    found = {}
    for item in index["artifacts"]:
        if item["artifact_id"] != MANAGER:
            continue
        platform = item["platform"]
        if (item["kind"] != "scaffold-manager" or
                platform["os"] != "linux" or platform["abi"] != "static"):
            raise ReleaseRefusal("unsafe full-feed Supervisor manager")
        arch = platform["arch"]
        if arch not in ARCHES or arch in found:
            raise ReleaseRefusal("duplicate/unexpected full-feed Supervisor manager")
        found[arch] = item
    if set(found) != ARCHES:
        raise ReleaseRefusal("full feed must contain exactly one manager per architecture")
    return found


def verified_pair(full: Feed, supervisor: SupervisorFeed, *,
                  keys: Mapping[str, Ed25519PublicKey],
                  now: datetime | None = None, historical: bool = False) -> Pair:
    """Check exact signed full/Supervisor manager closure on both architectures.

    No registry reads or package-byte verification occur here.
    """
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ReleaseRefusal("validation clock must be timezone aware")
    if not isinstance(supervisor, SupervisorFeed):
        raise ReleaseRefusal("Supervisor must provide per-architecture signed catalogs")
    if not isinstance(supervisor.signed_indexes, Mapping) or set(supervisor.signed_indexes) != ARCHES:
        raise ReleaseRefusal("Supervisor signed catalog set must be exactly amd64 and arm64")
    if full.digest == supervisor.digest:
        raise ReleaseRefusal("full/Supervisor require distinct immutable images")
    complete = _catalog(full, keys, now=instant, historical=historical)
    managers = _full_managers(complete)
    if len(complete["artifacts"]) <= len(managers):
        raise ReleaseRefusal("full feed contains no application/runtime closure")

    for arch in sorted(ARCHES):
        signed = _catalog(Feed(supervisor.digest, supervisor.signed_indexes[arch]),
                          keys, now=instant, historical=historical)
        if signed["sequence"] != complete["sequence"]:
            raise ReleaseRefusal("full/Supervisor signed catalog sequence mismatch")
        artifacts = signed["artifacts"]
        if len(artifacts) != 1:
            raise ReleaseRefusal("architecture-specific Supervisor catalog must contain one manager")
        manager = artifacts[0]
        platform = manager["platform"]
        if (manager["artifact_id"] != MANAGER or
                manager["kind"] != "scaffold-manager" or
                platform["os"] != "linux" or platform["arch"] != arch or
                platform["abi"] != "static"):
            raise ReleaseRefusal("wrong Supervisor manager identity/architecture")
        if manager != managers[arch]:
            raise ReleaseRefusal("Supervisor manager does not exactly match full feed")
    return Pair(complete["sequence"], full.digest, supervisor.digest)


def evaluate_promotion(*, candidate_full: Feed, candidate_supervisor: SupervisorFeed,
                       current_full: Feed, current_supervisor: SupervisorFeed,
                       keys: Mapping[str, Ed25519PublicKey],
                       now: datetime | None = None) -> tuple[str, Pair]:
    """Return ('promote' | 'already-current', pair) without registry mutation.

    Inputs describing current stable MUST be fresh, trusted GHCR readbacks, not
    requester assertions. Callers must ALSO establish complete signed ZIP
    closure, provenance/SHA, immutable OCI architecture manifest, exclusive
    publication lock, actor approval and post-write readback/compensation.
    """
    instant = now or datetime.now(timezone.utc)
    target = verified_pair(candidate_full, candidate_supervisor, keys=keys, now=instant)
    previous = verified_pair(current_full, current_supervisor, keys=keys,
                             now=instant, historical=True)
    if target.sequence < previous.sequence:
        raise ReleaseRefusal("signed catalog downgrade refused")
    if target.sequence == previous.sequence:
        if (target.full_digest == previous.full_digest and
                target.supervisor_digest == previous.supervisor_digest):
            return ("already-current", target)
        raise ReleaseRefusal("same-sequence alternate artifact/mixed pointers refused")
    return ("promote", target)
