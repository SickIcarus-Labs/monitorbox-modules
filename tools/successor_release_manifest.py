"""Read-only immutable successor release manifest + signed package closure admission.

The caller MUST retrieve OCI indexes, signed catalog bytes, real OCI labels and
package directories from immutable digest-pinned GHCR images. This helper cannot
prove that caller provenance; it never signs, publishes or touches a mutable tag.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from successor_release_pairing import (
    ARCHES, Feed, SupervisorFeed, Pair, ReleaseRefusal, verified_pair,
)
from verify_platform_index import _parse, VerificationError, verify_package

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "platform/schema/qualified-release-candidate-v1.schema.json"

FULL_CLASS = "successor-physical-acceptance-feed"
SUPERVISOR_CLASS = "successor-supervisor-bootstrap-feed"
SOURCE = "https://github.com/SickIcarus-Labs/monitorbox-modules"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identity(item: dict) -> dict:
    """Projection of signed artifact identity and exact package hash/size."""
    p = item["platform"]
    q = item["package"]
    return {
        "artifact_id": item["artifact_id"], "version": item["version"],
        "build": item["build"],
        "platform": {k: p[k] for k in ("os", "arch", "abi")},
        "url": q["url"], "sha256": q["sha256"], "size": q["size"],
    }


def _identity_key(item: dict) -> tuple:
    p = item["platform"]
    return (item["artifact_id"], item["version"], item["build"],
            p["os"], p["arch"], p["abi"])


def _require_exact_package_directory(root: Path, declared: list[dict]) -> None:
    directory = root / "platform" / "packages"
    if root.is_symlink() or directory.is_symlink() or not directory.is_dir():
        raise ReleaseRefusal("missing, linked or invalid package root")
    names = []
    for item in declared:
        name = item["package"]["url"]
        if not name.startswith("platform/packages/") or "/" in name[len("platform/packages/"):]:
            raise ReleaseRefusal("package path must be a flat signed ZIP path")
        names.append(name[len("platform/packages/"):])
    if len(set(names)) != len(names):
        raise ReleaseRefusal("duplicate package path in signed artifact closure")
    actual = {p.name for p in directory.iterdir()}
    if actual != set(names):
        raise ReleaseRefusal("missing or extraneous package files in feed image")
    if any(not p.is_file() or p.is_symlink() for p in directory.iterdir()):
        raise ReleaseRefusal("non-file or linked package in feed image")


def _verify_package_closure(index: dict, root: Path,
                            keys: Mapping[str, Ed25519PublicKey]) -> None:
    artifacts = index["signed"]["artifacts"]
    _require_exact_package_directory(root, artifacts)
    for item in artifacts:
        try:
            verify_package(item, root, dict(keys))
        except (VerificationError, OSError, ValueError) as exc:
            raise ReleaseRefusal("signed package bytes, length or signature mismatch") from exc


def _verify_labels(actual: Mapping, sources: dict, sequence: int,
                   handoff: str) -> None:
    if not isinstance(actual, Mapping) or set(actual) != {"full", "supervisor"}:
        raise ReleaseRefusal("missing complete immutable registry label evidence")
    for role, class_name in (("full", FULL_CLASS), ("supervisor", SUPERVISOR_CLASS)):
        platforms = actual[role]
        if not isinstance(platforms, Mapping) or set(platforms) != ARCHES:
            raise ReleaseRefusal("missing exact OCI platform-label evidence")
        for arch in ARCHES:
            labels = platforms[arch]
            if not isinstance(labels, Mapping):
                raise ReleaseRefusal("invalid OCI labels from registry")
            expected = {
                "org.opencontainers.image.source": SOURCE,
                "org.opencontainers.image.revision": sources["modules"],
                "com.sickicarus.monitorbox.core-source": sources["core"],
                "com.sickicarus.monitorbox.artifact-class": class_name,
                "com.sickicarus.monitorbox.catalog-sequence": str(sequence),
            }
            if role == "full":
                expected["com.sickicarus.monitorbox.python-source"] = sources["python"]
                expected["com.sickicarus.monitorbox.handoff-digest"] = handoff
            for name, value in expected.items():
                if labels.get(name) != value:
                    raise ReleaseRefusal("immutable OCI source/provenance label mismatch")


def admit_candidate_manifest(raw: bytes, *, full: Feed, supervisor: SupervisorFeed,
                             full_root: Path, supervisor_roots: Mapping[str, Path],
                             observed_registry_labels: Mapping,
                             keys: Mapping[str, Ed25519PublicKey],
                             now: datetime | None = None) -> Pair:
    """Prove exact manifest/index/ZIP/label consistency; authorize NO writes.

    observed_registry_labels must be extracted by a trusted caller, verifying
    immutable multiarch OCI manifests and platform-specific image digests.
    This function cannot tell fabricated dicts from genuine GHCR readback.
    Approved GitHub qualifications, operator approval, signer key custody,
    tag mutation and rollback are entirely separate gates.
    """
    try:
        manifest = _parse(raw)
        schema = _parse(SCHEMA.read_bytes())
        violations = list(Draft202012Validator(schema).iter_errors(manifest))
    except (VerificationError, OSError, ValueError, TypeError) as exc:
        raise ReleaseRefusal("invalid release manifest JSON or schema") from exc
    if violations:
        raise ReleaseRefusal("invalid release manifest: " + sorted(
            violations, key=lambda x: str(x.json_path))[0].message)

    pair = verified_pair(full, supervisor, keys=keys, now=now)
    if manifest["sequence"] != pair.sequence:
        raise ReleaseRefusal("manifest sequence disagrees with signed catalogs")
    images = manifest["images"]
    if (images["full"]["digest"] != pair.full_digest or
            images["supervisor"]["digest"] != pair.supervisor_digest):
        raise ReleaseRefusal("manifest immutable OCI digests disagree with catalog evidence")
    if images["full"]["catalog_sha256"] != _digest(full.signed_index):
        raise ReleaseRefusal("full signed catalog bytes differ from immutable manifest")
    if (not isinstance(supervisor_roots, Mapping) or set(supervisor_roots) != ARCHES or
            set(supervisor.signed_indexes) != ARCHES):
        raise ReleaseRefusal("incomplete Supervisor architecture package roots")
    for arch in ARCHES:
        if images["supervisor"]["catalogs_sha256"][arch] != _digest(supervisor.signed_indexes[arch]):
            raise ReleaseRefusal("Supervisor architecture signed catalog bytes differ")

    full_index = _parse(full.signed_index)
    artifacts = full_index["signed"]["artifacts"]
    expected = [_identity(item) for item in artifacts]
    proposed = manifest["package_closure"]
    if (len(expected) != len(proposed) or
            len({_identity_key(item) for item in proposed}) != len(proposed) or
            {_identity_key(item) for item in expected} != {_identity_key(item) for item in proposed}):
        raise ReleaseRefusal("release package closure has missing/duplicate artifact identities")
    signed_by_identity = {_identity_key(item): item for item in expected}
    for item in proposed:
        if signed_by_identity[_identity_key(item)] != item:
            raise ReleaseRefusal("release package closure metadata differs from signed index")

    _verify_labels(observed_registry_labels, manifest["sources"], pair.sequence,
                   manifest["handoff_digest"])
    _verify_package_closure(full_index, full_root, keys)
    for arch in ARCHES:
        index = _parse(supervisor.signed_indexes[arch])
        _verify_package_closure(index, supervisor_roots[arch], keys)
    return pair
