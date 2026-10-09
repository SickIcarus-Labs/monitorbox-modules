#!/usr/bin/env python3
"""Resume signed UI58 publication using ONLY previously published immutable OCI bytes.

No signer secret, Docker daemon, registry mutation or package rebuild. Fully
verify pinned multiarch OCI blobs, all signed channel indexes/ZIPs, paired
Supervisor catalogs and the strict one-package delta against prior stable.
Only then issue the durable intent used by the independently guarded writer.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from successor_ghcr_readonly import read_only_ghcr_client_from_environment
from successor_registry_extract import (
    FULL_REPO, SUPERVISOR_REPO, _verified_platform_image,
    _compare_full_architectures,
)
from successor_release_pairing import Feed, SupervisorFeed, verified_pair
from successor_ui_only_release import UI, assert_exact_delta
from verify_platform_index import _date, verify_index, verify_package

RELEASE_SHA = "9d4f4eac2bad0a64672a60456737cc5dc306b548"
CORE_SHA = "595262fd989d7b6aa8d8e986d5a1e6655c8318d5"
KEY_ID = "official-ed25519-1"
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"
CHANNELS = ("stable", "beta", "dev")
ARCHES = ("amd64", "arm64")


def _inventory(directory: Path) -> dict[str, str]:
    result = {}
    for file in directory.rglob("*"):
        if file.is_symlink() or (not file.is_dir() and not file.is_file()):
            raise ValueError("invalid retrieved feed entry")
        if file.is_file():
            result[str(file.relative_to(directory))] = hashlib.sha256(file.read_bytes()).hexdigest()
    return result


def resume(*, prior: Path, prior_index: Path, output: Path,
           full_digest: str, supervisor_digest: str,
           expected_full: str, expected_supervisor: str,
           trust: Path, source_commit: str) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("refusing existing recovered candidate output")
    pub = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(trust.read_text("utf-8").strip(), validate=True))
    keys = {KEY_ID: pub}
    baseline = json.loads(prior_index.read_bytes())
    original_seq = baseline["signed"]["sequence"]
    if original_seq != 9:
        raise ValueError("expected exact sequence-9 predecessor")
    verify_index(prior_index.read_bytes(), keys=keys, channel="stable",
                 now=_date(baseline["signed"]["generated_at"]))
    for item in baseline["signed"]["artifacts"]:
        verify_package(item, prior.parent.parent, keys)

    client = read_only_ghcr_client_from_environment()
    output.mkdir(parents=True)
    full_labels, full_roots = _verified_platform_image(
        client, FULL_REPO, full_digest, output / "retrieved-full")
    _compare_full_architectures(full_roots)
    sup_labels, sup_roots = _verified_platform_image(
        client, SUPERVISOR_REPO, supervisor_digest, output / "retrieved-supervisor")

    # The source and Core SHA in the already-published OCI images must be the
    # exact reviewed UI58 publication source, never the new verifier's SHA.
    for role, labels, classname in (
        ("full", full_labels, "successor-physical-acceptance-feed"),
        ("supervisor", sup_labels, "successor-supervisor-bootstrap-feed"),
    ):
        for arch in ARCHES:
            image = labels[arch]
            if (image.get("com.sickicarus.monitorbox.artifact-class") != classname
                or image.get("com.sickicarus.monitorbox.catalog-sequence") != "10"
                or image.get("org.opencontainers.image.revision") != RELEASE_SHA
                or image.get("com.sickicarus.monitorbox.core-source") != CORE_SHA):
                raise ValueError(f"published {role} OCI provenance is wrong: {arch}")

    candidate_platform = full_roots["amd64"] / "platform"
    for arch in ARCHES:
        other = full_roots[arch] / "platform"
        if _inventory(candidate_platform) != _inventory(other):
            raise ValueError("different signed channel/index/package bytes across OCI architectures")
    # Source and destination MUST be separate verified directory trees.
    stage = output / "staged"
    shutil.copytree(candidate_platform, stage / "full" / "platform")
    for arch in ARCHES:
        shutil.copytree(
            sup_roots[arch] / "platform",
            stage / f"supervisor-{arch}" / "platform",
        )

    new_indexes = {}
    for channel in CHANNELS:
        raw = (stage / "full/platform/channels" / channel / "index.json").read_bytes()
        index = verify_index(raw, keys=keys, channel=channel, min_sequence=10)
        if index["sequence"] != 10 or len(index["artifacts"]) != 22:
            raise ValueError("target channel is not complete sequence-10 signed closure")
        for item in index["artifacts"]:
            verify_package(item, stage / "full", keys)
        new_indexes[channel] = json.loads(raw)

    assert_exact_delta(baseline, new_indexes["stable"], old_sequence=9)
    prior_packages = _inventory(prior)
    new_packages = _inventory(stage / "full/platform/packages")
    if len(prior_packages) != 22 or len(new_packages) != 22:
        raise ValueError("expected complete 22-package prior/target census")
    old_index = {x["artifact_id"]: x for x in baseline["signed"]["artifacts"]
                 if x["platform"]["arch"] == "any"}
    old_ui = old_index[UI]["package"]["url"].split("/")[-1]
    new_ui = next(x["package"]["url"].split("/")[-1]
                  for x in new_indexes["stable"]["signed"]["artifacts"]
                  if x["artifact_id"] == UI)
    for name, digest in prior_packages.items():
        if name != old_ui and new_packages.get(name) != digest:
            raise ValueError("unrelated exact ZIP bytes changed: " + name)
    if old_ui in new_packages or new_ui not in new_packages:
        raise ValueError("incorrect UI package replacement")

    signed_supervisor = {}
    for arch in ARCHES:
        raw = (stage / f"supervisor-{arch}/platform/channels/stable/index.json").read_bytes()
        index = verify_index(raw, keys=keys, channel="stable", min_sequence=10)
        if index["sequence"] != 10 or len(index["artifacts"]) != 1:
            raise ValueError("Supervisor catalog must contain exactly one manager")
        manager = index["artifacts"][0]
        if manager["artifact_id"] != MANAGER or manager["platform"]["arch"] != arch:
            raise ValueError("Supervisor manager identity mismatch")
        verify_package(manager, stage / f"supervisor-{arch}", keys)
        signed_supervisor[arch] = raw
    pair = verified_pair(
        Feed(full_digest, (stage / "full/platform/channels/stable/index.json").read_bytes()),
        SupervisorFeed(supervisor_digest, signed_supervisor), keys=keys)
    if pair.sequence != 10:
        raise ValueError("unpaired successor sequence")

    intent = {
        "old_sequence": 9, "new_sequence": 10,
        "module_id": UI, "module_version": "1.18.0", "module_build": 58,
        "previous_full_digest": expected_full,
        "previous_supervisor_digest": expected_supervisor,
        "target_full_digest": full_digest,
        "target_supervisor_digest": supervisor_digest,
        "source_commit": source_commit,
        "immutable_publisher_commit": RELEASE_SHA,
        "unchanged_package_count": 21,
        "catalog_channels": list(CHANNELS),
        "status": "immutable-verified-not-promoted",
    }
    (output / "promotion-receipt.json").write_text(
        json.dumps(intent, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return intent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prior", type=Path, required=True)
    p.add_argument("--prior-index", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--full-digest", required=True)
    p.add_argument("--supervisor-digest", required=True)
    p.add_argument("--expected-full", required=True)
    p.add_argument("--expected-supervisor", required=True)
    p.add_argument("--trust", type=Path, default=Path("trust/official-ed25519-1.pub"))
    a = p.parse_args()
    intent = resume(
        prior=a.prior, prior_index=a.prior_index, output=a.output,
        full_digest=a.full_digest, supervisor_digest=a.supervisor_digest,
        expected_full=a.expected_full, expected_supervisor=a.expected_supervisor,
        trust=a.trust, source_commit=os.environ["GITHUB_SHA"])
    print("Verified immutable signed UI58 candidate; stable pointers UNCHANGED: " +
          json.dumps(intent, sort_keys=True))


if __name__ == "__main__":
    main()
