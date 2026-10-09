#!/usr/bin/env python3
"""Protected signer staging for #630 UI-only successor sequence promotion.

Stage a full three-channel signed application catalog and two manager-only
Supervisor catalog contexts. Reuse all prior manager and other module ZIP bytes.
Does not access GHCR or write a channel pointer.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from build_platform_index import sign_candidate
from successor_ui_only_release import UI, prepare, assert_exact_delta
from verify_platform_index import _date, verify_index, verify_package

KEY_ID = "official-ed25519-1"
CHANNELS = ("stable", "beta", "dev")
ARCHES = ("amd64", "arm64")
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"


def create_stage(*, previous: Path, baseline_index: Path, output: Path,
                 authority: Path, core_source_sha: str, trust_root: Path,
                 signer_seed: str) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("refusing existing signer output")
    raw_key = base64.b64decode(signer_seed, validate=True)
    if len(raw_key) != 32:
        raise ValueError("protected signer seed is not Ed25519 raw32")
    key = Ed25519PrivateKey.from_private_bytes(raw_key)
    public = key.public_key()
    actual = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    if base64.b64encode(actual).decode("ascii") != trust_root.read_text().strip():
        raise ValueError("protected signer public identity is not the appliance trust root")

    baseline = json.loads(baseline_index.read_text("utf-8"))
    previous_time = _date(baseline["signed"]["generated_at"])
    keys = {KEY_ID: public}
    # Verify historical signatures even when prior catalog expired; historical
    # expiry is never accepted as a new installation candidate.
    verify_index(baseline_index.read_bytes(), keys=keys,
                 channel="stable", now=previous_time)
    for artifact in baseline["signed"]["artifacts"]:
        verify_package(artifact, previous.parent.parent, keys)
    old_seq = baseline["signed"]["sequence"]
    if type(old_seq) is not int or old_seq < 1:
        raise ValueError("bad historical sequence")

    full = output / "full"
    package_dir = full / "platform" / "packages"
    inventory = prepare(previous, package_dir, baseline_index=baseline_index,
                        authority=authority, core_source_sha=core_source_sha)
    source_bytes = (json.dumps(inventory, indent=2, sort_keys=True) + "\n").encode()
    now = datetime.now(timezone.utc)
    signed = {}
    for channel in CHANNELS:
        dst = full / "platform" / "channels" / channel / "index.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = sign_candidate(source_bytes, package_root=full, key=key,
                             key_id=KEY_ID, channel=channel,
                             sequence=old_seq + 1, generated_at=now,
                             valid_hours=168)
        dst.write_bytes(raw)
        signed[channel] = json.loads(raw)
        verify_index(raw, keys=keys, channel=channel, now=now,
                     min_sequence=old_seq + 1)
        for item in signed[channel]["signed"]["artifacts"]:
            verify_package(item, full, keys)
    assert_exact_delta(baseline, signed["stable"], old_sequence=old_seq)

    sup = {}
    for arch in ARCHES:
        items = [item for item in inventory["artifacts"]
                 if item["artifact_id"] == MANAGER and item["platform"]["arch"] == arch]
        if len(items) != 1:
            raise ValueError("Supervisor architecture closure missing/ambiguous")
        item = items[0]
        d = output / ("supervisor-" + arch)
        pkg = d / "platform" / "packages"
        pkg.mkdir(parents=True)
        shutil.copyfile(package_dir / item["package_file"], pkg / item["package_file"])
        one = {"schema": 1, "repository_id": "official-platform", "artifacts": items}
        raw = sign_candidate(json.dumps(one, sort_keys=True).encode(),
                             package_root=d, key=key, key_id=KEY_ID,
                             channel="stable", sequence=old_seq + 1,
                             generated_at=now, valid_hours=168)
        index = d / "platform" / "channels" / "stable" / "index.json"
        index.parent.mkdir(parents=True)
        index.write_bytes(raw)
        manager_signed = json.loads(raw)["signed"]["artifacts"][0]
        full_signed = [v for v in signed["stable"]["signed"]["artifacts"]
                       if v["artifact_id"] == MANAGER and v["platform"]["arch"] == arch]
        if len(full_signed) != 1 or full_signed[0] != manager_signed:
            raise ValueError("Supervisor catalog manager differs from full release")
        verify_index(raw, keys=keys, channel="stable", now=now,
                     min_sequence=old_seq + 1)
        verify_package(manager_signed, d, keys)
        sup[arch] = manager_signed["package"]["sha256"]

    receipt = {
        "old_sequence": old_seq, "new_sequence": old_seq + 1,
        "module_id": UI, "module_version": "1.18.0", "module_build": 58,
        "core_source_sha": core_source_sha,
        "catalog_channels": list(CHANNELS),
        "supervisor_manager_package_sha256": sup,
        "unchanged_package_count": 21,
    }
    (output / "release-intent.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--baseline-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authority", type=Path,
                        default=Path("platform/modules/first-party-successor-v1.json"))
    parser.add_argument("--core-source-sha", required=True)
    parser.add_argument("--trust-root", type=Path, default=Path("trust/official-ed25519-1.pub"))
    args = parser.parse_args()
    result = create_stage(previous=args.previous, baseline_index=args.baseline_index,
                          output=args.output, authority=args.authority,
                          core_source_sha=args.core_source_sha,
                          trust_root=args.trust_root,
                          signer_seed=os.environ["MONITORBOX_PLATFORM_SIGNING_KEY"])
    print("Staged signed UI-only successor candidate (NOT published): " +
          json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
