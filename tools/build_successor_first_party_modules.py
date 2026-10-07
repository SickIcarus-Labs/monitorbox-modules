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
PORTAINER_ID = "com.sickicarus.monitorbox.portainer"
SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"
UI_ID = "com.sickicarus.monitorbox.ui"
NODE_RUNTIME_ID = "com.sickicarus.monitorbox.runtime.node"
PORTAINER_RUNTIME_MEMBER = "monitorbox_portainer_b9/runtime.py"
SCRYPTED_RUNTIME_MEMBER = "monitorbox_scrypted_v230_b6/runtime.py"
UI_MODULES_MEMBER_SUFFIX = "/assets/modules.js"
UI_MODULES_CSS_MEMBER_SUFFIX = "/assets/modules.css"

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


def _apply_portainer_successor_overlay(
    files: dict[str, bytes | None],
) -> None:
    """Keep real multi-environment inventory inside the managed 15s budget."""

    payload = files.get(PORTAINER_RUNTIME_MEMBER)
    if not isinstance(payload, bytes):
        raise SuccessorModuleError("Portainer predecessor runtime member is missing")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuccessorModuleError("Portainer predecessor runtime is not UTF-8") from exc

    import_anchor = "from __future__ import annotations\n\n"
    if text.count(import_anchor) != 1 or "import asyncio\n" in text:
        raise SuccessorModuleError(
            "Portainer predecessor asyncio import boundary changed unexpectedly"
        )
    text = text.replace(import_anchor, import_anchor + "import asyncio\n", 1)

    old_timeout = "        timeout = aiohttp.ClientTimeout(total=15)\n"
    new_timeout = (
        "        # The Core managed-provider deadline is 15s. Bound each Portainer\n"
        "        # request to 5s and fan out environment inventories concurrently so\n"
        "        # one slow endpoint becomes partial visibility rather than killing\n"
        "        # the entire provider execution.\n"
        "        timeout = aiohttp.ClientTimeout(total=5)\n"
    )
    if text.count(old_timeout) != 1:
        raise SuccessorModuleError(
            "Portainer predecessor timeout boundary changed unexpectedly"
        )
    text = text.replace(old_timeout, new_timeout, 1)

    old_loop = '''            ignored_count = 0
            for (
                endpoint,
                provider_id,
                name,
                engine,
                environment_key,
            ) in _environment_rows(endpoints, selected_ids):
                endpoint_url = endpoint.get("URL", endpoint.get("url"))
                environments.append(
                    {
                        "provider_id": provider_id,
                        "name": name,
                        "key": environment_key,
                        "status": endpoint.get(
                            "Status", endpoint.get("status")
                        ),
                        "url": endpoint_url,
                        "container_engine": engine,
                    }
                )
                try:
                    containers = await self._get(
                        session,
                        (
                            f"{base}/api/endpoints/{provider_id}/docker/"
                            "containers/json?all=true"
                        ),
                        headers,
                        verify_tls,
                    )
                    if not isinstance(containers, list):
                        raise RuntimeError("container inventory is not a list")
                    successful.add(environment_key)
                except Exception as exc:
                    errors.append(
                        {
                            "environment": name,
                            "environment_key": environment_key,
                            "error": f"{type(exc).__name__}: {exc}"[:300],
                        }
                    )
                    continue

                for container in containers:
'''
    new_loop = '''            ignored_count = 0
            rows = _environment_rows(endpoints, selected_ids)
            container_results = await asyncio.gather(
                *(
                    self._get(
                        session,
                        (
                            f"{base}/api/endpoints/{provider_id}/docker/"
                            "containers/json?all=true"
                        ),
                        headers,
                        verify_tls,
                    )
                    for _, provider_id, _, _, _ in rows
                ),
                return_exceptions=True,
            )
            for row, container_result in zip(rows, container_results):
                endpoint, provider_id, name, engine, environment_key = row
                endpoint_url = endpoint.get("URL", endpoint.get("url"))
                environments.append(
                    {
                        "provider_id": provider_id,
                        "name": name,
                        "key": environment_key,
                        "status": endpoint.get(
                            "Status", endpoint.get("status")
                        ),
                        "url": endpoint_url,
                        "container_engine": engine,
                    }
                )
                if isinstance(container_result, Exception):
                    errors.append(
                        {
                            "environment": name,
                            "environment_key": environment_key,
                            "error": (
                                f"{type(container_result).__name__}: "
                                f"{container_result}"
                            )[:300],
                        }
                    )
                    continue
                containers = container_result
                if not isinstance(containers, list):
                    errors.append(
                        {
                            "environment": name,
                            "environment_key": environment_key,
                            "error": "RuntimeError: container inventory is not a list",
                        }
                    )
                    continue
                successful.add(environment_key)

                for container in containers:
'''
    if text.count(old_loop) != 1:
        raise SuccessorModuleError(
            "Portainer predecessor inventory loop changed unexpectedly"
        )
    text = text.replace(old_loop, new_loop, 1)
    files[PORTAINER_RUNTIME_MEMBER] = text.encode("utf-8")


def _apply_scrypted_successor_overlay(
    files: dict[str, bytes | None],
) -> None:
    payload = files.get(SCRYPTED_RUNTIME_MEMBER)
    if not isinstance(payload, bytes):
        raise SuccessorModuleError("Scrypted predecessor runtime member is missing")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuccessorModuleError("Scrypted predecessor runtime is not UTF-8") from exc

    old_state_import = "from .state_socket import resolve_managed_socket\n"
    new_state_import = '''from .state_socket import (
    LEGACY_SOCKET as _LEGACY_SOCKET,
    resolve_managed_socket as _legacy_resolve_managed_socket,
)

_SUCCESSOR_SOCKET_DEFAULT = "/tmp/monitorbox-scrypted/bridge.sock"
_UNIX_PATH_MAX_BYTES = 107


def resolve_managed_socket(requested: Any, state_root: str | None) -> str:
    """Resolve successor bridge IPC into a short private ephemeral namespace."""

    raw = str(requested or "").strip()
    if not os.environ.get("MONITORBOX_ARTIFACT_ID"):
        return _legacy_resolve_managed_socket(requested, state_root)
    if raw and raw not in {_LEGACY_SOCKET, _SUCCESSOR_SOCKET_DEFAULT}:
        return _legacy_resolve_managed_socket(requested, state_root)
    if not state_root:
        raise RuntimeError("Scrypted managed state root is unavailable")

    root = Path(state_root)
    if not root.is_absolute():
        raise ValueError("Scrypted managed state root must be an absolute path")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Scrypted managed state root is not a real directory")

    # Durable successor slots are deliberately deep. A Linux pathname AF_UNIX
    # socket has only 108 bytes of sun_path storage, so never append bridge.sock
    # directly beneath the durable module state root.
    digest = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:16]
    runtime_root = Path("/tmp") / f"mb-scrypted-{digest}"
    runtime_root.mkdir(mode=0o700, exist_ok=True)
    if (
        runtime_root.is_symlink()
        or not runtime_root.is_dir()
        or runtime_root.stat().st_uid != os.geteuid()
    ):
        raise RuntimeError("Scrypted ephemeral runtime directory is unsafe")
    runtime_root.chmod(0o700)

    socket_path = runtime_root / "bridge.sock"
    if len(os.fsencode(str(socket_path))) > _UNIX_PATH_MAX_BYTES:
        raise RuntimeError("Scrypted bridge socket exceeds Linux AF_UNIX path limit")
    return str(socket_path)
'''

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
        text.count(old_state_import) != 1
        or text.count(old_lookup) != 1
        or text.count(old_exec) != 1
        or text.count(old_socket) != 1
        or text.count(old_mkdir) != 1
    ):
        raise SuccessorModuleError(
            "Scrypted predecessor successor runtime boundary changed unexpectedly"
        )
    text = (
        text.replace(old_state_import, new_state_import, 1)
        .replace(old_lookup, new_lookup, 1)
        .replace(old_exec, new_exec, 1)
        .replace(old_socket, new_socket, 1)
        .replace(old_mkdir, new_mkdir, 1)
    )
    files[SCRYPTED_RUNTIME_MEMBER] = text.encode("utf-8")



def _apply_ui_successor_overlay(
    files: dict[str, bytes | None],
) -> None:
    members = [
        name for name, payload in files.items()
        if name.endswith(UI_MODULES_MEMBER_SUFFIX) and isinstance(payload, bytes)
    ]
    if len(members) != 1:
        raise SuccessorModuleError(
            "UI predecessor must contain exactly one assets/modules.js member"
        )
    member = members[0]
    payload = files[member]
    assert isinstance(payload, bytes)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuccessorModuleError("UI predecessor modules.js is not UTF-8") from exc

    capability_anchor = '''    const catalogRefresh = Boolean(current.catalog_refresh);
    const packageInstall = Boolean(current.package_install);
    const repositoryError = model && model.repository_error ? String(model.repository_error) : "";
'''
    capability_replacement = '''    const catalogRefresh = Boolean(current.catalog_refresh);
    const packageInstall = Boolean(current.package_install);
    const scaffoldLifecycle = Boolean(current.scaffold_lifecycle);
    const updatePlane = packageInstall || scaffoldLifecycle;
    const distributionReady = scaffoldLifecycle || (catalogRefresh && packageInstall);
    const releaseChannels = Array.isArray(current.release_channels) ? current.release_channels : [];
    const preferredChannel = typeof current.preferred_channel === "string" ? current.preferred_channel : "";
    const repositoryError = model && model.repository_error ? String(model.repository_error) : "";
'''
    api_anchor = '''  const UPDATE_ALL_API = "/api/v2/config/modules/update-all";
  const REPOSITORIES_API = "/api/v2/config/modules/repositories";
'''
    api_replacement = '''  const UPDATE_ALL_API = "/api/v2/config/modules/update-all";
  const RELEASE_CHANNEL_API = "/api/v2/config/modules/release-channel";
  const REPOSITORIES_API = "/api/v2/config/modules/repositories";
'''
    if text.count(api_anchor) != 1:
        raise SuccessorModuleError("UI lifecycle API boundary changed unexpectedly")
    text = text.replace(api_anchor, api_replacement, 1)

    if text.count(capability_anchor) != 1:
        raise SuccessorModuleError("UI capability boundary changed unexpectedly")
    text = text.replace(capability_anchor, capability_replacement, 1)
    if text.count("heading.textContent = catalogRefresh && packageInstall") != 1:
        raise SuccessorModuleError("UI distribution heading boundary changed unexpectedly")
    text = text.replace(
        "heading.textContent = catalogRefresh && packageInstall",
        "heading.textContent = distributionReady",
        1,
    )
    if text.count(
        'capabilities.dataset.state = catalogRefresh && packageInstall && !repositoryError ? "ready" : "limited";'
    ) != 1:
        raise SuccessorModuleError("UI distribution state boundary changed unexpectedly")
    text = text.replace(
        'capabilities.dataset.state = catalogRefresh && packageInstall && !repositoryError ? "ready" : "limited";',
        'capabilities.dataset.state = distributionReady && !repositoryError ? "ready" : "limited";',
        1,
    )
    capability_append_anchor = '''    capabilities.append(heading, copy);
    capabilities.dataset.state = distributionReady && !repositoryError ? "ready" : "limited";
'''
    capability_append_replacement = '''    capabilities.append(heading, copy);
    if (scaffoldLifecycle && releaseChannels.length) {
      const releaseControl = document.createElement("label");
      releaseControl.className = "modules-release-channel";
      releaseControl.textContent = "Release channel";
      const releaseSelect = document.createElement("select");
      releaseSelect.setAttribute("aria-label", "MonitorBox release channel");
      for (const channel of releaseChannels) {
        const option = document.createElement("option");
        option.value = channel;
        option.textContent = channel;
        option.selected = channel === preferredChannel;
        releaseSelect.append(option);
      }
      releaseSelect.disabled = !authenticated || !csrfToken || busy || Boolean(current.platform_updating);
      releaseSelect.title = !authenticated || !csrfToken
        ? "Administrator authentication required"
        : Boolean(current.platform_updating)
          ? "MonitorBox lifecycle activation is already in progress"
          : "Bounded by deployment ceiling: " + (current.channel_ceiling || "unknown");
      releaseSelect.addEventListener("change", () => changeReleaseChannel(releaseSelect.value));
      releaseControl.append(releaseSelect);
      capabilities.append(releaseControl);
    }
    capabilities.dataset.state = distributionReady && !repositoryError ? "ready" : "limited";
'''
    if text.count(capability_append_anchor) != 1:
        raise SuccessorModuleError("UI release-channel capability boundary changed unexpectedly")
    text = text.replace(capability_append_anchor, capability_append_replacement, 1)
    if text.count(
        "checkUpdates.disabled = !catalogRefresh || !authenticated || !csrfToken || busy;"
    ) != 1:
        raise SuccessorModuleError("UI check-updates capability boundary changed unexpectedly")
    text = text.replace(
        "checkUpdates.disabled = !catalogRefresh || !authenticated || !csrfToken || busy;",
        "checkUpdates.disabled = (!catalogRefresh && !scaffoldLifecycle) || !authenticated || !csrfToken || busy;",
        1,
    )
    if text.count('checkUpdates.title = !catalogRefresh') != 1:
        raise SuccessorModuleError("UI check-updates title boundary changed unexpectedly")
    text = text.replace(
        'checkUpdates.title = !catalogRefresh',
        'checkUpdates.title = (!catalogRefresh && !scaffoldLifecycle)',
        1,
    )

    old_update_gate = '''    const updates = installed.reduce(
      (count, module) => count + ((Array.isArray(module.actions) && module.actions.includes("update")) ? 1 : 0),
      0
    );
    const packageInstall = Boolean(model && model.capabilities && model.capabilities.package_install);
    updateAll.disabled = !authenticated || !csrfToken || !packageInstall || updates === 0 || busy;
    updateAll.textContent = updates > 0 ? `Update All (${updates})` : "Update All";
'''
    new_update_gate = '''    const capabilities = model && model.capabilities ? model.capabilities : {};
    const scaffoldLifecycle = Boolean(capabilities.scaffold_lifecycle);
    const legacyUpdates = installed.reduce(
      (count, module) => count + ((Array.isArray(module.actions) && module.actions.includes("update")) ? 1 : 0),
      0
    );
    const updates = scaffoldLifecycle
      ? Number(capabilities.platform_update_count || 0)
      : legacyUpdates;
    const updatePlane = scaffoldLifecycle || Boolean(capabilities.package_install);
    updateAll.disabled = !authenticated || !csrfToken || !updatePlane || updates === 0 || busy;
    updateAll.textContent = updates > 0 ? `Update All (${updates})` : "Update All";
'''
    if text.count(old_update_gate) != 1:
        raise SuccessorModuleError("UI Update All gate boundary changed unexpectedly")
    text = text.replace(old_update_gate, new_update_gate, 1)

    release_handler_anchor = "  async function updateAllModules() {"
    release_handler = '''  async function changeReleaseChannel(channel) {
    const capabilities = model && model.capabilities ? model.capabilities : {};
    const allowed = Array.isArray(capabilities.release_channels)
      ? capabilities.release_channels
      : [];
    if (!capabilities.scaffold_lifecycle || !allowed.includes(channel)) {
      setStatus("Release-channel change is not permitted by current scaffold authority.", true);
      renderCapabilities();
      return;
    }
    if (!authenticated || !csrfToken || busy) {
      renderCapabilities();
      return;
    }

    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus("Switching signed MonitorBox release channel to " + channel + "…");
    try {
      const payload = await jsonRequest(RELEASE_CHANNEL_API, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [CSRF_HEADER]: csrfToken,
        },
        body: JSON.stringify({ channel }),
      });
      const scaffoldActivation = Boolean(payload.accepted)
        || payload.runtime_reconcile === "scaffold_activation_scheduled";
      if (scaffoldActivation) {
        setStatus(
          "Release channel " + channel + " accepted. MonitorBox is activating the signed generation; reconnecting may take a moment."
        );
      } else {
        await loadModel();
        setStatus("Release channel is " + (payload.preferred_channel || channel) + ".");
      }
    } catch (error) {
      setStatus(error.message || String(error), true);
      await loadModel().catch(() => {});
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  }

  async function updateAllModules() {'''
    if text.count(release_handler_anchor) != 1:
        raise SuccessorModuleError("UI release-channel handler boundary changed unexpectedly")
    text = text.replace(release_handler_anchor, release_handler, 1)

    update_start = text.find("  async function updateAllModules() {")
    update_end = text.find('  repositoryForm.addEventListener("submit"', update_start)
    if update_start < 0 or update_end < 0:
        raise SuccessorModuleError("UI Update All handler boundary changed unexpectedly")
    new_update_handler = '''  async function updateAllModules() {
    if (!authenticated || !csrfToken || busy) return;
    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    const scaffoldLifecycle = Boolean(model?.capabilities?.scaffold_lifecycle);
    setStatus(scaffoldLifecycle
      ? "Applying compatible signed MonitorBox updates…"
      : "Applying compatible cached module updates independently…");
    try {
      const payload = await jsonRequest(UPDATE_ALL_API, {
        method: "POST",
        headers: { [CSRF_HEADER]: csrfToken },
      });
      const scaffoldActivation = Boolean(payload.accepted)
        || payload.runtime_reconcile === "scaffold_activation_scheduled";
      if (scaffoldActivation) {
        const pending = Number(payload.pending || 0);
        setStatus(
          `Update accepted${pending ? ` for ${pending} package${pending === 1 ? "" : "s"}` : ""}. MonitorBox is activating the signed generation; reconnecting may take a moment.`
        );
      } else {
        const summary = `${payload.updated || 0} updated, ${payload.failed || 0} failed.`;
        setStatus(
          payload.runtime_reconcile === "restart_scheduled"
            ? `${summary} Module authority committed; MonitorBox restart scheduled.`
            : summary,
          Boolean(payload.failed)
        );
        if (payload.runtime_reconcile !== "restart_scheduled") {
          await loadModel();
        }
      }
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  }

'''
    text = text[:update_start] + new_update_handler + text[update_end:]

    check_start = text.find('  checkUpdates.addEventListener("click", async () => {')
    check_end = text.find('  updateAll.addEventListener("click", updateAllModules);', check_start)
    if check_start < 0 or check_end < 0:
        raise SuccessorModuleError("UI Check for Updates handler boundary changed unexpectedly")
    new_check_handler = '''  checkUpdates.addEventListener("click", async () => {
    const capabilities = model && model.capabilities ? model.capabilities : {};
    const scaffoldLifecycle = Boolean(capabilities.scaffold_lifecycle);
    if (!capabilities.catalog_refresh && !scaffoldLifecycle) {
      setStatus("Update discovery is unavailable in this build.", true);
      return;
    }
    if (!authenticated || !csrfToken || busy) return;

    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus(scaffoldLifecycle
      ? "Checking the signed MonitorBox release channel for updates…"
      : "Checking configured module repositories for updates…");
    try {
      const payload = await jsonRequest(CHECK_UPDATES_API, {
        method: "POST",
        headers: { [CSRF_HEADER]: csrfToken },
      });
      await loadModel();
      const failed = Number(payload.failed || 0);
      if (scaffoldLifecycle) {
        const updates = Number(payload.platform_update_count || 0);
        setStatus(
          updates > 0
            ? `Update check complete: ${updates} signed package${updates === 1 ? "" : "s"} available.`
            : "Update check complete: MonitorBox is current.",
          failed > 0
        );
      } else {
        const refreshed = Number(payload.refreshed || 0);
        setStatus(
          `Repository check complete: ${refreshed} refreshed, ${failed} failed.`,
          failed > 0
        );
      }
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  });

'''
    text = text[:check_start] + new_check_handler + text[check_end:]
    files[member] = text.encode("utf-8")

    css_members = [
        name for name, payload in files.items()
        if name.endswith(UI_MODULES_CSS_MEMBER_SUFFIX) and isinstance(payload, bytes)
    ]
    if len(css_members) != 1:
        raise SuccessorModuleError(
            "UI predecessor must contain exactly one assets/modules.css member"
        )
    css_member = css_members[0]
    css_payload = files[css_member]
    assert isinstance(css_payload, bytes)
    try:
        css_text = css_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuccessorModuleError("UI predecessor modules.css is not UTF-8") from exc
    release_css = """
.modules-release-channel {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: 12px;
  color: #c9d5e5;
  font-size: .9rem;
  white-space: nowrap;
}

.modules-release-channel select {
  border: 1px solid rgba(255, 255, 255, .16);
  border-radius: 8px;
  background: rgba(0, 0, 0, .22);
  color: inherit;
  padding: 6px 9px;
}

@media (max-width: 760px) {
  .modules-release-channel {
    display: flex;
    margin: 12px 0 0;
    width: 100%;
  }
}
"""
    if ".modules-release-channel {" in css_text:
        raise SuccessorModuleError("UI predecessor unexpectedly already has release-channel CSS")
    files[css_member] = (css_text.rstrip() + "\n" + release_css.lstrip()).encode("utf-8")


def _successor_runtime_overlays(
    record: dict[str, Any],
    files: dict[str, bytes | None],
) -> None:
    """Apply narrowly bounded successor-only runtime/operator overlays."""

    artifact_id = record["artifact_id"]
    if artifact_id == PORTAINER_ID:
        _apply_portainer_successor_overlay(files)
    elif artifact_id == SCRYPTED_ID:
        _apply_scrypted_successor_overlay(files)
    elif artifact_id == UI_ID:
        _apply_ui_successor_overlay(files)



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
