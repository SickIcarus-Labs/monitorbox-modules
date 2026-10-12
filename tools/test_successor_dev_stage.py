import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from tools import successor_dev_stage as stage
from successor_dev_release import CORE, MANAGER, DevReleaseRefused
from tools.test_successor_dev_release import fixture

SOURCE = "f" * 40
ARCHES = ("amd64", "arm64")


def package(path: Path, item: dict, *, source_sha="e" * 40, stage_name=None):
    manifest = {
        "artifact_id": item["artifact_id"],
        "version": item["version"],
        "build": item["build"],
        "kind": item["kind"],
        "git_sha": source_sha,
        "release_eligible": True,
        "packaging_stage": stage_name or (
            "successor-scaffold-manager" if item["artifact_id"] == MANAGER
            else "qualified-interpreted"
        ),
        "platform": item["platform"],
        "runtime": {"artifact_id": "python", "version": "1", "build": 1, "sha256": "c" * 64},
        "wheelhouse": {"artifact_id": "wheels", "version": "1", "build": 1, "sha256": "d" * 64},
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("package.json", json.dumps(manifest))


def staged_inputs(tmp_path: Path, monkeypatch):
    old, new, _ = fixture()
    baseline = tmp_path / "baseline"
    src = baseline / "platform" / "packages"
    src.mkdir(parents=True)
    for j, item in enumerate(old["artifacts"]):
        name = f"old-{j:02d}.zip"
        path = src / name
        package(path, item)
        data = path.read_bytes()
        item["package"] = {
            "url": f"platform/packages/{name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "signature": {"algorithm": "ed25519", "identity": "official-ed25519-1", "value": "test"},
        }
    catalog = baseline / "platform" / "channels" / "dev" / "index.json"
    catalog.parent.mkdir(parents=True)
    old["generated_at"] = "2026-10-11T15:00:00Z"
    catalog.write_text(json.dumps({"signed": old, "schema": 1, "signature": {}}))
    monkeypatch.setattr(stage, "verify_index", lambda raw, **kwargs: json.loads(raw)["signed"])
    monkeypatch.setattr(stage, "verify_package", lambda record, path, keys: None)
    key = Ed25519PrivateKey.generate().public_key()
    trust = tmp_path / "trust.pub"
    trust.write_text(base64.b64encode(key.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())
    replacements = {}
    for arch in ARCHES:
        for identity in (CORE, MANAGER):
            item = next(x for x in new["artifacts"] if x["artifact_id"] == identity and x["platform"]["arch"] == arch)
            path = tmp_path / f"new-{identity.rsplit('.', 1)[-1]}-{arch}.zip"
            package(path, item, source_sha=SOURCE)
            replacements[identity, arch] = path
    return src, catalog, replacements, trust


def test_stages_exact_22_packages_and_preserves_other_18(tmp_path: Path, monkeypatch):
    src, index, changes, trust = staged_inputs(tmp_path, monkeypatch)
    output = tmp_path / "candidate"
    receipt = stage.stage_unsigned_dev_delta(
        previous_packages=src, previous_dev_index=index,
        replacements=changes, output=output, core_source_sha=SOURCE,
        trust_root=trust,
    )
    assert receipt["channels_to_publish"] == ["dev"]
    assert receipt["complete_artifact_count"] == 22
    assert receipt["signed"] is False
    manifest = json.loads((output / "catalog.source.json").read_text())
    assert len(manifest["artifacts"]) == 22
    assert len(list((output / "platform" / "packages").glob("*.zip"))) == 22
    unchanged = [
        record for record in manifest["artifacts"]
        if record["artifact_id"] not in (CORE, MANAGER)
    ]
    assert len(unchanged) == 18
    for record in unchanged:
        filename = record["package_file"]
        assert (src / filename).read_bytes() == (output / "platform" / "packages" / filename).read_bytes()


@pytest.mark.parametrize("mutation", [
    "missing-arch", "bad-source", "same-version", "new-dependency", "existing-output",
])
def test_bad_unsigned_dev_release_fails_closed(tmp_path: Path, monkeypatch, mutation):
    src, index, changes, trust = staged_inputs(tmp_path, monkeypatch)
    output = tmp_path / "candidate"
    if mutation == "missing-arch":
        changes.pop((CORE, "arm64"))
    elif mutation == "bad-source":
        item = {
            "artifact_id": CORE, "version": "3.0.0", "build": 4,
            "kind": "module", "platform": {"os":"linux","arch":"amd64","abi":"pure"}
        }
        package(changes[CORE, "amd64"], item, source_sha="0" * 40)
    elif mutation == "same-version":
        item = {
            "artifact_id": MANAGER, "version": "1.0.0", "build": 4,
            "kind": "scaffold-manager", "platform": {"os":"linux","arch":"arm64","abi":"static"}
        }
        package(changes[MANAGER, "arm64"], item, source_sha=SOURCE)
    elif mutation == "new-dependency":
        item = {
            "artifact_id": CORE, "version": "3.0.0", "build": 4,
            "kind": "module", "platform": {"os":"linux","arch":"amd64","abi":"pure"}
        }
        package(changes[CORE, "amd64"], item, source_sha=SOURCE)
        # Repackage a changed wheelhouse declaration unlike the signed baseline.
        with zipfile.ZipFile(changes[CORE, "amd64"], "w") as archive:
            archive.writestr("package.json", json.dumps({
                "artifact_id": CORE, "version": "3.0.0", "build": 4,
                "kind": "module", "git_sha": SOURCE,
                "packaging_stage": "qualified-interpreted", "release_eligible": True,
                "runtime": {"changed": True}, "wheelhouse": {"changed": True}
            }))
    elif mutation == "existing-output":
        output.mkdir()
    with pytest.raises(DevReleaseRefused):
        stage.stage_unsigned_dev_delta(
            previous_packages=src, previous_dev_index=index, replacements=changes,
            output=output, core_source_sha=SOURCE, trust_root=trust,
        )


def test_subsequent_dev_release_allows_verified_historical_zip_names(tmp_path: Path, monkeypatch):
    src, index, changes, trust = staged_inputs(tmp_path, monkeypatch)
    # The first published Dev catalog carries additional old Core/Manager
    # package files referenced by Stable/Beta; subsequent Dev releases must
    # still select the active 22-package closure, not reject the whole feed.
    for i in range(4):
        (src / f"historical-{i}.zip").write_bytes((src / f"old-{i:02d}.zip").read_bytes())
    result = stage.stage_unsigned_dev_delta(
        previous_packages=src, previous_dev_index=index,
        replacements=changes, output=tmp_path / "second-dev",
        core_source_sha=SOURCE, trust_root=trust,
    )
    assert result["complete_artifact_count"] == 22
    assert len(list((tmp_path / "second-dev/platform/packages").glob("*.zip"))) == 22
