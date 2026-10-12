"""Unsigned, read-only-predecessor staging for signed v3 Dev Core/Manager updates.

This is NOT a publisher. Historical Dev signature, signed ZIPs, 22 roles,
and the exact intended Core source are admission prerequisites; the protected
signer must later verify the staged bytes and publish only to Dev.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from successor_dev_release import CORE, MANAGER, DevReleaseRefused, _records, _release_key
from verify_platform_index import _date, verify_index, verify_package

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
KEY_ID = "official-ed25519-1"
ARCHES = ("amd64", "arm64")
REQUIRED = frozenset((identity, arch) for identity in (CORE, MANAGER) for arch in ARCHES)


def _manifest(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise DevReleaseRefused("unsigned package is missing or linked")
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.namelist().count("package.json") != 1:
                raise DevReleaseRefused("changed ZIP must have one package.json")
            if archive.getinfo("package.json").file_size > 65536:
                raise DevReleaseRefused("changed package manifest too large")
            manifest = json.loads(archive.read("package.json"))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DevReleaseRefused("invalid changed package archive") from exc
    if not isinstance(manifest, dict):
        raise DevReleaseRefused("changed package manifest must be an object")
    return manifest


def stage_unsigned_dev_delta(
    *,
    previous_packages: Path,
    previous_dev_index: Path,
    replacements: Mapping[tuple[str, str], Path],
    output: Path,
    core_source_sha: str,
    trust_root: Path,
) -> dict:
    """Prepare one 22-ZIP Dev candidate; never sign or modify any OCI tags.

    Caller supplies exactly four unsigned Core/Manager files, one of each per
    architecture, built from the CI-qualified source commit. Signing remains
    restricted to trusted main after independent provenance requalification.
    """
    if not SHA.fullmatch(core_source_sha):
        raise DevReleaseRefused("exact Core source commit is required")
    if set(replacements) != REQUIRED:
        raise DevReleaseRefused("exact two-architecture Core/Manager change set required")
    if output.exists() or output.is_symlink():
        raise DevReleaseRefused("refusing to overwrite candidate output")
    if previous_packages.is_symlink() or not previous_packages.is_dir():
        raise DevReleaseRefused("verified Dev package directory missing")
    if previous_dev_index.is_symlink() or not previous_dev_index.is_file():
        raise DevReleaseRefused("verified Dev index missing")
    raw = previous_dev_index.read_bytes()
    try:
        document = json.loads(raw)
        generated = _date(document["signed"]["generated_at"])
        trusted = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(trust_root.read_text().strip(), validate=True)
        )
        signed = verify_index(
            raw, keys={KEY_ID: trusted}, channel="dev", now=generated
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DevReleaseRefused("baseline Dev catalog signature/admission failed") from exc
    previous = _records(signed, channel="dev", full=True)
    if not isinstance(signed.get("sequence"), int) or signed["sequence"] < 1:
        raise DevReleaseRefused("baseline has no valid signed sequence")
    if not {key[0] for key in previous if key[0] in (CORE, MANAGER)} == {CORE, MANAGER}:
        raise DevReleaseRefused("baseline lacks Core/Manager roles")
    if not all(
        len([key for key in previous if key[0] == module]) == 2
        for module in (CORE, MANAGER)
    ):
        raise DevReleaseRefused("baseline Core/Manager architecture inventory is incomplete")
    old_names = {}
    for key, artifact in previous.items():
        url = artifact["package"]["url"]
        if not isinstance(url, str) or not url.startswith("platform/packages/"):
            raise DevReleaseRefused("unsafe baseline package URL")
        name = url.removeprefix("platform/packages/")
        if not name or Path(name).name != name or name in old_names:
            raise DevReleaseRefused("ambiguous baseline package filename")
        old_names[name] = key
        verify_package(artifact, previous_packages.parent.parent, {KEY_ID: trusted})
    actual_names = {p.name for p in previous_packages.iterdir() if p.is_file()}
    if len(old_names) != 22 or set(old_names) != actual_names:
        raise DevReleaseRefused("previous signed ZIP inventory is not exact")

    # Staged unsigned ZIPs must come from one reviewed Core source, while the
    # unchanged Agent and ten app packages retain their earlier provenance.
    staged = {}
    for module_id, arch in sorted(REQUIRED):
        new_file = replacements[module_id, arch]
        info = _manifest(new_file)
        previous_record = next(
            (item for key, item in previous.items()
             if key[0] == module_id and key[2] == arch), None
        )
        if previous_record is None:
            raise DevReleaseRefused("changed signed package identity is absent")
        if (info.get("artifact_id") != module_id
                or info.get("kind") != ("scaffold-manager" if module_id == MANAGER else "module")
                or info.get("release_eligible") is not True
                or info.get("git_sha") != core_source_sha
                or info.get("packaging_stage") != (
                    "successor-scaffold-manager" if module_id == MANAGER else "qualified-interpreted"
                )):
            raise DevReleaseRefused("changed package provenance/stage is invalid")
        new_identity = {
            "version": info.get("version"), "build": info.get("build"),
        }
        if (not isinstance(new_identity["version"], str)
                or type(new_identity["build"]) is not int
                or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)",
                                    new_identity["version"])):
            raise DevReleaseRefused("changed module has invalid SemVer/build")
        proposed = dict(previous_record, **new_identity)
        if _release_key(proposed) <= _release_key(previous_record):
            raise DevReleaseRefused("changed module version/build must increase")
        if module_id == CORE:
            # Preserve the existing sealed Python/wheelhouse closure; this
            # campaign changes Core code, not dependency packages or Agent.
            old_name = previous_record["package"]["url"].removeprefix("platform/packages/")
            old_info = _manifest(previous_packages / old_name)
            if info.get("runtime") != old_info.get("runtime") or info.get("wheelhouse") != old_info.get("wheelhouse"):
                raise DevReleaseRefused("Core changed its protected runtime dependencies")
        else:
            if info.get("platform") != previous_record.get("platform"):
                raise DevReleaseRefused("Supervisor manager platform changed")
        name = f"{module_id}-{info['version']}-build{info['build']}-{arch}.zip"
        if name in old_names or name in staged:
            raise DevReleaseRefused("new version reuses existing package filename")
        staged[name] = (new_file, (module_id, arch), new_identity)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dev-source-stage-", dir=output.parent) as tmp:
        destination = Path(tmp)
        package_dir = destination / "platform" / "packages"
        package_dir.mkdir(parents=True)
        records = []
        for key, artifact in previous.items():
            original = artifact["package"]["url"].removeprefix("platform/packages/")
            if (key[0], key[2]) in REQUIRED:
                continue
            shutil.copyfile(previous_packages / original, package_dir / original)
            record = {k: v for k, v in artifact.items() if k not in ("package", "portable_config")}
            record["package_file"] = original
            records.append(record)
        for filename, (source, identity, metadata) in staged.items():
            shutil.copyfile(source, package_dir / filename)
            prior = next(
                value for key, value in previous.items()
                if key[0] == identity[0] and key[2] == identity[1]
            )
            record = {k: v for k, v in prior.items() if k not in ("package", "portable_config")}
            record.update(metadata)
            record["package_file"] = filename
            records.append(record)
        records.sort(key=lambda item: (
            item["artifact_id"], item["version"], item["build"],
            item["platform"]["arch"], item["platform"]["abi"]
        ))
        if len(records) != 22 or len(list(package_dir.iterdir())) != 22:
            raise DevReleaseRefused("Dev candidate is not exactly 22 ZIPs")
        inventory = {
            "schema": 1, "repository_id": "official-platform",
            "artifacts": records,
        }
        source = destination / "catalog.source.json"
        source.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
        receipt = {
            "baseline_dev_sequence": signed["sequence"],
            "candidate_dev_sequence": signed["sequence"] + 1,
            "core_source_sha": core_source_sha,
            "changed_roles": sorted({identity[0] for identity in REQUIRED}),
            "channels_to_publish": ["dev"],
            "complete_artifact_count": 22,
            "signed": False,
        }
        (destination / "release-intent.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
        destination.rename(output)
    return receipt
