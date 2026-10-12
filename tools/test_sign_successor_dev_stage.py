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
from tools.test_successor_dev_stage import staged_inputs
from successor_dev_release import DevReleaseRefused


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
