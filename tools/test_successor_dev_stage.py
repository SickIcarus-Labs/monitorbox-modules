import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from tools import successor_dev_stage as stage
from successor_dev_release import AGENT, CORE, MANAGER, BACKUP_RESTORE, DevReleaseRefused
from tools.test_successor_dev_release import fixture

SOURCE = "f" * 40
ARCHES = ("amd64", "arm64")


def package(path: Path, item: dict, *, source_sha="e" * 40, stage_name=None, parser=b"generation-fence-v2"):
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
    if item["artifact_id"] == BACKUP_RESTORE:
        manifest["packaging_stage"] = "successor-module-requalification"
        manifest["module_runtime"] = {
            "module_id": BACKUP_RESTORE,
            "version": item["version"],
            "build": item["build"],
        }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("package.json", json.dumps(manifest))
        if item["artifact_id"] in (CORE, AGENT):
            archive.writestr("app/monitorbox/v2/config.py", parser)


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


def test_agent_only_stages_signed_core_unchanged_and_matched_agent(tmp_path, monkeypatch):
    src, index, _, trust = staged_inputs(tmp_path, monkeypatch)
    baseline = json.loads(index.read_text())["signed"]
    replacements = {}
    for arch in ARCHES:
        item = next(x for x in baseline["artifacts"]
                    if x["artifact_id"] == AGENT and x["platform"]["arch"] == arch)
        updated = dict(item, build=item["build"] + 1)
        path = tmp_path / f"agent-{arch}.zip"
        package(path, updated, source_sha=SOURCE)
        replacements[AGENT, arch] = path
    out = tmp_path / "agent-only"
    receipt = stage.stage_unsigned_dev_delta(
        previous_packages=src, previous_dev_index=index, replacements=replacements,
        output=out, core_source_sha=SOURCE, trust_root=trust,
        changed_ids=frozenset({AGENT}),
    )
    assert receipt["changed_roles"] == [AGENT]
    assert receipt["complete_artifact_count"] == 22
    rows = json.loads((out / "catalog.source.json").read_text())["artifacts"]
    assert len(rows) == 22
    assert len(list((out / "platform/packages").glob("*.zip"))) == 22
    assert {r["build"] for r in rows if r["artifact_id"] == CORE} == {
        r["build"] for r in baseline["artifacts"] if r["artifact_id"] == CORE
    }


@pytest.mark.parametrize("mutation", ["mismatch", "missing-arch", "core-replacement"])
def test_agent_only_rejects_unpaired_core_or_incomplete_delta(tmp_path, monkeypatch, mutation):
    src, index, _, trust = staged_inputs(tmp_path, monkeypatch)
    baseline = json.loads(index.read_text())["signed"]
    replacements = {}
    for arch in ARCHES:
        item = next(x for x in baseline["artifacts"]
                    if x["artifact_id"] == AGENT and x["platform"]["arch"] == arch)
        path = tmp_path / f"new-agent-{arch}.zip"
        package(path, dict(item, build=item["build"] + 1), source_sha=SOURCE,
                parser=b"legacy-two-part-generation" if mutation == "mismatch" else b"generation-fence-v2")
        replacements[AGENT, arch] = path
    if mutation == "missing-arch":
        replacements.pop((AGENT, "arm64"))
    elif mutation == "core-replacement":
        replacements[CORE, "amd64"] = replacements[AGENT, "amd64"]
    with pytest.raises(DevReleaseRefused):
        stage.stage_unsigned_dev_delta(
            previous_packages=src, previous_dev_index=index, replacements=replacements,
            output=tmp_path / "invalid-agent", core_source_sha=SOURCE,
            trust_root=trust, changed_ids=frozenset({AGENT}),
        )


def br_replacement(tmp_path: Path, monkeypatch):
    src, index, _, trust = staged_inputs(tmp_path, monkeypatch)
    old = next(x for x in json.loads(index.read_text())["signed"]["artifacts"]
               if x["artifact_id"] == BACKUP_RESTORE)
    replacement = tmp_path / "new-backup-restore.zip"
    package(replacement, dict(old, version="1.0.6", build=8))
    return src, index, {(BACKUP_RESTORE, "any"): replacement}, trust


def test_br_only_unsigned_delta_preserves_all_other_signed_roles(tmp_path, monkeypatch):
    src, index, changes, trust = br_replacement(tmp_path, monkeypatch)
    output = tmp_path / "br-dev"
    receipt = stage.stage_unsigned_dev_delta(
        previous_packages=src, previous_dev_index=index,
        replacements=changes, output=output, core_source_sha=SOURCE,
        trust_root=trust, changed_ids=frozenset({BACKUP_RESTORE}),
    )
    assert receipt["changed_roles"] == [BACKUP_RESTORE]
    files = list((output / "platform/packages").glob("*.zip"))
    assert len(files) == 22
    rows = json.loads((output / "catalog.source.json").read_text())["artifacts"]
    br = next(row for row in rows if row["artifact_id"] == BACKUP_RESTORE)
    assert br["version"] == "1.0.6"
    assert br["build"] == 8
    assert br["platform"]["arch"] == "any"
    assert br["package_file"] == f"{BACKUP_RESTORE}-1.0.6-build8.zip"


@pytest.mark.parametrize("mutation", ["wrong-arch", "bad-runtime", "bad-stage", "second-module"])
def test_br_unsigned_delta_rejects_unexpected_artifact(tmp_path, monkeypatch, mutation):
    src, index, changes, trust = br_replacement(tmp_path, monkeypatch)
    if mutation == "wrong-arch":
        changes[BACKUP_RESTORE, "amd64"] = changes.pop((BACKUP_RESTORE, "any"))
    elif mutation == "second-module":
        changes[CORE, "amd64"] = changes[BACKUP_RESTORE, "any"]
    else:
        source = changes[BACKUP_RESTORE, "any"]
        with zipfile.ZipFile(source, "r") as archive:
            meta = json.loads(archive.read("package.json"))
        if mutation == "bad-runtime":
            meta["module_runtime"]["build"] = 999
        else:
            meta["packaging_stage"] = "unreviewed"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("package.json", json.dumps(meta))
    with pytest.raises(DevReleaseRefused):
        stage.stage_unsigned_dev_delta(
            previous_packages=src, previous_dev_index=index, replacements=changes,
            output=tmp_path / "rejected", core_source_sha=SOURCE,
            trust_root=trust, changed_ids=frozenset({BACKUP_RESTORE}),
        )

def ui_replacement(tmp_path: Path, monkeypatch):
    from successor_dev_release import UI
    src, index, _, trust = staged_inputs(tmp_path, monkeypatch)
    old = next(x for x in json.loads(index.read_text())["signed"]["artifacts"]
               if x["artifact_id"] == UI)
    replacement = tmp_path / "new-ui59.zip"
    package(replacement, dict(old, version="1.18.1", build=59))
    return src, index, {(UI, "any"): replacement}, trust


def test_ui_only_unsigned_dev_retains_every_other_package(tmp_path, monkeypatch):
    from successor_dev_release import UI
    src, index, changes, trust = ui_replacement(tmp_path, monkeypatch)
    out = tmp_path / "ui59-dev"
    receipt = stage.stage_unsigned_dev_delta(
        previous_packages=src, previous_dev_index=index,
        replacements=changes, output=out, core_source_sha=SOURCE,
        trust_root=trust, changed_ids=frozenset({UI}),
    )
    assert receipt["changed_roles"] == [UI]
    rows = json.loads((out / "catalog.source.json").read_text())["artifacts"]
    assert len(rows) == 22
    assert len(list((out / "platform/packages").glob("*.zip"))) == 22
    ui = next(x for x in rows if x["artifact_id"] == UI)
    assert (ui["version"], ui["build"], ui["platform"]["arch"]) == ("1.18.1", 59, "any")
    assert ui["package_file"] == f"{UI}-1.18.1-build59.zip"


@pytest.mark.parametrize("mutation", ["wrong-arch", "second-module", "wrong-runtime"])
def test_ui_only_stager_refuses_mixed_or_untrusted_input(tmp_path, monkeypatch, mutation):
    from successor_dev_release import UI
    src, index, changes, trust = ui_replacement(tmp_path, monkeypatch)
    if mutation == "wrong-arch":
        changes[UI, "amd64"] = changes.pop((UI, "any"))
    elif mutation == "second-module":
        changes[CORE, "amd64"] = changes[UI, "any"]
    elif mutation == "wrong-runtime":
        path = changes[UI, "any"]
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read("package.json"))
        data["module_runtime"]["version"] = "99.0.0"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("package.json", json.dumps(data))
    with pytest.raises(DevReleaseRefused):
        stage.stage_unsigned_dev_delta(
            previous_packages=src, previous_dev_index=index, replacements=changes,
            output=tmp_path / "no-ui", core_source_sha=SOURCE,
            trust_root=trust, changed_ids=frozenset({UI}),
        )
