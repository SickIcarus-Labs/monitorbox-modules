"""OCI-index/config immutable identity tests; registry network never accessed."""
import copy
import hashlib

import pytest

from successor_release_pairing import ReleaseRefusal
from successor_oci_evidence import verify_immutable_oci_index
from verify_platform_index import canonical

# Shared fixture proves OCI digest-bound labels can be passed into the signed
# three-catalog/complete ZIP closure validator, without registry writes.
from test_successor_release_manifest import candidate, admit


def digest(blob):
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def make_oci(labels_by_arch, *, config_arch_override=None):
    manifests = {}
    configs = {}
    descriptors = []
    for arch in ("amd64", "arm64"):
        raw_config = canonical({
            "os": "linux",
            "architecture": (config_arch_override if arch == "arm64" and config_arch_override else arch),
            "config": {"Labels": labels_by_arch[arch]},
        })
        configs[arch] = raw_config
        raw_manifest = canonical({
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": digest(raw_config), "size": len(raw_config),
            },
            "layers": [{
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": "sha256:" + "c" * 64, "size": 500,
            }],
        })
        manifests[arch] = raw_manifest
        descriptors.append({
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": digest(raw_manifest), "size": len(raw_manifest),
            "platform": {"os": "linux", "architecture": arch},
        })
    raw_index = canonical({
        "schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": descriptors,
    })
    return {
        "index_raw": raw_index,
        "expected_digest": digest(raw_index),
        "platform_manifests": manifests,
        "platform_configs": configs,
    }


def verify(receipt):
    return verify_immutable_oci_index(**receipt)


def test_verified_oci_digest_chain_feeds_signed_manifest_validator(candidate):
    labels = {}
    for role in ("full", "supervisor"):
        receipt = make_oci(candidate["observed_registry_labels"][role])
        labels[role] = verify(receipt)
    accepted = dict(candidate)
    accepted["observed_registry_labels"] = labels
    assert admit(accepted).sequence == 10


def test_mismatched_immutable_index_digest_rejected(candidate):
    receipt = make_oci(candidate["observed_registry_labels"]["full"])
    receipt["expected_digest"] = "sha256:" + "d" * 64
    with pytest.raises(ReleaseRefusal, match="index digest"):
        verify(receipt)


def test_tampered_platform_manifest_rejected_by_descriptor_digest(candidate):
    receipt = make_oci(candidate["observed_registry_labels"]["full"])
    receipt["platform_manifests"]["arm64"] += b" "
    with pytest.raises(ReleaseRefusal, match="descriptor digest"):
        verify(receipt)


def test_tampered_platform_config_rejected_by_manifest_digest(candidate):
    receipt = make_oci(candidate["observed_registry_labels"]["full"])
    receipt["platform_configs"]["amd64"] += b" "
    with pytest.raises(ReleaseRefusal, match="descriptor digest"):
        verify(receipt)


def test_wrong_architecture_inside_digest_verified_config_rejected(candidate):
    receipt = make_oci(candidate["observed_registry_labels"]["full"],
                       config_arch_override="amd64")
    with pytest.raises(ReleaseRefusal, match="configuration platform"):
        verify(receipt)


def test_missing_or_extra_platform_blob_refused(candidate):
    for field in ("platform_manifests", "platform_configs"):
        receipt = make_oci(candidate["observed_registry_labels"]["full"])
        del receipt[field]["arm64"]
        with pytest.raises(ReleaseRefusal, match="exactly amd64 and arm64"):
            verify(receipt)


def test_same_architecture_twice_in_signed_digest_index_fails(candidate):
    receipt = make_oci(candidate["observed_registry_labels"]["full"])
    from json import loads
    value = loads(receipt["index_raw"])
    value["manifests"][1]["platform"]["architecture"] = "amd64"
    receipt["index_raw"] = canonical(value)
    receipt["expected_digest"] = digest(receipt["index_raw"])
    with pytest.raises(ReleaseRefusal, match="duplicate"):
        verify(receipt)


def test_extra_attestation_or_unknown_platform_not_accepted(candidate):
    receipt = make_oci(candidate["observed_registry_labels"]["full"])
    from json import loads
    value = loads(receipt["index_raw"])
    value["manifests"].append({
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": "sha256:" + "e" * 64, "size": 512,
        "platform": {"os": "unknown", "architecture": "unknown"},
    })
    receipt["index_raw"] = canonical(value)
    receipt["expected_digest"] = digest(receipt["index_raw"])
    with pytest.raises(ReleaseRefusal, match="exactly two"):
        verify(receipt)


def test_missing_oci_provenance_label_then_manifest_check_refuses(candidate):
    from json import loads
    receipt = make_oci(candidate["observed_registry_labels"]["full"])
    labels = copy.deepcopy(candidate["observed_registry_labels"]["full"])
    del labels["amd64"]["com.sickicarus.monitorbox.core-source"]
    missing = make_oci(labels)
    verified = verify(missing)
    evidence = dict(candidate)
    evidence["observed_registry_labels"] = copy.deepcopy(candidate["observed_registry_labels"])
    evidence["observed_registry_labels"]["full"] = verified
    with pytest.raises(ReleaseRefusal, match="label mismatch"):
        admit(evidence)


def test_untrusted_oci_labels_must_never_override_manifest_signed_source(candidate):
    labels = copy.deepcopy(candidate["observed_registry_labels"]["supervisor"])
    labels["arm64"]["com.sickicarus.monitorbox.core-source"] = "f" * 40
    receipt = make_oci(labels)
    verified = verify(receipt)
    altered = dict(candidate)
    altered["observed_registry_labels"] = copy.deepcopy(candidate["observed_registry_labels"])
    altered["observed_registry_labels"]["supervisor"] = verified
    with pytest.raises(ReleaseRefusal, match="label mismatch"):
        admit(altered)


def test_no_docker_write_or_runtime_dependency():
    from pathlib import Path
    raw = (Path(__file__).parent / "successor_oci_evidence.py").read_text()
    assert "docker buildx imagetools create" not in raw
    assert "subprocess" not in raw
    assert "MONITORBOX_MODULE_SIGNING_KEY" not in raw
