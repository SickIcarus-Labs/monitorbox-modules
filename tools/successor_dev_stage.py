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

from successor_dev_release import AGENT, CORE, MANAGER, BACKUP_RESTORE, UI, DevReleaseRefused, _records, _release_key
from verify_platform_index import _date, verify_index, verify_package

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
KEY_ID = "official-ed25519-1"
ARCHES = ("amd64", "arm64")
CORE_MANAGER = frozenset({CORE, MANAGER})
AGENT_ONLY = frozenset({AGENT})
BACKUP_RESTORE_ONLY = frozenset({BACKUP_RESTORE})
UI_ONLY = frozenset({UI})
APP_ONLY = frozenset({BACKUP_RESTORE, UI})
REQUIRED = frozenset((identity, arch) for identity in CORE_MANAGER for arch in ARCHES)


def _agent_config_bytes(path: Path) -> bytes:
    """Read the exact shared Agent-generation parser from a fully admitted ZIP."""
    with zipfile.ZipFile(path) as archive:
        name = "app/monitorbox/v2/config.py"
        if archive.namelist().count(name) != 1:
            raise DevReleaseRefused("Core/Agent ZIP lacks a unique generation parser")
        info = archive.getinfo(name)
        if info.file_size > 250_000:
            raise DevReleaseRefused("Core/Agent generation parser is oversized")
        return archive.read(info)



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
    changed_ids: frozenset[str] = CORE_MANAGER,
) -> dict:
    """Prepare one 22-ZIP Dev candidate; never sign or modify any OCI tags.

    Caller supplies Core/Manager (four ZIPs) or a repaired Agent (two ZIPs),
    one per architecture, built from the CI-qualified source commit. Signing
    remains restricted to trusted main after independent requalification.
    """
    if not SHA.fullmatch(core_source_sha):
        raise DevReleaseRefused("exact Core source commit is required")
    if changed_ids not in (CORE_MANAGER, AGENT_ONLY, BACKUP_RESTORE_ONLY, UI_ONLY):
        raise DevReleaseRefused("Dev delta must change exactly Core/Manager, Agent, Backup/Restore or UI")
    required = (frozenset({(next(iter(changed_ids)), "any")}) if changed_ids in (BACKUP_RESTORE_ONLY, UI_ONLY)
                else frozenset((identity, arch) for identity in changed_ids for arch in ARCHES))
    if set(replacements) != required:
        raise DevReleaseRefused("exact two-architecture Dev change set required")
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
    if not {key[0] for key in previous if key[0] in (CORE, MANAGER, AGENT)} == {CORE, MANAGER, AGENT}:
        raise DevReleaseRefused("baseline lacks Core/Agent/Manager roles")
    if not all(
        len([key for key in previous if key[0] == module]) == 2
        for module in (CORE, MANAGER, AGENT)
    ):
        raise DevReleaseRefused("baseline native architecture inventory is incomplete")
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
    # A later Dev image may retain old ZIPs that are still referenced by
    # signed Stable/Beta catalogs. Verify the active Dev closure, rather than
    # demanding that the entire OCI package directory contain only 22 files.
    entries = list(previous_packages.iterdir())
    if (len(entries) > 128 or any(
        p.is_symlink() or not p.is_file() or p.suffix != ".zip"
        for p in entries
    )):
        raise DevReleaseRefused("prior signed feed package directory is unsafe")
    actual_names = {p.name for p in entries}
    if len(old_names) != 22 or not set(old_names).issubset(actual_names):
        raise DevReleaseRefused("previous signed Dev ZIP inventory is incomplete")

    # Staged ZIPs must come from one reviewed Core source, while all unchanged
    # artifacts retain their earlier verified provenance.
    staged = {}
    for module_id, arch in sorted(required):
        new_file = replacements[module_id, arch]
        info = _manifest(new_file)
        previous_record = next(
            (item for key, item in previous.items()
             if key[0] == module_id and key[2] == arch), None
        )
        if previous_record is None:
            raise DevReleaseRefused("changed signed package identity is absent")
        stage = ("successor-module-requalification" if module_id in APP_ONLY
                 else "successor-scaffold-manager" if module_id == MANAGER
                 else "qualified-interpreted")
        if (info.get("artifact_id") != module_id
                or info.get("kind") != ("scaffold-manager" if module_id == MANAGER else "module")
                or info.get("release_eligible") is not True
                or info.get("packaging_stage") != stage
                or (module_id not in APP_ONLY and info.get("git_sha") != core_source_sha)
                or (module_id in APP_ONLY and (
                    not isinstance(info.get("module_runtime"), dict)
                    or info["module_runtime"].get("module_id") != module_id
                    or info["module_runtime"].get("version") != info.get("version")
                    or info["module_runtime"].get("build") != info.get("build")
                ))):
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
        if module_id in (CORE, AGENT):
            # Preserve the sealed Python/wheelhouse closure for interpreted
            # native modules. No dependency upgrades during this repair.
            old_name = previous_record["package"]["url"].removeprefix("platform/packages/")
            old_info = _manifest(previous_packages / old_name)
            if info.get("runtime") != old_info.get("runtime") or info.get("wheelhouse") != old_info.get("wheelhouse"):
                raise DevReleaseRefused("Core/Agent changed protected runtime dependencies")
        elif module_id == MANAGER:
            if info.get("platform") != previous_record.get("platform"):
                raise DevReleaseRefused("Supervisor manager platform changed")
        name = (f"{module_id}-{info['version']}-build{info['build']}.zip"
                if module_id in APP_ONLY else
                f"{module_id}-{info['version']}-build{info['build']}-{arch}.zip")
        if name in actual_names or name in staged:
            raise DevReleaseRefused("new version reuses existing package filename")
        staged[name] = (new_file, (module_id, arch), new_identity)

    # Enforce identical runtime generation wire semantics across the exact
    # selected signed Core and Agent. A newer Core with a stale Agent is not
    # a valid full Dev closure even when both ZIPs are individually signed.
    for arch in ARCHES:
        def package_for(identity: str) -> Path:
            if identity in changed_ids:
                return replacements[identity, arch]
            old = next((item for key, item in previous.items()
                        if key[0] == identity and key[2] == arch), None)
            if old is None:
                raise DevReleaseRefused("missing native runtime role")
            return previous_packages / old["package"]["url"].removeprefix("platform/packages/")
        if _agent_config_bytes(package_for(CORE)) != _agent_config_bytes(package_for(AGENT)):
            raise DevReleaseRefused("Core/Agent selected generation parsers are incompatible")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dev-source-stage-", dir=output.parent) as tmp:
        destination = Path(tmp)
        package_dir = destination / "platform" / "packages"
        package_dir.mkdir(parents=True)
        records = []
        for key, artifact in previous.items():
            original = artifact["package"]["url"].removeprefix("platform/packages/")
            if (key[0], key[2]) in required:
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
            "changed_roles": sorted(changed_ids),
            "channels_to_publish": ["dev"],
            "complete_artifact_count": 22,
            "signed": False,
        }
        (destination / "release-intent.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
        destination.rename(output)
    return receipt
