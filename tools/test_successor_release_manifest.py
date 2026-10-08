"""Read-only strict candidate manifest acceptance over actual 3-catalog layout."""
import base64
import io
import json
import shutil
import zipfile
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from successor_release_pairing import Feed, SupervisorFeed, ReleaseRefusal
from successor_release_manifest import admit_candidate_manifest
from verify_platform_index import canonical
import hashlib

NOW = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"
CORE = "1" * 40
MODULES = "2" * 40
PYTHON = "3" * 40
HANDOFF = "sha256:" + "4" * 64


def zip_payload(name, arch):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("package.json", json.dumps({
            "artifact_id": name, "arch": arch, "release_eligible": True,
        }, sort_keys=True))
    return stream.getvalue()


def signed_index(key, artifacts, *, sequence=10, issue=NOW - timedelta(minutes=30),
                 expires=NOW + timedelta(days=1)):
    signed = {
        "repository_id": "official-platform", "channel": "stable",
        "sequence": sequence, "generated_at": issue.isoformat(),
        "expires_at": expires.isoformat(), "artifacts": artifacts,
    }
    return canonical({
        "schema": 1, "signed": signed,
        "signature": {
            "algorithm": "ed25519", "identity": "official-ed25519-1",
            "value": base64.b64encode(key.sign(canonical(signed))).decode(),
        },
    })


def catalog_artifact(key, artifact_id, arch, *, kind="scaffold-manager"):
    payload = zip_payload(artifact_id, arch)
    name = ("manager" if kind == "scaffold-manager" else "runtime") + "-" + arch + ".zip"
    return {
        "artifact_id": artifact_id, "kind": kind,
        "version": "1.0.0", "build": 4,
        "platform": {"os": "linux", "arch": arch, "abi": "static"},
        "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
        "dependencies": [],
        "package": {
            "url": "platform/packages/" + name,
            "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
            "signature": {
                "algorithm": "ed25519", "identity": "official-ed25519-1",
                "value": base64.b64encode(key.sign(payload)).decode(),
            },
        },
    }, payload


def manifest_projection(item):
    p = item["platform"]
    q = item["package"]
    return {
        "artifact_id": item["artifact_id"], "version": item["version"],
        "build": item["build"],
        "platform": {k: p[k] for k in ("os", "arch", "abi")},
        "url": q["url"], "sha256": q["sha256"], "size": q["size"],
    }


def write_package(root: Path, item, payload):
    out = root / item["package"]["url"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)


def labels(class_name, *, full=False):
    out = {
        "org.opencontainers.image.source": "https://github.com/SickIcarus-Labs/monitorbox-modules",
        "org.opencontainers.image.revision": MODULES,
        "com.sickicarus.monitorbox.core-source": CORE,
        "com.sickicarus.monitorbox.catalog-sequence": "10",
        "com.sickicarus.monitorbox.artifact-class": class_name,
    }
    if full:
        out["com.sickicarus.monitorbox.python-source"] = PYTHON
        out["com.sickicarus.monitorbox.handoff-digest"] = HANDOFF
    return out


@pytest.fixture
def candidate(tmp_path):
    key = Ed25519PrivateKey.generate()
    trusted = {"official-ed25519-1": key.public_key()}
    full_artifacts = []
    packages = {}
    for artifact_id, arch, kind in (
        (MANAGER, "amd64", "scaffold-manager"),
        (MANAGER, "arm64", "scaffold-manager"),
        ("com.sickicarus.monitorbox.python-runtime", "amd64", "runtime"),
    ):
        item, data = catalog_artifact(key, artifact_id, arch, kind=kind)
        full_artifacts.append(item)
        packages[item["package"]["url"]] = data

    full_catalog = signed_index(key, full_artifacts)
    full_root = tmp_path / "full"
    for item in full_artifacts:
        write_package(full_root, item, packages[item["package"]["url"]])

    sup_catalogs = {}
    sup_roots = {}
    for arch in ("amd64", "arm64"):
        manager = next(item for item in full_artifacts
                       if item["artifact_id"] == MANAGER and item["platform"]["arch"] == arch)
        sup_catalogs[arch] = signed_index(key, [manager])
        root = tmp_path / ("sup-" + arch)
        write_package(root, manager, packages[manager["package"]["url"]])
        sup_roots[arch] = root

    full = Feed("sha256:" + "a" * 64, full_catalog)
    sup = SupervisorFeed("sha256:" + "b" * 64, sup_catalogs)
    manifest = {
        "schema": 1, "artifact_class": "successor-qualified-release-candidate",
        "channel": "stable", "sequence": 10,
        "sources": {"core": CORE, "modules": MODULES, "python": PYTHON},
        "handoff_digest": HANDOFF,
        "images": {
            "full": {"digest": full.digest,
                     "catalog_sha256": hashlib.sha256(full_catalog).hexdigest()},
            "supervisor": {
                "digest": sup.digest,
                "catalogs_sha256": {
                    arch: hashlib.sha256(data).hexdigest()
                    for arch, data in sup_catalogs.items()
                },
            },
        },
        "package_closure": [manifest_projection(x) for x in full_artifacts],
    }
    evidence = {
        "full": {arch: labels("successor-physical-acceptance-feed", full=True)
                 for arch in ("amd64", "arm64")},
        "supervisor": {arch: labels("successor-supervisor-bootstrap-feed")
                       for arch in ("amd64", "arm64")},
    }
    return {
        "manifest": manifest, "full": full, "supervisor": sup,
        "full_root": full_root, "supervisor_roots": sup_roots,
        "observed_registry_labels": evidence, "keys": trusted,
        "now": NOW,
    }


def admit(c, *, manifest=None):
    values = {k: v for k, v in c.items() if k != "manifest"}
    return admit_candidate_manifest(canonical(c["manifest"] if manifest is None else manifest),
                                     **values)


def test_signed_exact_full_and_both_supervisor_package_sets_admitted(candidate):
    pair = admit(candidate)
    assert pair.sequence == 10
    assert pair.full_digest == "sha256:" + "a" * 64


@pytest.mark.parametrize("target", [
    ("images", "full", "digest"),
    ("images", "full", "catalog_sha256"),
    ("images", "supervisor", "digest"),
    ("images", "supervisor", "catalogs_sha256", "arm64"),
    ("sources", "core"),
    ("handoff_digest",),
])
def test_manifest_identity_or_source_mismatch_rejected(candidate, target):
    manifest = copy.deepcopy(candidate["manifest"])
    parent = manifest
    for item in target[:-1]:
        parent = parent[item]
    old = parent[target[-1]]
    parent[target[-1]] = "sha256:" + "f" * 64 if old.startswith("sha256:") else "f" * len(old)
    with pytest.raises(ReleaseRefusal):
        admit(candidate, manifest=manifest)


def test_missing_package_and_extra_unlisted_file_refused(candidate):
    pkgdir = candidate["full_root"] / "platform/packages"
    victim = next(pkgdir.iterdir())
    content = victim.read_bytes()
    victim.unlink()
    with pytest.raises(ReleaseRefusal, match="extraneous|missing"):
        admit(candidate)
    victim.write_bytes(content)
    (pkgdir / "unexpected.zip").write_bytes(b"not a signed package")
    with pytest.raises(ReleaseRefusal, match="extraneous"):
        admit(candidate)


def test_tampered_full_zip_digest_refused(candidate):
    file = next((candidate["full_root"] / "platform/packages").iterdir())
    file.write_bytes(file.read_bytes() + b"malicious")
    with pytest.raises(ReleaseRefusal, match="signed package"):
        admit(candidate)


def test_tampered_supervisor_package_refused(candidate):
    file = next((candidate["supervisor_roots"]["arm64"] / "platform/packages").iterdir())
    file.write_bytes(file.read_bytes() + b"corrupted")
    with pytest.raises(ReleaseRefusal, match="signed package"):
        admit(candidate)


def test_mismatched_supervisor_architecture_roots_fail(candidate):
    swapped = dict(candidate)
    swapped["supervisor_roots"] = {"amd64": candidate["supervisor_roots"]["arm64"],
                                   "arm64": candidate["supervisor_roots"]["amd64"]}
    with pytest.raises(ReleaseRefusal):
        admit(swapped)


def test_missing_supervisor_architecture_refused(candidate):
    missing = dict(candidate)
    missing["supervisor_roots"] = {"amd64": candidate["supervisor_roots"]["amd64"]}
    with pytest.raises(ReleaseRefusal, match="incomplete"):
        admit(missing)


def test_package_manifest_omission_or_addition_refused(candidate):
    for edit in ("remove", "duplicate"):
        manifest = copy.deepcopy(candidate["manifest"])
        if edit == "remove":
            manifest["package_closure"].pop()
        else:
            manifest["package_closure"].append(copy.deepcopy(manifest["package_closure"][0]))
        with pytest.raises(ReleaseRefusal):
            admit(candidate, manifest=manifest)


def test_manifest_package_hash_rejected_even_with_same_artifact_identity(candidate):
    manifest = copy.deepcopy(candidate["manifest"])
    manifest["package_closure"][0]["sha256"] = "f" * 64
    with pytest.raises(ReleaseRefusal, match="metadata differs"):
        admit(candidate, manifest=manifest)


def test_oci_arch_or_core_provenance_mismatch_refused(candidate):
    evidence = copy.deepcopy(candidate)
    evidence["observed_registry_labels"]["supervisor"]["amd64"]["com.sickicarus.monitorbox.core-source"] = "f" * 40
    with pytest.raises(ReleaseRefusal, match="label mismatch"):
        admit(evidence)
    evidence = copy.deepcopy(candidate)
    del evidence["observed_registry_labels"]["supervisor"]["arm64"]
    with pytest.raises(ReleaseRefusal, match="platform-label"):
        admit(evidence)


def test_unsigned_catalog_tampering_refused(candidate):
    contents = json.loads(candidate["full"].signed_index)
    contents["signed"]["artifacts"].pop()
    corrupt = dict(candidate)
    corrupt["full"] = Feed(candidate["full"].digest, canonical(contents))
    with pytest.raises(ReleaseRefusal, match="untrusted"):
        admit(corrupt)


def test_reject_extra_schema_fields_and_duplicate_json_keys(candidate):
    manifest = copy.deepcopy(candidate["manifest"])
    manifest["operator_approval"] = True  # Manifest cannot self-authorize.
    with pytest.raises(ReleaseRefusal, match="invalid release manifest"):
        admit(candidate, manifest=manifest)
    raw = canonical(candidate["manifest"])
    duplicate = raw.replace(b'"schema":1', b'"schema":1,"schema":1', 1)
    with pytest.raises(ReleaseRefusal, match="invalid release manifest"):
        admit_candidate_manifest(duplicate, **{k: v for k, v in candidate.items()
                                               if k != "manifest"})


def test_manifest_is_read_only_and_has_no_registry_mutator():
    from pathlib import Path
    raw = (Path(__file__).parent / "successor_release_manifest.py").read_text("utf-8")
    assert "docker buildx imagetools create" not in raw
    assert "subprocess" not in raw
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in raw
