"""Read-only staging model for signed v3 Dev. No production signer or GHCR."""
import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from tools import successor_dev_stage as unsigned
from tools import sign_successor_dev_stage as signed
from tools.test_successor_dev_stage import staged_inputs, package, br_replacement
from successor_dev_release import AGENT, DevReleaseRefused


def fake_signed(source, *, package_root, channel, sequence, **kwargs):
    inventory = json.loads(source)
    artifacts = []
    for record in inventory["artifacts"]:
        filename = record["package_file"]
        data = (package_root / "platform" / "packages" / filename).read_bytes()
        artifact = {k: v for k, v in record.items() if k != "package_file"}
        artifact["package"] = {
            "url": "platform/packages/" + filename,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "signature": {"algorithm": "ed25519", "identity": "official-ed25519-1", "value": "test"},
        }
        artifacts.append(artifact)
    return json.dumps({"schema": 1, "signature": {},
                       "signed": {
                           "repository_id": inventory["repository_id"],
                           "channel": channel, "sequence": sequence,
                           "artifacts": artifacts
                       }}).encode()


def prepare(tmp_path: Path, monkeypatch):
    old_packages, old_dev, replacements, trust = staged_inputs(tmp_path, monkeypatch)
    # The signed v3 full image always includes stable, beta, dev indexes.
    old_index = json.loads(old_dev.read_text())
    for channel in ("stable", "beta"):
        copy = json.loads(json.dumps(old_index))
        copy["signed"]["channel"] = channel
        channel_path = old_dev.parent.parent / channel / "index.json"
        channel_path.parent.mkdir()
        channel_path.write_text(json.dumps(copy))
    unsigned_output = tmp_path / "unsigned"
    unsigned.stage_unsigned_dev_delta(
        previous_packages=old_packages, previous_dev_index=old_dev,
        replacements=replacements, output=unsigned_output,
        core_source_sha="f" * 40, trust_root=trust,
    )
    private = Ed25519PrivateKey.generate()
    seed = base64.b64encode(private.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )).decode()
    trust.write_text(base64.b64encode(private.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )).decode())
    monkeypatch.setattr(signed, "verify_index",
                        lambda data, **kw: json.loads(data)["signed"])
    monkeypatch.setattr(signed, "verify_package",
                        lambda artifact, root, keys: None)
    monkeypatch.setattr(signed, "sign_candidate", fake_signed)
    return old_packages.parent, unsigned_output, trust, seed


def test_signer_staging_preserves_existing_channels_and_26_zip_union(tmp_path, monkeypatch):
    prior, unsigned_dir, trust, seed = prepare(tmp_path, monkeypatch)
    output = tmp_path / "signed"
    result = signed.stage_signed_dev(
        prior_platform=prior, unsigned_candidate=unsigned_dir,
        output=output, trust_root=trust, signer_seed=seed,
        core_source_sha="f" * 40,
    )
    assert result["outer_channels_to_publish"] == ["dev"]
    assert result["candidate_sequence"] == 11
    assert result["changed_module_ids"] == [
        "com.sickicarus.monitorbox.core", "com.sickicarus.monitorbox.scaffold-manager"
    ]
    packages = list((output / "full" / "platform" / "packages").glob("*.zip"))
    assert len(packages) == 26
    assert result["new_dev_zip_count"] == 4
    for channel in ("stable", "beta", "dev"):
        index = json.loads(
            (output / "full" / "platform" / "channels" / channel / "index.json").read_text()
        )["signed"]
        assert len(index["artifacts"]) == 22
        assert index["channel"] == channel
        assert index["sequence"] == (11 if channel == "dev" else 10)
    assert not (output / "supervisor-amd64").exists()
    assert not (output / "supervisor-arm64").exists()
    assert not (output / "full" / "platform" / "channels" / "stable" / "promote").exists()


def test_signer_staging_rejects_unmatched_source_or_key(tmp_path, monkeypatch):
    prior, unsigned_dir, trust, seed = prepare(tmp_path, monkeypatch)
    with pytest.raises(DevReleaseRefused):
        signed.stage_signed_dev(
            prior_platform=prior, unsigned_candidate=unsigned_dir,
            output=tmp_path / "out", trust_root=trust, signer_seed=seed,
            core_source_sha="e" * 40,
        )
    with pytest.raises(DevReleaseRefused):
        signed.stage_signed_dev(
            prior_platform=prior, unsigned_candidate=unsigned_dir,
            output=tmp_path / "out", trust_root=trust,
            signer_seed=base64.b64encode(bytes(32)).decode(),
            core_source_sha="f" * 40,
        )


def test_next_dev_release_discards_unreferenced_old_zip_files(tmp_path, monkeypatch):
    prior, unsigned_dir, trust, seed = prepare(tmp_path, monkeypatch)
    for i in range(4):
        (prior / "packages" / f"orphan-{i}.zip").write_bytes(
            (prior / "packages" / f"old-{i:02d}.zip").read_bytes()
        )
    target = tmp_path / "next-dev"
    signed.stage_signed_dev(
        prior_platform=prior, unsigned_candidate=unsigned_dir,
        output=target, trust_root=trust, signer_seed=seed,
        core_source_sha="f" * 40,
    )
    names = {path.name for path in (target / "full/platform/packages").glob("*.zip")}
    assert len(names) == 26
    assert not any(name.startswith("orphan-") for name in names)


def test_signed_stable_reference_retains_historical_package(tmp_path, monkeypatch):
    prior, unsigned_dir, trust, seed = prepare(tmp_path, monkeypatch)
    archive = prior / "packages"
    (archive / "archived.zip").write_bytes((archive / "old-00.zip").read_bytes())
    stable = prior / "channels/stable/index.json"
    data = json.loads(stable.read_text())
    data["signed"]["artifacts"][0]["package"]["url"] = "platform/packages/archived.zip"
    stable.write_text(json.dumps(data))
    target = tmp_path / "keep-stable"
    signed.stage_signed_dev(
        prior_platform=prior, unsigned_candidate=unsigned_dir,
        output=target, trust_root=trust, signer_seed=seed,
        core_source_sha="f" * 40,
    )
    assert (target / "full/platform/packages/archived.zip").is_file()
    assert len(list((target / "full/platform/packages").glob("*.zip"))) == 27


def test_signer_allows_agent_only_dev_without_core_or_manager_replacement(tmp_path, monkeypatch):
    old_packages, old_dev, _, trust = staged_inputs(tmp_path, monkeypatch)
    baseline = json.loads(old_dev.read_text())["signed"]
    for channel in ("stable", "beta"):
        data = json.loads(old_dev.read_text())
        data["signed"]["channel"] = channel
        dest = old_dev.parent.parent / channel / "index.json"
        dest.parent.mkdir()
        dest.write_text(json.dumps(data))
    new_agent = {}
    for arch in ("amd64", "arm64"):
        old = next(x for x in baseline["artifacts"]
                   if x["artifact_id"] == AGENT and x["platform"]["arch"] == arch)
        path = tmp_path / f"new-agent-{arch}.zip"
        package(path, dict(old, build=old["build"] + 1), source_sha="f" * 40)
        new_agent[AGENT, arch] = path
    unsigned_out = tmp_path / "unsigned-agent"
    unsigned.stage_unsigned_dev_delta(
        previous_packages=old_packages, previous_dev_index=old_dev,
        replacements=new_agent, output=unsigned_out, core_source_sha="f" * 40,
        trust_root=trust, changed_ids=frozenset({AGENT}),
    )
    key = Ed25519PrivateKey.generate()
    seed = base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
    trust.write_text(base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())
    monkeypatch.setattr(signed, "verify_index", lambda data, **kw: json.loads(data)["signed"])
    monkeypatch.setattr(signed, "verify_package", lambda item, root, keys: None)
    monkeypatch.setattr(signed, "sign_candidate", fake_signed)
    result = signed.stage_signed_dev(
        prior_platform=old_packages.parent, unsigned_candidate=unsigned_out,
        output=tmp_path / "signed-agent", trust_root=trust,
        signer_seed=seed, core_source_sha="f" * 40,
    )
    assert result["changed_module_ids"] == [AGENT]
    assert result["new_dev_zip_count"] == 2
    assert result["outer_channels_to_publish"] == ["dev"]
    assert len(list((tmp_path / "signed-agent/full/platform/packages").glob("*.zip"))) == 24


def test_signer_admits_exact_one_br_only_zip_and_retains_stable_beta(tmp_path, monkeypatch):
    from successor_dev_release import BACKUP_RESTORE
    old_packages, old_dev, replacement, trust = br_replacement(tmp_path, monkeypatch)
    baseline = json.loads(old_dev.read_text())
    for channel in ("stable", "beta"):
        old = json.loads(json.dumps(baseline))
        old["signed"]["channel"] = channel
        path = old_dev.parent.parent / channel / "index.json"
        path.parent.mkdir()
        path.write_text(json.dumps(old))
    proposed = tmp_path / "unsigned-br"
    unsigned.stage_unsigned_dev_delta(
        previous_packages=old_packages, previous_dev_index=old_dev,
        replacements=replacement, output=proposed, core_source_sha="f" * 40,
        trust_root=trust, changed_ids=frozenset({BACKUP_RESTORE}),
    )
    private = Ed25519PrivateKey.generate()
    seed = base64.b64encode(private.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )).decode()
    trust.write_text(base64.b64encode(private.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )).decode())
    monkeypatch.setattr(signed, "verify_index", lambda data, **kw: json.loads(data)["signed"])
    monkeypatch.setattr(signed, "verify_package", lambda item, root, keys: None)
    monkeypatch.setattr(signed, "sign_candidate", fake_signed)
    out = tmp_path / "signed-br"
    result = signed.stage_signed_dev(
        prior_platform=old_packages.parent, unsigned_candidate=proposed,
        output=out, trust_root=trust, signer_seed=seed,
        core_source_sha="f" * 40,
    )
    assert result["changed_module_ids"] == [BACKUP_RESTORE]
    assert result["new_dev_zip_count"] == 1
    assert result["outer_channels_to_publish"] == ["dev"]
    assert result["artifact_count"] == 22
    assert len(list((out / "full/platform/packages").glob("*.zip"))) == 23
    for channel in ("stable", "beta"):
        newer = json.loads((out / f"full/platform/channels/{channel}/index.json").read_text())["signed"]
        assert newer["artifacts"] == baseline["signed"]["artifacts"]

def test_protected_signer_admits_only_ui59_and_preserves_stable_beta(tmp_path, monkeypatch):
    from successor_dev_release import UI
    from tools.test_successor_dev_stage import ui_replacement
    old_packages, old_dev, changes, trust = ui_replacement(tmp_path, monkeypatch)
    before = json.loads(old_dev.read_text())
    for channel in ("stable", "beta"):
        old = json.loads(json.dumps(before))
        old["signed"]["channel"] = channel
        target = old_dev.parent.parent / channel / "index.json"
        target.parent.mkdir()
        target.write_text(json.dumps(old))
    prepared = tmp_path / "ui-unsigned"
    unsigned.stage_unsigned_dev_delta(
        previous_packages=old_packages, previous_dev_index=old_dev,
        replacements=changes, output=prepared, core_source_sha="f" * 40,
        trust_root=trust, changed_ids=frozenset({UI}),
    )
    key = Ed25519PrivateKey.generate()
    seed = base64.b64encode(key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
    trust.write_text(base64.b64encode(key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw)).decode())
    monkeypatch.setattr(signed, "verify_index", lambda data, **kw: json.loads(data)["signed"])
    monkeypatch.setattr(signed, "verify_package", lambda item, root, keys: None)
    monkeypatch.setattr(signed, "sign_candidate", fake_signed)
    out = tmp_path / "signed-ui"
    result = signed.stage_signed_dev(
        prior_platform=old_packages.parent, unsigned_candidate=prepared,
        output=out, trust_root=trust, signer_seed=seed, core_source_sha="f" * 40,
    )
    assert result["changed_module_ids"] == [UI]
    assert result["new_dev_zip_count"] == 1
    assert result["artifact_count"] == 22
    assert result["outer_channels_to_publish"] == ["dev"]
    assert len(list((out / "full/platform/packages").glob("*.zip"))) == 23
    for channel in ("stable", "beta"):
        index = json.loads((out / f"full/platform/channels/{channel}/index.json").read_text())["signed"]
        assert index["artifacts"] == before["signed"]["artifacts"]
