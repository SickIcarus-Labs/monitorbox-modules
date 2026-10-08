"""Offline integration: GHCR-shaped immutable OCI blobs through final signed ZIPs."""
import copy
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from successor_registry_extract import (
    FULL_REPO, SUPERVISOR_REPO, ReadOnlyRegistry, ReleaseRefusal,
    admit_digest_pinned_registry_release,
)
from verify_platform_index import canonical
from test_successor_release_manifest import candidate, NOW


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class FakeRegistry:
    def __init__(self):
        self.manifests = {}
        self.blobs = {}
        self.calls = []

    def manifest(self, repository, digest):
        self.calls.append(("GET_MANIFEST", repository, digest))
        return self.manifests[(repository, digest)]

    def blob(self, repository, digest, destination, max_bytes):
        self.calls.append(("GET_BLOB", repository, digest))
        data = self.blobs[(repository, digest)]
        if len(data) > max_bytes:
            raise ReleaseRefusal("test transport size budget exceeded")
        destination.write_bytes(data)


def make_tar(files, *, injected=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for name, data in [*files, *(injected or [])]:
            info = tarfile.TarInfo(name=name)
            if data == "SYMLINK":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                info.size = 0
                tar.addfile(info)
                continue
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def publish_fixture(registry, repo, arch_content, labels, *, injected=None):
    descriptors = []
    for arch in ("amd64", "arm64"):
        root, catalog = arch_content[arch]
        files = [("feed/platform/channels/stable/index.json", catalog)]
        for p in sorted((root / "platform/packages").iterdir()):
            files.append(("feed/platform/packages/" + p.name, p.read_bytes()))
        payload = make_tar(files, injected=(injected or {}).get(arch))
        layer_hash = sha(payload)
        registry.blobs[(repo, layer_hash)] = payload
        config = canonical({"os": "linux", "architecture": arch,
                            "config": {"Labels": labels[arch]}})
        config_hash = sha(config)
        registry.blobs[(repo, config_hash)] = config
        manifest = canonical({
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                       "digest": config_hash, "size": len(config)},
            "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                        "digest": layer_hash, "size": len(payload)}],
        })
        manifest_hash = sha(manifest)
        registry.manifests[(repo, manifest_hash)] = manifest
        descriptors.append({
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": manifest_hash, "size": len(manifest),
            "platform": {"os": "linux", "architecture": arch},
        })
    index = canonical({
        "schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": descriptors,
    })
    digest = sha(index)
    registry.manifests[(repo, digest)] = index
    return digest


@pytest.fixture
def registry_candidate(candidate):
    registry = FakeRegistry()
    full_content = {
        arch: (candidate["full_root"], candidate["full"].signed_index)
        for arch in ("amd64", "arm64")
    }
    sup_content = {
        arch: (candidate["supervisor_roots"][arch],
               candidate["supervisor"].signed_indexes[arch])
        for arch in ("amd64", "arm64")
    }
    manifest = copy.deepcopy(candidate["manifest"])
    manifest["images"]["full"]["digest"] = publish_fixture(
        registry, FULL_REPO, full_content, candidate["observed_registry_labels"]["full"])
    manifest["images"]["supervisor"]["digest"] = publish_fixture(
        registry, SUPERVISOR_REPO, sup_content,
        candidate["observed_registry_labels"]["supervisor"])
    return registry, manifest, candidate


def run(state):
    registry, manifest, candidate = state
    return admit_digest_pinned_registry_release(canonical(manifest), registry,
                                                keys=candidate["keys"], now=NOW)


def test_authentic_digest_pinned_full_and_both_supervisor_platforms(registry_candidate):
    result = run(registry_candidate)
    assert result.pair.sequence == 10
    assert result.full_architectures == ("amd64", "arm64")
    assert result.supervisor_architectures == ("amd64", "arm64")
    registry, manifest, _ = registry_candidate
    assert registry.calls
    assert all(action in ("GET_MANIFEST", "GET_BLOB") for action, _, _ in registry.calls)
    assert set(repository for _, repository, _ in registry.calls) == {
        FULL_REPO, SUPERVISOR_REPO}
    assert all(digest.startswith("sha256:") for _, _, digest in registry.calls)


def test_forged_manifest_digest_rejected_before_package_read(registry_candidate):
    registry, manifest, _ = registry_candidate
    manifest["images"]["full"]["digest"] = "sha256:" + "f" * 64
    with pytest.raises((ReleaseRefusal, KeyError)):
        run(registry_candidate)


def test_tampered_oci_layer_blob_rejected(registry_candidate):
    registry, manifest, _ = registry_candidate
    repo, digest = next((repo, digest) for repo, digest in registry.blobs
                        if repo == FULL_REPO and registry.blobs[(repo, digest)].startswith(b"\x1f\x8b"))
    registry.blobs[(repo, digest)] += b"forged"
    with pytest.raises(ReleaseRefusal, match="layer size|layer digest"):
        run(registry_candidate)


def test_signed_package_disappears_on_one_full_architecture(registry_candidate):
    registry, manifest, candidate = registry_candidate
    full_content = {}
    for arch in ("amd64", "arm64"):
        root = candidate["full_root"]
        catalog = candidate["full"].signed_index
        full_content[arch] = (root, catalog)
    # Rebuild only ARM64 image without one legitimate package.
    original = candidate["full_root"]
    pkg = next((original / "platform/packages").iterdir())
    payloads = [("feed/platform/channels/stable/index.json",
                 candidate["full"].signed_index)]
    payloads.extend(("feed/platform/packages/" + p.name, p.read_bytes())
                    for p in (original / "platform/packages").iterdir() if p.name != pkg.name)
    other_payload = make_tar(payloads)
    old_idx = json.loads(registry.manifests[(FULL_REPO, manifest["images"]["full"]["digest"])])
    arch = old_idx["manifests"][1]
    old_manifest = json.loads(registry.manifests[(FULL_REPO, arch["digest"])])
    layer = old_manifest["layers"][0]
    layer["digest"] = sha(other_payload)
    layer["size"] = len(other_payload)
    registry.blobs[(FULL_REPO, sha(other_payload))] = other_payload
    new_m = canonical(old_manifest)
    arch["digest"] = sha(new_m)
    arch["size"] = len(new_m)
    registry.manifests[(FULL_REPO, sha(new_m))] = new_m
    new_index = canonical(old_idx)
    new_id = sha(new_index)
    registry.manifests[(FULL_REPO, new_id)] = new_index
    manifest["images"]["full"]["digest"] = new_id
    with pytest.raises(ReleaseRefusal, match="architecture package sets differ"):
        run(registry_candidate)


@pytest.mark.parametrize("injected,expected", [
    ([("feed/platform/packages/evil.zip", b"unsigned")], "missing or extraneous"),
    ([("../escape", b"bad")], "path traversal"),
    ([("feed/platform/packages/manager-amd64.zip", "SYMLINK")], "unsafe non-regular|duplicate"),
    ([("feed/platform/packages/.wh.old.zip", b"whiteout")], "whiteouts"),
])
def test_reject_extra_tar_members_and_unsafe_paths(candidate, injected, expected):
    registry = FakeRegistry()
    full_content = {
        arch: (candidate["full_root"], candidate["full"].signed_index)
        for arch in ("amd64", "arm64")
    }
    sup_content = {
        arch: (candidate["supervisor_roots"][arch],
               candidate["supervisor"].signed_indexes[arch])
        for arch in ("amd64", "arm64")
    }
    manifest = copy.deepcopy(candidate["manifest"])
    manifest["images"]["full"]["digest"] = publish_fixture(
        registry, FULL_REPO, full_content, candidate["observed_registry_labels"]["full"],
        injected={"amd64": injected})
    manifest["images"]["supervisor"]["digest"] = publish_fixture(
        registry, SUPERVISOR_REPO, sup_content,
        candidate["observed_registry_labels"]["supervisor"])
    with pytest.raises(ReleaseRefusal, match=expected):
        run((registry, manifest, candidate))


def test_no_live_registry_or_docker_access_in_integration_suite():
    from pathlib import Path
    code = (Path(__file__).parent / "successor_registry_extract.py").read_text()
    assert "docker buildx imagetools create" not in code
    assert "subprocess" not in code
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in code
