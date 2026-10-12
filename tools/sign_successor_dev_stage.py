"""Stage a signed v3 full Dev OCI feed (no registry writes).

Uses the official protected signer ONLY in a trusted publication job. The
normal appliance updater consumes FULL:dev for Core/Manager Update All.
The immutable first stage separately bootstraps from SUP:stable; Dev does not
need a Supervisor OCI pointer. Stable/Beta moving OCI pointers remain untouched.
The Dev image retains signed Stable/Beta catalogs and their old ZIPs.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from build_platform_index import sign_candidate
from successor_dev_release import DevReleaseRefused, qualify_dev_delta
from verify_platform_index import _date, verify_index, verify_package

CHANNELS = ("stable", "beta", "dev")
ARCHES = ("amd64", "arm64")
KEY_ID = "official-ed25519-1"


def _source_from_signed(index: dict) -> bytes:
    """Use the signed old package metadata, never caller-authored source."""
    inventory = {
        "schema": 1,
        "repository_id": "official-platform",
        "artifacts": [],
    }
    for artifact in index["artifacts"]:
        filename = artifact["package"]["url"]
        if not filename.startswith("platform/packages/"):
            raise DevReleaseRefused("prior signed package location is invalid")
        name = filename.removeprefix("platform/packages/")
        if not name or Path(name).name != name:
            raise DevReleaseRefused("prior signed filename is invalid")
        source = {k: v for k, v in artifact.items() if k not in ("package", "portable_config")}
        source["package_file"] = name
        inventory["artifacts"].append(source)
    return json.dumps(inventory, sort_keys=True).encode()


def stage_signed_dev(
    *,
    prior_platform: Path,
    unsigned_candidate: Path,
    output: Path,
    trust_root: Path,
    signer_seed: str,
    core_source_sha: str,
) -> dict:
    """Create fresh trusted indexes, full OCI context and two manager contexts.

    Source PR code never executes in this function. The caller must have
    separately qualified the precise Core source SHA and the unsigned package
    admission; all ZIPs are revalidated using the platform verifier.
    """
    if output.exists() or output.is_symlink():
        raise DevReleaseRefused("refusing to overwrite signed Dev output")
    if prior_platform.is_symlink() or unsigned_candidate.is_symlink():
        raise DevReleaseRefused("signed staging inputs may not be linked")
    if not prior_platform.is_dir() or not unsigned_candidate.is_dir():
        raise DevReleaseRefused("signed staging input directory is unavailable")
    try:
        raw_seed = base64.b64decode(signer_seed, validate=True)
        if len(raw_seed) != 32:
            raise ValueError("invalid signer seed size")
        key = Ed25519PrivateKey.from_private_bytes(raw_seed)
        identity = base64.b64encode(
            key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode("ascii")
        if identity != trust_root.read_text().strip():
            raise DevReleaseRefused("protected signer does not match official trust root")
    except (ValueError, OSError) as exc:
        raise DevReleaseRefused("invalid protected signer identity") from exc
    public = {KEY_ID: key.public_key()}
    previous = {}
    source_packages = prior_platform / "packages"
    if source_packages.is_symlink() or not source_packages.is_dir():
        raise DevReleaseRefused("prior signed package directory is unavailable")
    for channel in CHANNELS:
        index_path = prior_platform / "channels" / channel / "index.json"
        if index_path.is_symlink() or not index_path.is_file():
            raise DevReleaseRefused("prior signed channel is unavailable")
        raw = index_path.read_bytes()
        try:
            issued = _date(json.loads(raw)["signed"]["generated_at"])
            signed = verify_index(raw, keys=public, channel=channel, now=issued)
            for artifact in signed["artifacts"]:
                verify_package(artifact, prior_platform.parent, public)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise DevReleaseRefused("prior signed channel is not authenticated") from exc
        if len(signed["artifacts"]) != 22:
            raise DevReleaseRefused("prior signed channel has incomplete platform closure")
        previous[channel] = signed
    entries = list(source_packages.iterdir())
    if (len(entries) > 128 or any(
        p.is_symlink() or not p.is_file() or p.suffix != ".zip"
        for p in entries
    )):
        raise DevReleaseRefused("prior signed feed package directory is unsafe")
    original_files = {item.name: item for item in entries}
    # Carry forward ONLY ZIPs referenced by the three verified signed
    # catalogs. A previous Dev promotion may have left unreferenced obsolete
    # Core/Manager ZIPs; they must not grow the image forever.
    retained_names = set()
    for channel in CHANNELS:
        for artifact in previous[channel]["artifacts"]:
            url = artifact["package"]["url"]
            if not isinstance(url, str) or not url.startswith("platform/packages/"):
                raise DevReleaseRefused("signed prior ZIP has an unsafe path")
            name = url.removeprefix("platform/packages/")
            if not name or Path(name).name != name:
                raise DevReleaseRefused("signed prior ZIP name is unsafe")
            retained_names.add(name)
    if not retained_names.issubset(original_files):
        raise DevReleaseRefused("a signed historical catalog package is missing")

    unsigned_receipt = json.loads(
        (unsigned_candidate / "release-intent.json").read_text("utf-8")
    )
    if (
        unsigned_receipt.get("core_source_sha") != core_source_sha
        or unsigned_receipt.get("baseline_dev_sequence") != previous["dev"]["sequence"]
        or unsigned_receipt.get("candidate_dev_sequence") != previous["dev"]["sequence"] + 1
        or unsigned_receipt.get("channels_to_publish") != ["dev"]
        or unsigned_receipt.get("signed") is not False
        or unsigned_receipt.get("complete_artifact_count") != 22
    ):
        raise DevReleaseRefused("unsigned Core candidate has wrong release authority")
    unsigned_source = (unsigned_candidate / "catalog.source.json").read_bytes()
    unsigned_inventory = json.loads(unsigned_source)
    if unsigned_inventory.get("repository_id") != "official-platform" or len(unsigned_inventory.get("artifacts", [])) != 22:
        raise DevReleaseRefused("unsigned Dev catalog is incomplete")

    now = datetime.now(timezone.utc)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".signed-dev-stage-", dir=output.parent) as tmp:
        base = Path(tmp)
        full = base / "full"
        target_packages = full / "platform" / "packages"
        target_packages.mkdir(parents=True)
        for filename in sorted(retained_names):
            shutil.copyfile(original_files[filename], target_packages / filename)
        unsigned_packages = unsigned_candidate / "platform" / "packages"
        if unsigned_packages.is_symlink() or not unsigned_packages.is_dir():
            raise DevReleaseRefused("unsigned Dev packages are unavailable")
        updated_names = set()
        for row in unsigned_inventory["artifacts"]:
            filename = row["package_file"]
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise DevReleaseRefused("unsigned Dev package filename is invalid")
            updated_names.add(filename)
        if len(updated_names) != 22 or {p.name for p in unsigned_packages.iterdir()} != updated_names:
            raise DevReleaseRefused("unsigned Dev ZIP census is incomplete")
        new_files = set()
        for filename in updated_names:
            src = unsigned_packages / filename
            if not src.is_file() or src.is_symlink():
                raise DevReleaseRefused("untrusted ZIP in unsigned Dev input")
            dst = target_packages / filename
            if dst.exists():
                if src.read_bytes() != dst.read_bytes():
                    raise DevReleaseRefused("Dev update attempted to replace immutable package filename")
            else:
                shutil.copyfile(src, dst)
                new_files.add(filename)
        if len(new_files) != 4:
            raise DevReleaseRefused("expected exactly four newly versioned Core/Manager ZIPs")
        # Re-sign the old stable and beta *contents* only to refresh the
        # expiration inside the Dev OCI image. No stable/beta OCI tag write.
        signed = {}
        for channel in CHANNELS:
            src = (unsigned_source if channel == "dev"
                   else _source_from_signed(previous[channel]))
            sequence = (
                previous["dev"]["sequence"] + 1
                if channel == "dev" else previous[channel]["sequence"]
            )
            raw = sign_candidate(
                src, package_root=full, key=key, key_id=KEY_ID,
                channel=channel, sequence=sequence,
                generated_at=now, valid_hours=168,
            )
            index = full / "platform" / "channels" / channel / "index.json"
            index.parent.mkdir(parents=True)
            index.write_bytes(raw)
            signed[channel] = verify_index(
                raw, keys=public, channel=channel, now=now
            )
            for artifact in signed[channel]["artifacts"]:
                verify_package(artifact, full, public)
            if channel != "dev" and signed[channel]["artifacts"] != previous[channel]["artifacts"]:
                raise DevReleaseRefused("non-Dev signed artifact inventory changed")
        evidence = qualify_dev_delta(previous["dev"], signed["dev"])
        receipt = {
            **evidence,
            "core_source_sha": core_source_sha,
            "outer_channels_to_publish": ["dev"],
            "stable_beta_oci_tags_changed": False,
            "new_dev_zip_count": len(new_files),
        }
        (base / "release-intent.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
        base.rename(output)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-platform", type=Path, required=True)
    parser.add_argument("--unsigned-candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trust-root", type=Path, default=Path("trust/official-ed25519-1.pub"))
    parser.add_argument("--core-source-sha", required=True)
    args = parser.parse_args()
    receipt = stage_signed_dev(
        prior_platform=args.prior_platform,
        unsigned_candidate=args.unsigned_candidate,
        output=args.output,
        trust_root=args.trust_root,
        signer_seed=os.environ["MONITORBOX_PLATFORM_SIGNING_KEY"],
        core_source_sha=args.core_source_sha,
    )
    print("Prepared signed v3 Dev catalog (NOT PUBLISHED): " +
          json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
