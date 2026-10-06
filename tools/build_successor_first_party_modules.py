#!/usr/bin/env python3
"""Build deterministic successor-requalified first-party application modules.

These candidates use the exact accepted 2.x package bytes as immutable
provenance and wrap them in a new independently versioned successor package.
Bytes are preserved exactly except for explicitly reviewed successor-only
runtime-boundary overlays (currently Scrypted's signed Node launcher contract).
Each package carries:
- one strict package.json application-module runtime contract;
- one exact portable-config.json contract from #120;
- a truthful Core >=3,<4 compatibility claim that remains release-ineligible
  until the cross-repository Core3 qualification gate is complete.

Existing 2.x package files remain read-only inputs and are never modified in
place; any successor overlay exists only in the newly built candidate ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

from portable_contracts import materialize_contract

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "platform" / "modules" / "first-party-successor-v1.json"
PREDECESSOR_ROOT = ROOT / "packages"
DEFAULT_OUTPUT = ROOT / "platform" / "packages"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_PREDECESSOR_BYTES = 64 << 20
MAX_MEMBERS = 5000
MAX_MEMBER_BYTES = 32 << 20
MAX_TOTAL_BYTES = 128 << 20

CORE_ID = "com.sickicarus.monitorbox.core"
SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"
NODE_RUNTIME_ID = "com.sickicarus.monitorbox.runtime.node"
SCRYPTED_RUNTIME_MEMBER = "monitorbox_scrypted_v230_b6/runtime.py"

_CORE_DEPENDENCY = {
    "artifact_id": CORE_ID,
    "version_range": ">=3.0.0 <4.0.0",
}
_NODE24_DEPENDENCY = {
    "artifact_id": NODE_RUNTIME_ID,
    "version_range": ">=24.0.0 <25.0.0",
}

FIRST_PARTY_IDS = frozenset({
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

_ARTIFACT_ID = re.compile(r"^[a-z0-9][a-z0-9.-]+$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_ENTRYPOINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")


class SuccessorModuleError(ValueError):
    pass


def _expected_platform_dependencies(artifact_id: str) -> list[dict[str, str]]:
    result = [dict(_CORE_DEPENDENCY)]
    if artifact_id == SCRYPTED_ID:
        result.append(dict(_NODE24_DEPENDENCY))
    return result


def _parse_authority() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(AUTHORITY.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuccessorModuleError(f"invalid successor module authority: {exc}") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "packaging_stage", "release_eligible", "modules"}
        or raw["schema"] != 1
        or raw["packaging_stage"] != "successor-module-requalification"
        or type(raw["release_eligible"]) is not bool
        or not isinstance(raw["modules"], list)
    ):
        raise SuccessorModuleError("malformed successor module authority root")
    result: dict[str, dict[str, Any]] = {}
    for item in raw["modules"]:
        if not isinstance(item, dict) or set(item) != {
            "artifact_id", "version", "build", "predecessor", "module_runtime", "platform"
        }:
            raise SuccessorModuleError("malformed successor module record")
        artifact_id = item["artifact_id"]
        version = item["version"]
        build = item["build"]
        if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise SuccessorModuleError("invalid successor artifact identity")
        if not isinstance(version, str) or not _SEMVER.fullmatch(version):
            raise SuccessorModuleError("invalid successor module version")
        if type(build) is not int or build < 1:
            raise SuccessorModuleError("invalid successor module build")
        if artifact_id in result:
            raise SuccessorModuleError("duplicate successor module identity")

        predecessor = item["predecessor"]
        if not isinstance(predecessor, dict) or set(predecessor) != {"filename", "sha256"}:
            raise SuccessorModuleError("malformed predecessor authority")
        filename = predecessor["filename"]
        digest = predecessor["sha256"]
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".zip")
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise SuccessorModuleError("invalid predecessor package authority")

        runtime = item["module_runtime"]
        if not isinstance(runtime, dict):
            raise SuccessorModuleError("module_runtime must be an object")
        required = {
            "module_id", "display_name", "version", "build", "schema",
            "state_schema", "module_type", "entrypoints", "requires_core",
            "requires_runtime_api", "dependencies", "publisher_id", "permissions",
            "lifecycle_policy",
        }
        optional = {"description", "capability_detection"}
        if not required.issubset(runtime) or set(runtime) - required - optional:
            raise SuccessorModuleError("module_runtime shape is invalid")
        if (
            runtime["module_id"] != artifact_id
            or runtime["version"] != version
            or runtime["build"] != build
            or runtime["schema"] != 1
            or type(runtime["state_schema"]) is not int
            or runtime["state_schema"] < 1
            or runtime["requires_core"] != ">=3.0.0 <4.0.0"
            or runtime["requires_runtime_api"] != ">=1 <2"
            or runtime["lifecycle_policy"] not in {"required", "optional"}
        ):
            raise SuccessorModuleError("successor runtime identity/compatibility mismatch")
        entrypoints = runtime["entrypoints"]
        if (
            not isinstance(entrypoints, dict)
            or not entrypoints
            or any(
                not isinstance(name, str) or not name
                or not isinstance(target, str)
                or not _ENTRYPOINT.fullmatch(target)
                for name, target in entrypoints.items()
            )
        ):
            raise SuccessorModuleError("invalid successor module entrypoints")
        if not isinstance(runtime["dependencies"], list) or not isinstance(runtime["permissions"], list):
            raise SuccessorModuleError("successor module list fields are invalid")

        platform = item["platform"]
        if not isinstance(platform, dict) or set(platform) != {
            "os", "arch", "abi", "requires_scaffold_api", "dependencies"
        }:
            raise SuccessorModuleError("malformed successor platform contract")
        if (platform["os"], platform["arch"], platform["abi"]) != ("linux", "any", "pure"):
            raise SuccessorModuleError("first-party successor application modules must be Linux pure packages")
        api = platform["requires_scaffold_api"]
        if api != {"minimum": 1, "maximum_exclusive": 2}:
            raise SuccessorModuleError("unexpected scaffold API range")
        deps = platform["dependencies"]
        if deps != _expected_platform_dependencies(artifact_id):
            raise SuccessorModuleError(
                "successor module platform dependency closure is invalid"
            )
        result[artifact_id] = item
    if set(result) != FIRST_PARTY_IDS:
        raise SuccessorModuleError("successor authority is not the exact 10-module set")
    return result


def _safe_member(name: str) -> bool:
    if not name or name.startswith("/") or "\\" in name:
        return False
    parts = name.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _predecessor_members(record: dict[str, Any]) -> dict[str, bytes | None]:
    package = PREDECESSOR_ROOT / record["predecessor"]["filename"]
    try:
        raw = package.read_bytes()
    except OSError as exc:
        raise SuccessorModuleError(f"missing predecessor package {package.name}") from exc
    if not raw or len(raw) > MAX_PREDECESSOR_BYTES:
        raise SuccessorModuleError("predecessor package is empty or oversized")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != record["predecessor"]["sha256"]:
        raise SuccessorModuleError(
            f"predecessor digest mismatch for {package.name}: {actual}"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile as exc:
        raise SuccessorModuleError("predecessor package is not a ZIP") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_MEMBERS:
            raise SuccessorModuleError("predecessor package member count is invalid")
        seen: set[str] = set()
        total = 0
        result: dict[str, bytes | None] = {}
        for info in infos:
            name = info.filename
            if (
                name in seen
                or not _safe_member(name.rstrip("/"))
                or name in {"package.json", "portable-config.json"}
                or info.file_size > MAX_MEMBER_BYTES
            ):
                raise SuccessorModuleError(f"unsafe predecessor member {name!r}")
            mode = (info.external_attr >> 16) & 0xFFFF
            kind = stat.S_IFMT(mode)
            if info.is_dir():
                if not name.endswith("/") or info.file_size != 0 or kind not in {0, stat.S_IFDIR}:
                    raise SuccessorModuleError(f"unsafe predecessor directory {name!r}")
                seen.add(name)
                result[name] = None
                continue
            if kind not in {0, stat.S_IFREG}:
                raise SuccessorModuleError(f"non-regular predecessor member {name!r}")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise SuccessorModuleError("predecessor expanded payload exceeds bound")
            payload = archive.read(info)
            if len(payload) != info.file_size:
                raise SuccessorModuleError("short predecessor ZIP member")
            seen.add(name)
            result[name] = payload
        return result


def _successor_runtime_overlays(
    record: dict[str, Any],
    files: dict[str, bytes | None],
) -> None:
    """Apply narrowly bounded successor-only runtime contracts.

    Scrypted 2.x located Node from the container PATH. Successor Agent3 must
    instead launch the exact signed Node runtime selected by the scaffold,
    including its reviewed ELF loader and library closure. The legacy fallback
    remains available only when no scaffold artifact identity is present.
    """

    if record["artifact_id"] != SCRYPTED_ID:
        return
    payload = files.get(SCRYPTED_RUNTIME_MEMBER)
    if not isinstance(payload, bytes):
        raise SuccessorModuleError("Scrypted predecessor runtime member is missing")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuccessorModuleError("Scrypted predecessor runtime is not UTF-8") from exc

    old_lookup = '''        node = shutil.which(os.environ.get("MONITORBOX_MODULE_NODE", "node"))
        if node is None:
            raise RuntimeError("Node.js runtime is unavailable for the Scrypted module")
'''
    new_lookup = '''        scaffolded = bool(os.environ.get("MONITORBOX_ARTIFACT_ID"))
        if scaffolded:
            node = os.environ.get("MONITORBOX_MODULE_NODE", "")
            node_loader = os.environ.get("MONITORBOX_MODULE_NODE_LOADER", "")
            node_library_path = os.environ.get(
                "MONITORBOX_MODULE_NODE_LIBRARY_PATH", ""
            )
            if not all(
                isinstance(value, str)
                and value.startswith("/")
                and "\\x00" not in value
                for value in (node, node_loader, node_library_path)
            ):
                raise RuntimeError(
                    "signed Node runtime launch contract is unavailable for Scrypted"
                )
            node_command = [
                node_loader,
                "--library-path",
                node_library_path,
                node,
            ]
        else:
            node = shutil.which(os.environ.get("MONITORBOX_MODULE_NODE", "node"))
            if node is None:
                raise RuntimeError("Node.js runtime is unavailable for the Scrypted module")
            node_command = [node]
'''
    old_exec = '''        process = await asyncio.create_subprocess_exec(
            node,
            str(self._bridge_root / "server.mjs"),
            cwd=str(self._bridge_root),
            env=environment,
        )
'''
    new_exec = '''        process = await asyncio.create_subprocess_exec(
            *node_command,
            str(self._bridge_root / "server.mjs"),
            cwd=str(self._bridge_root),
            env=environment,
        )
'''
    old_socket = '_DEFAULT_SOCKET = "/run/monitorbox-scrypted/bridge.sock"'
    new_socket = '_DEFAULT_SOCKET = "/tmp/monitorbox-scrypted/bridge.sock"'
    old_mkdir = "        socket_path.parent.mkdir(parents=True, exist_ok=True)\n"
    new_mkdir = "        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)\n"

    if (
        text.count(old_lookup) != 1
        or text.count(old_exec) != 1
        or text.count(old_socket) != 1
        or text.count(old_mkdir) != 1
    ):
        raise SuccessorModuleError(
            "Scrypted predecessor successor runtime boundary changed unexpectedly"
        )
    text = (
        text.replace(old_lookup, new_lookup, 1)
        .replace(old_exec, new_exec, 1)
        .replace(old_socket, new_socket, 1)
        .replace(old_mkdir, new_mkdir, 1)
    )
    files[SCRYPTED_RUNTIME_MEMBER] = text.encode("utf-8")


def package_manifest(record: dict[str, Any], *, release_eligible: bool) -> bytes:
    document = {
        "schema": 1,
        "artifact_id": record["artifact_id"],
        "kind": "module",
        "version": record["version"],
        "build": record["build"],
        "release_eligible": release_eligible,
        "packaging_stage": "successor-module-requalification",
        "module_runtime": record["module_runtime"],
        "provenance": {
            "source": "immutable-signed-2.x-package",
            "predecessor_filename": record["predecessor"]["filename"],
            "predecessor_sha256": record["predecessor"]["sha256"],
        },
    }
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def build_package(
    record: dict[str, Any],
    output_dir: Path,
    *,
    release_eligible: bool,
) -> Path:
    files = _predecessor_members(record)
    _successor_runtime_overlays(record, files)
    files["package.json"] = package_manifest(record, release_eligible=release_eligible)
    files["portable-config.json"] = materialize_contract(
        record["artifact_id"], record["version"], record["build"]
    )

    output = io.BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            payload = files[name]
            if payload is None:
                info.external_attr = (stat.S_IFDIR | 0o755) << 16
                archive.writestr(info, b"")
                continue
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            archive.writestr(
                info, payload,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    payload = output.getvalue()
    filename = (
        f"{record['artifact_id']}-{record['version']}-build{record['build']}.zip"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename
    target.write_bytes(payload)
    return target


def build_all(
    output_dir: Path,
    *,
    selected: set[str] | None = None,
    release_eligible: bool | None = None,
) -> list[Path]:
    authority = json.loads(AUTHORITY.read_text("utf-8"))
    records = _parse_authority()
    eligible = authority["release_eligible"] if release_eligible is None else release_eligible
    targets: list[Path] = []
    for artifact_id in sorted(records):
        if selected is not None and artifact_id not in selected:
            continue
        target = build_package(records[artifact_id], output_dir, release_eligible=eligible)
        raw = target.read_bytes()
        print(
            f"built {target}: sha256={hashlib.sha256(raw).hexdigest()} "
            f"release_eligible={str(eligible).lower()}",
            file=sys.stderr,
        )
        targets.append(target)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic successor-requalified first-party module candidates"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--module", action="append", default=[])
    args = parser.parse_args()
    selected = set(args.module) if args.module else None
    try:
        if selected is not None:
            unknown = selected - FIRST_PARTY_IDS
            if unknown:
                raise SuccessorModuleError(
                    "unknown successor module selection: " + ", ".join(sorted(unknown))
                )
        targets = build_all(args.output_dir, selected=selected)
        if not targets:
            raise SuccessorModuleError("no successor modules selected")
    except (OSError, SuccessorModuleError) as exc:
        print(f"successor module build rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
