from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import qualify_successor_runtime_artifacts as q


def _write_snapshot(path: Path, arch: str) -> dict:
    value = {
        "schema": 1,
        "release_eligible": False,
        "packaging_stage": "snapshot-debian-signed-index-discovery-only",
        "arch": arch,
        "keyring_sha256": "1" * 64,
        "inrelease": {"sha256": "2" * 64},
        "packages": {"sha256": "3" * 64},
    }
    path.write_text(json.dumps(value))
    return value


def test_runtime_qualification_rebinds_only_reviewed_authority(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    (root / "runtime/loader").mkdir(parents=True)
    (root / "runtime/usr/local/bin").mkdir(parents=True)
    ca_dir = root / "runtime/etc/ssl/certs"
    ca_dir.mkdir(parents=True)
    ca = b"synthetic-ca"
    monkeypatch.setattr(q, "APPROVED_CA", hashlib.sha256(ca).hexdigest())
    (ca_dir / "ca-certificates.crt").write_bytes(ca)
    entry = root / "runtime/usr/local/bin/python3.13"
    loader = root / "runtime/loader/ld-linux-x86-64.so.2"
    entry.write_bytes(b"\x7fELF" + bytes(100))
    loader.write_bytes(b"\x7fELF" + bytes(100))
    snapshot_path = tmp_path / "snapshot.json"
    snapshot = _write_snapshot(snapshot_path, "amd64")
    manifest = {
        "schema": 1,
        "artifact_id": "com.sickicarus.monitorbox.runtime.python",
        "kind": "runtime",
        "version": "3.13.15",
        "build": 1,
        "release_eligible": False,
        "packaging_stage": "digest-pinned-upstream-runtime-proof",
        "platform": {"os": "linux", "arch": "amd64", "abi": "glibc"},
        "entrypoint": "runtime/usr/local/bin/python3.13",
        "dynamic_loader": "runtime/loader/ld-linux-x86-64.so.2",
        "library_paths": ["runtime/lib", "runtime/usr/local/lib"],
        "tools": {},
        "environment": {},
        "verified_elf_count": 2,
        "library_count": 0,
        "upstream": {
            "python_image": "pinned",
            "node_image": "pinned",
            "os_packages": "snapshot-locked-oci-base-abi-prototype",
            "debian_abi": {
                "arch": "amd64",
                "lock_sha256": "4" * 64,
                "base_ca_sha256": q.APPROVED_CA,
                "installed_ca_sha256": q.APPROVED_CA,
                "abi_versions": {},
                "changed_packages": [],
                "snapshot": {
                    "signed_inrelease_sha256": snapshot["inrelease"]["sha256"],
                    "signed_packages_sha256": snapshot["packages"]["sha256"],
                    "debian_keyring_sha256": snapshot["keyring_sha256"],
                },
            },
        },
    }
    (root / "package.json").write_text(json.dumps(manifest))
    first = q.qualify_runtime(root, snapshot_path)
    second = q.qualify_runtime(root, snapshot_path)
    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        qualified = json.loads(archive.read("package.json"))
        assert qualified["release_eligible"] is True
        assert qualified["packaging_stage"] == "qualified-native-runtime"
        assert qualified["upstream"]["os_packages"] == "qualified-archived-debian-abi"
        assert "snapshot" not in qualified["upstream"]["debian_abi"]
        assert archive.read("runtime/usr/local/bin/python3.13").startswith(b"\x7fELF")


def test_wheelhouse_qualification_preserves_exact_reviewed_wheel_bytes(tmp_path: Path):
    source = tmp_path / "wheelhouse.zip"
    wheels = []
    payloads = {}
    for index in range(14):
        filename = f"pkg{index}-1.0.0-py3-none-any.whl"
        payload = f"wheel-{index}".encode()
        payloads[filename] = payload
        wheels.append({
            "name": f"pkg{index}",
            "version": "1.0.0",
            "filename": filename,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        })
    manifest = {
        "schema": 1,
        "artifact_id": "com.sickicarus.monitorbox.core.wheelhouse-proof",
        "packaging_stage": "source-reviewed-hashlocked-offline-proof",
        "release_eligible": False,
        "platform": {"os": "linux", "arch": "amd64", "python": "cp313"},
        "direct_requirements": ["pkg0==1.0.0"],
        "wheels": wheels,
    }
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("wheelhouse.json", json.dumps(manifest))
        archive.writestr("requirements.lock", "synthetic-lock")
        for name, payload in payloads.items():
            archive.writestr("wheels/" + name, payload)
    qualified = q.qualify_wheelhouse(source)
    with zipfile.ZipFile(io.BytesIO(qualified)) as archive:
        value = json.loads(archive.read("wheelhouse.json"))
        assert value["artifact_id"] == "com.sickicarus.monitorbox.core.wheels"
        assert value["release_eligible"] is True
        assert value["packaging_stage"] == "qualified-wheel-closure"
        for name, payload in payloads.items():
            assert archive.read("wheels/" + name) == payload


def test_wheelhouse_rejects_changed_reviewed_hash(tmp_path: Path):
    source = tmp_path / "wheelhouse.zip"
    records = []
    with zipfile.ZipFile(source, "w") as archive:
        for index in range(14):
            filename = f"pkg{index}-1.0.0-py3-none-any.whl"
            payload = f"wheel-{index}".encode()
            records.append({
                "name": f"pkg{index}",
                "version": "1.0.0",
                "filename": filename,
                "sha256": "0" * 64 if index == 0 else hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            })
            archive.writestr("wheels/" + filename, payload)
        archive.writestr("requirements.lock", "synthetic-lock")
        archive.writestr("wheelhouse.json", json.dumps({
            "schema": 1,
            "artifact_id": "com.sickicarus.monitorbox.core.wheelhouse-proof",
            "packaging_stage": "source-reviewed-hashlocked-offline-proof",
            "release_eligible": False,
            "platform": {"os": "linux", "arch": "amd64", "python": "cp313"},
            "direct_requirements": ["pkg0==1.0.0"],
            "wheels": records,
        }))
    try:
        q.qualify_wheelhouse(source)
    except q.QualificationError as exc:
        assert "reviewed hashes" in str(exc)
    else:
        raise AssertionError("changed wheel hash was accepted")
