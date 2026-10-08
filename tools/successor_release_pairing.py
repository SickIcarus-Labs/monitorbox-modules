"""Read-only, fail-closed pairing and anti-rollback admission for successor feeds.

This is a validation kernel, NOT a publisher. The future protected release job
must read both current tags from GHCR, verify immutable image provenance and
complete ZIP bytes, and supply their exact signed catalog bytes here. Neither a
requester-provided current-state document nor this module authorizes a tag write.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from verify_platform_index import VerificationError, _parse, _date, verify_index

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\\Z")
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"
ARCHES = frozenset(("amd64", "arm64"))


class ReleaseRefusal(ValueError):
    """Reject unsafe pairing, stale authority, or ambiguous promotion."""


@dataclass(frozen=True)
class Feed:
    digest: str
    signed_index: bytes


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
        raise ReleaseRefusal("signed index must be the exact retrieved UTF-8 bytes")
    try:
        # An older current stable index may be expired. Its Ed25519 signature
        # and signed issue-time still need verification for ordering, without
        # pretending that it is a currently installable package catalog.
        check_time = now
        if historical:
            document = _parse(feed.signed_index)
            if not isinstance(document, dict):
                raise ReleaseRefusal("invalid historic signed index")
            check_time = _date(document["signed"]["generated_at"])
        return verify_index(feed.signed_index, keys=dict(keys),
                            channel="stable", now=check_time)
    except (VerificationError, KeyError, TypeError, ValueError) as exc:
        raise ReleaseRefusal("untrusted, expired, or structurally invalid signed feed") from exc


def _managers(index: dict) -> dict:
    found = {}
    for item in index["artifacts"]:
        if item["artifact_id"] != MANAGER:
            continue
        p = item["platform"]
        if item["kind"] != "scaffold-manager" or p["os"] != "linux" or p["abi"] != "static":
            raise ReleaseRefusal("manager has unsafe platform or kind")
        arch = p["arch"]
        if arch not in ARCHES or arch in found:
            raise ReleaseRefusal("duplicate or unexpected manager architecture")
        found[arch] = item
    if set(found) != ARCHES:
        raise ReleaseRefusal("manager closure must cover amd64 and arm64 exactly")
    return found


def verified_pair(full: Feed, supervisor: Feed, *,
                  keys: Mapping[str, Ed25519PublicKey],
                  now: datetime | None = None, historical: bool = False) -> Pair:
    """Validate both separately signed feeds and their exact paired manager closure."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ReleaseRefusal("validation clock must be timezone aware")
    if full.digest == supervisor.digest:
        raise ReleaseRefusal("full and Supervisor require distinct immutable images")
    a = _catalog(full, keys, now=instant, historical=historical)
    b = _catalog(supervisor, keys, now=instant, historical=historical)
    if a["sequence"] != b["sequence"]:
        raise ReleaseRefusal("full/Supervisor signed catalog sequence mismatch")
    if len(b["artifacts"]) != 2:
        raise ReleaseRefusal("Supervisor feed must contain only its two managers")
    full_managers = _managers(a)
    supervisor_managers = _managers(b)
    if len(a["artifacts"]) <= len(full_managers):
        raise ReleaseRefusal("full feed contains no application/runtime closure")
    for arch in ARCHES:
        if full_managers[arch] != supervisor_managers[arch]:
            raise ReleaseRefusal("Supervisor manager does not exactly match full feed")
    return Pair(a["sequence"], full.digest, supervisor.digest)


def evaluate_promotion(*, candidate_full: Feed, candidate_supervisor: Feed,
                       current_full: Feed, current_supervisor: Feed,
                       keys: Mapping[str, Ed25519PublicKey],
                       now: datetime | None = None) -> tuple[str, Pair]:
    """Return ('promote' | 'already-current', pair). This never mutates GHCR.

    Current feed inputs MUST come from a fresh, trusted GHCR readback, never
    from operator-controlled manifest fields. Caller must additionally prove
    package-byte closure, image provenance, qualified source SHAs, exclusive
    publication lock, actor approval, and coherent post-write registry state.
    """
    instant = now or datetime.now(timezone.utc)
    target = verified_pair(candidate_full, candidate_supervisor, keys=keys, now=instant)
    previous = verified_pair(current_full, current_supervisor, keys=keys,
                             now=instant, historical=True)
    if target.sequence < previous.sequence:
        raise ReleaseRefusal("signed catalog downgrade refused")
    if target.sequence == previous.sequence:
        if target.full_digest == previous.full_digest and target.supervisor_digest == previous.supervisor_digest:
            return ("already-current", target)
        raise ReleaseRefusal("same-sequence alternate artifact or mixed pointers refused")
    return ("promote", target)
