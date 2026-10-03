#!/usr/bin/env python3
"""Derive the immutable successor platform source inventory from package-owned authority.

No digest, portable capability or platform identity is hand-copied into a signed
catalog. This tool emits only the unsigned publisher source consumed later by
build_platform_index.py inside the protected signer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9.-]+$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
CORE = "com.sickicarus.monitorbox.core"
AGENT = "com.sickicarus.monitorbox.agent"
PYTHON = "com.sickicarus.monitorbox.runtime.python"
NODE = "com.sickicarus.monitorbox.runtime.node"
WHEELS = "com.sickicarus.monitorbox.core.wheels"
MANAGER = "com.sickicarus.monitorbox.scaffold-manager"
APP_IDS = frozenset({
    "com.sickicarus.monitorbox.backup-restore",
    "com.sickicarus.monitorbox.configuration-bootstrap",
    "com.sickicarus.monitorbox.http",
    "com.sickicarus.monitorbox.nut",
    "com.sickicarus.monitorbox.portainer",
    "com.sickicarus.monitorbox.scrypted",
    "com.sickicarus.monitorbox.snmp",
    "com.sickicarus.monitorbox.ui",
    "com.sickicarus.monitorbox.unifi",
    "com.sickicarus.monitorbox.wol",
})
REQUIRED_ARCH_IDS = frozenset({CORE, AGENT, PYTHON, NODE, WHEELS, MANAGER})


class FeedSourceError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_member(path: Path, name: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.namelist().count(name) != 1:
                raise FeedSourceError(f"{path.name} requires exactly one {name}")
            raw = archive.read(name)
    except zipfile.BadZipFile as exc:
        raise FeedSourceError(f"{path.name} is not a ZIP") from exc
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FeedSourceError(f"{path.name} {name} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FeedSourceError(f"{path.name} {name} must be an object")
    return value


def _load_module_authority(path: Path) -> dict[str, dict[str, Any]]:
    try:
        root = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FeedSourceError("successor module authority is invalid") from exc
    if (
        not isinstance(root, dict)
        or root.get("schema") != 1
        or root.get("packaging_stage") != "successor-module-requalification"
        or not isinstance(root.get("modules"), list)
    ):
        raise FeedSourceError("successor module authority root is invalid")
    result: dict[str, dict[str, Any]] = {}
    for record in root["modules"]:
        if not isinstance(record, dict):
            raise FeedSourceError("successor module authority record is invalid")
        artifact_id = record.get("artifact_id")
        if artifact_id in result:
            raise FeedSourceError("duplicate successor module authority")
        result[str(artifact_id)] = record
    if set(result) != APP_IDS:
        raise FeedSourceError("successor module authority is not the exact ten-module set")
    return result


def _base_record(
    *,
    artifact_id: str,
    kind: str,
    version: str,
    build: int,
    platform: dict[str, Any],
    dependencies: list[dict[str, Any]],
    filename: str,
) -> dict[str, Any]:
    if (
        not ARTIFACT_ID.fullmatch(artifact_id)
        or not SEMVER.fullmatch(version)
        or type(build) is not int
        or build < 1
    ):
        raise FeedSourceError("package-owned artifact identity is invalid")
    if platform.get("os") != "linux" or platform.get("arch") not in {
        "amd64", "arm64", "any"
    } or platform.get("abi") not in {"pure", "glibc", "static"}:
        raise FeedSourceError("package-owned platform identity is invalid")
    return {
        "artifact_id": artifact_id,
        "kind": kind,
        "version": version,
        "build": build,
        "platform": platform,
        "requires_scaffold_api": {"minimum": 1, "maximum_exclusive": 2},
        "dependencies": dependencies,
        "package_file": filename,
    }


def build_source(package_root: Path, module_authority: Path) -> dict[str, Any]:
    if package_root.is_symlink() or not package_root.is_dir():
        raise FeedSourceError("package root is missing or linked")
    authority = _load_module_authority(module_authority)
    files = sorted(package_root.glob("*.zip"))
    if not files or any(path.is_symlink() or not path.is_file() for path in files):
        raise FeedSourceError("package root contains no safe package set")

    manifests: list[tuple[Path, dict[str, Any], str]] = []
    wheelhouses: list[tuple[Path, dict[str, Any], str]] = []
    for path in files:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        if "package.json" in names:
            manifests.append((path, _read_member(path, "package.json"), _sha(path)))
        elif "wheelhouse.json" in names:
            wheelhouses.append((path, _read_member(path, "wheelhouse.json"), _sha(path)))
        else:
            raise FeedSourceError(f"{path.name} has no package-owned authority manifest")

    by_digest = {digest: (path, manifest) for path, manifest, digest in manifests}
    by_digest.update({digest: (path, manifest) for path, manifest, digest in wheelhouses})
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    wheel_refs: dict[str, tuple[str, int]] = {}

    # First gather executable/runtime packages; Core/Agent exact references are
    # later used to derive the wheelhouse version/build instead of inventing it.
    for path, manifest, digest in manifests:
        artifact_id = manifest.get("artifact_id")
        kind = manifest.get("kind")
        version = manifest.get("version")
        build = manifest.get("build")
        if not isinstance(artifact_id, str) or not isinstance(kind, str):
            raise FeedSourceError(f"{path.name} package identity is incomplete")
        if manifest.get("release_eligible") is not True:
            raise FeedSourceError(f"{path.name} is not release eligible")

        if artifact_id in {PYTHON, NODE}:
            platform = manifest.get("platform")
            if kind != "runtime" or not isinstance(platform, dict):
                raise FeedSourceError("native runtime manifest is invalid")
            records.append(_base_record(
                artifact_id=artifact_id, kind=kind, version=str(version), build=build,
                platform=dict(platform), dependencies=[], filename=path.name,
            ))
        elif artifact_id == MANAGER:
            platform = manifest.get("platform")
            if kind != "scaffold-manager" or not isinstance(platform, dict):
                raise FeedSourceError("scaffold-manager manifest is invalid")
            records.append(_base_record(
                artifact_id=artifact_id, kind=kind, version=str(version), build=build,
                platform=dict(platform), dependencies=[], filename=path.name,
            ))
        elif artifact_id in {CORE, AGENT}:
            runtime_ref = manifest.get("runtime")
            wheel_ref = manifest.get("wheelhouse")
            if (
                kind != "module"
                or manifest.get("packaging_stage") != "qualified-interpreted"
                or not isinstance(runtime_ref, dict)
                or not isinstance(wheel_ref, dict)
            ):
                raise FeedSourceError("Core/Agent interpreted package manifest is invalid")
            runtime_digest = runtime_ref.get("sha256")
            wheel_digest = wheel_ref.get("sha256")
            if runtime_digest not in by_digest or wheel_digest not in by_digest:
                raise FeedSourceError("Core/Agent exact dependency package is absent")
            runtime_path, runtime_manifest = by_digest[runtime_digest]
            wheel_path, wheel_manifest = by_digest[wheel_digest]
            if runtime_manifest.get("artifact_id") != PYTHON:
                raise FeedSourceError("Core/Agent runtime reference is not Python")
            if wheel_manifest.get("artifact_id") != WHEELS:
                raise FeedSourceError("Core/Agent wheelhouse reference is not core.wheels")
            arch = runtime_manifest.get("platform", {}).get("arch")
            if arch not in {"amd64", "arm64"} or wheel_manifest.get("platform", {}).get("arch") != arch:
                raise FeedSourceError("Core/Agent dependency architecture is inconsistent")
            for ref, expected, actual in (
                (runtime_ref, runtime_manifest, runtime_path),
            ):
                if (
                    ref.get("artifact_id") != expected.get("artifact_id")
                    or ref.get("version") != expected.get("version")
                    or ref.get("build") != expected.get("build")
                    or ref.get("sha256") != _sha(actual)
                ):
                    raise FeedSourceError("Core/Agent exact runtime reference changed")
            wheel_version = wheel_ref.get("version")
            wheel_build = wheel_ref.get("build")
            if (
                wheel_ref.get("artifact_id") != WHEELS
                or not isinstance(wheel_version, str)
                or not SEMVER.fullmatch(wheel_version)
                or type(wheel_build) is not int
                or wheel_build < 1
                or wheel_ref.get("sha256") != _sha(wheel_path)
            ):
                raise FeedSourceError("Core/Agent exact wheelhouse reference changed")
            prior = wheel_refs.get(arch)
            if prior is not None and prior != (wheel_version, wheel_build):
                raise FeedSourceError("Core/Agent disagree on wheelhouse release identity")
            wheel_refs[arch] = (wheel_version, wheel_build)
            records.append(_base_record(
                artifact_id=artifact_id, kind=kind, version=str(version), build=build,
                platform={"os": "linux", "arch": arch, "abi": "pure"},
                dependencies=[
                    {
                        "artifact_id": PYTHON,
                        "version_range": f"=={runtime_ref['version']}",
                    },
                    {
                        "artifact_id": WHEELS,
                        "version_range": f"=={wheel_version}",
                    },
                ],
                filename=path.name,
            ))
        elif artifact_id in APP_IDS:
            authority_record = authority[artifact_id]
            platform_record = authority_record.get("platform")
            if (
                kind != "module"
                or manifest.get("packaging_stage") != "successor-module-requalification"
                or authority_record.get("version") != version
                or authority_record.get("build") != build
                or not isinstance(platform_record, dict)
            ):
                raise FeedSourceError("first-party package disagrees with successor authority")
            platform = {
                "os": platform_record["os"],
                "arch": platform_record["arch"],
                "abi": platform_record["abi"],
            }
            dependencies = [dict(item) for item in platform_record["dependencies"]]
            records.append(_base_record(
                artifact_id=artifact_id, kind=kind, version=str(version), build=build,
                platform=platform, dependencies=dependencies, filename=path.name,
            ))
        else:
            raise FeedSourceError(f"unexpected successor package {artifact_id}")

    for path, manifest, _digest_value in wheelhouses:
        if (
            manifest.get("artifact_id") != WHEELS
            or manifest.get("release_eligible") is not True
            or manifest.get("packaging_stage") != "qualified-wheel-closure"
        ):
            raise FeedSourceError("wheelhouse package is not qualified")
        arch = manifest.get("platform", {}).get("arch")
        if arch not in wheel_refs:
            raise FeedSourceError("wheelhouse has no matching Core/Agent exact reference")
        version, build = wheel_refs[arch]
        records.append(_base_record(
            artifact_id=WHEELS, kind="runtime", version=version, build=build,
            platform={"os": "linux", "arch": arch, "abi": "glibc"},
            dependencies=[], filename=path.name,
        ))

    for record in records:
        key = (record["artifact_id"], record["platform"]["arch"])
        if key in seen:
            raise FeedSourceError(f"duplicate successor package platform identity: {key}")
        seen.add(key)

    expected = {(artifact_id, arch) for artifact_id in REQUIRED_ARCH_IDS for arch in ("amd64", "arm64")}
    expected |= {(artifact_id, "any") for artifact_id in APP_IDS}
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise FeedSourceError(f"incomplete successor feed closure missing={missing} extra={extra}")

    records.sort(
        key=lambda item: (
            item["artifact_id"], item["version"], item["build"],
            item["platform"]["arch"], item["platform"]["abi"],
        )
    )
    return {"schema": 1, "repository_id": "official-platform", "artifacts": records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument(
        "--module-authority",
        type=Path,
        default=Path("platform/modules/first-party-successor-v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = build_source(args.package_root, args.module_authority)
        if args.output.exists() or args.output.is_symlink():
            raise FeedSourceError("refusing existing output")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(source, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, FeedSourceError, zipfile.BadZipFile) as exc:
        print("successor feed source rejected: " + str(exc), file=__import__("sys").stderr)
        return 1
    print(f"derived {len(source['artifacts'])} successor feed artifacts -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
