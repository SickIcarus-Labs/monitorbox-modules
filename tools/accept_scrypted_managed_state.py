#!/usr/bin/env python3
"""Regression for Scrypted 2.1.2 build 3 managed bridge IPC state."""

from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from accept_http_behavior import install_core_contract_stubs
from accept_scrypted_media import _install_media_contracts

PACKAGE_NAME = "com.sickicarus.monitorbox.scrypted-2.1.2-build3.zip"
IMPORT_PACKAGE = "monitorbox_scrypted_v212_b3"
LEGACY_SOCKET = "/run/monitorbox-scrypted/bridge.sock"


def _install_runtime_contracts(plugin_api) -> None:
    @dataclass(frozen=True)
    class RuntimeExecutionContext:
        module_id: str
        package_root: str
        state_root: str

    @dataclass(frozen=True)
    class RuntimeExecutionRequest:
        check_id: str
        object_id: str
        adapter: str
        timeout_seconds: float
        options: Mapping[str, Any] = field(default_factory=dict)
        agent_id: str | None = None
        capability_id: str | None = None
        capability_kind: str | None = None

    @dataclass(frozen=True)
    class RuntimeExecutionResult:
        state: str
        summary: str
        duration_ms: float
        metrics: Mapping[str, float] = field(default_factory=dict)
        metadata: Mapping[str, Any] = field(default_factory=dict)

        def public(self):
            return {
                "state": self.state,
                "summary": self.summary,
                "duration_ms": self.duration_ms,
                "metrics": dict(self.metrics),
                "metadata": dict(self.metadata),
            }

    for value in (RuntimeExecutionContext, RuntimeExecutionRequest, RuntimeExecutionResult):
        setattr(plugin_api, value.__name__, value)


def _install_generic_storage_stubs() -> None:
    from types import ModuleType

    canonical = ModuleType("monitorbox.v2.canonical_store")
    secrets = ModuleType("monitorbox.v2.secret_store")

    class CanonicalConfigStore:
        def __init__(self, root):
            self.root = root

    class ProtectedSecretStore:
        def __init__(self, root):
            self.root = root

    canonical.CanonicalConfigStore = CanonicalConfigStore
    secrets.ProtectedSecretStore = ProtectedSecretStore
    sys.modules[canonical.__name__] = canonical
    sys.modules[secrets.__name__] = secrets


async def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed Scrypted build 3 package is missing: {package}")

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required = {
            f"{IMPORT_PACKAGE}/runtime.py",
            f"{IMPORT_PACKAGE}/state_socket.py",
            f"{IMPORT_PACKAGE}/onboarding.py",
            f"{IMPORT_PACKAGE}/legacy_control.py",
            f"{IMPORT_PACKAGE}/bridge/server.mjs",
        }
        missing = required - names
        if missing:
            raise AssertionError(f"Scrypted build 3 omitted managed-state assets: {sorted(missing)}")
        runtime_text = archive.read(f"{IMPORT_PACKAGE}/runtime.py").decode("utf-8")
        onboarding_text = archive.read(f"{IMPORT_PACKAGE}/onboarding.py").decode("utf-8")

    if "del context\n        await self._bridge.start()" in runtime_text:
        raise AssertionError("Scrypted build 3 still discards Core RuntimeExecutionContext")
    if "await self._bridge.start(context.state_root)" not in runtime_text:
        raise AssertionError("Scrypted build 3 does not consume Core-managed state_root")
    if LEGACY_SOCKET in onboarding_text:
        raise AssertionError("new Scrypted onboarding still persists unmanaged /run IPC state")

    plugin_api = install_core_contract_stubs()
    _install_runtime_contracts(plugin_api)
    _install_media_contracts(plugin_api)
    _install_generic_storage_stubs()
    sys.path.insert(0, str(package))
    try:
        managed = importlib.import_module(IMPORT_PACKAGE)
        runtime = importlib.import_module(f"{IMPORT_PACKAGE}.runtime")
        socket_policy = importlib.import_module(f"{IMPORT_PACKAGE}.state_socket")

        if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("2.1.2", 3):
            raise AssertionError("Scrypted build 3 release identity changed")
        if managed.MODULE_MANIFEST.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
            raise AssertionError("Scrypted build 3 entrypoint is not generation-safe")
        if managed.MODULE_MANIFEST.requires_core != ">=2.3.1 <3.0.0":
            raise AssertionError("Scrypted build 3 Core compatibility changed")

        with tempfile.TemporaryDirectory(prefix="monitorbox-scrypted-state-") as raw_state:
            state_root = str(Path(raw_state) / "module-state")
            expected_socket = str(Path(state_root) / "bridge.sock")

            if socket_policy.resolve_managed_socket(LEGACY_SOCKET, state_root) != expected_socket:
                raise AssertionError("legacy Scrypted /run socket did not relocate into module state_root")
            if socket_policy.resolve_managed_socket(None, state_root) != expected_socket:
                raise AssertionError("missing Scrypted socket did not default into module state_root")
            explicit = str(Path(raw_state) / "explicit.sock")
            if socket_policy.resolve_managed_socket(explicit, state_root) != explicit:
                raise AssertionError("explicit absolute Scrypted validation socket was rewritten")

            executor = runtime.ScryptedRuntimeExecutor()
            captured_start: list[str | None] = []

            async def capture_start(value=None):
                executor._bridge._state_root = value
                captured_start.append(value)

            executor._bridge.start = capture_start
            context = plugin_api.RuntimeExecutionContext(
                module_id=managed.MODULE_ID,
                package_root=str(package),
                state_root=state_root,
            )
            await executor.start(context)
            if captured_start != [state_root]:
                raise AssertionError(f"runtime state_root was not handed to bridge worker: {captured_start!r}")

            bridge = executor._bridge
            captured_configs = []

            async def capture_config(config):
                captured_configs.append(config)

            bridge._ensure_locked = capture_config
            runtime.resolve_legacy_worker_config = lambda: {
                "base_url": "https://192.0.2.20:10443",
                "username_env": "SCRYPTED_USER",
                "username": "user",
                "password_env": "SCRYPTED_PASSWORD",
                "password": "password",
                "socket": LEGACY_SOCKET,
                "excluded_camera_names": (),
            }
            resolved = await bridge.ensure(
                {"operation": "inventory", "socket": LEGACY_SOCKET},
                wait_for_control=False,
            )
            if resolved != expected_socket or len(captured_configs) != 1:
                raise AssertionError("legacy Scrypted worker control did not relocate to managed state")
            active = captured_configs[-1]
            if active.socket != expected_socket:
                raise AssertionError(f"worker received unmanaged IPC path: {active.socket!r}")

            bridge._last_config = active
            captured_configs.clear()
            camera_socket = await bridge.ensure(
                {"operation": "camera_state", "socket": LEGACY_SOCKET, "camera_id": "front-door"},
                wait_for_control=True,
            )
            if camera_socket != expected_socket or captured_configs != [active]:
                raise AssertionError("legacy camera checks do not reuse normalized managed worker IPC")

    finally:
        if sys.path and sys.path[0] == str(package):
            sys.path.pop(0)

    print("managed Scrypted 2.1.2 build 3 Core-owned state acceptance: PASS", flush=True)


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
