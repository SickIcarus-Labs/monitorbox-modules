#!/usr/bin/env python3
"""Acceptance for Scrypted 2.1.1 build 2 legacy worker-control recovery."""

from __future__ import annotations

import asyncio
import importlib
import sys
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

from accept_http_behavior import install_core_contract_stubs
from accept_scrypted_media import _install_media_contracts

PACKAGE_NAME = "com.sickicarus.monitorbox.scrypted-2.1.1-build2.zip"
IMPORT_PACKAGE = "monitorbox_scrypted_v211_b2"


def _install_generic_core_storage_stubs() -> None:
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
        raise AssertionError(f"managed Scrypted repair package is missing: {package}")

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required = {
            f"{IMPORT_PACKAGE}/__init__.py",
            f"{IMPORT_PACKAGE}/runtime.py",
            f"{IMPORT_PACKAGE}/legacy_control.py",
            f"{IMPORT_PACKAGE}/media.py",
            f"{IMPORT_PACKAGE}/bridge/server.mjs",
            f"{IMPORT_PACKAGE}/bridge/node_modules/@scrypted/client/package.json",
            f"{IMPORT_PACKAGE}/bridge/node_modules/ws/package.json",
        }
        missing = required - names
        if missing:
            raise AssertionError(f"Scrypted 2.1.1 package omitted repair/runtime assets: {sorted(missing)}")
        texts = "\n".join(
            archive.read(name).decode("utf-8")
            for name in names
            if name.startswith(f"{IMPORT_PACKAGE}/") and name.endswith(".py")
        )
    for forbidden in (
        "monitorbox.v2.integrations.scrypted",
        "monitorbox.v2.scrypted_worker",
        "monitorbox.v2.scrypted_sidecar_runtime",
    ):
        if forbidden in texts:
            raise AssertionError(f"Scrypted repair resurrected retired Core provider code: {forbidden}")
    for required_generic in ("monitorbox.v2.canonical_store", "monitorbox.v2.secret_store"):
        if required_generic not in texts:
            raise AssertionError(f"Scrypted repair stopped using generic Core authority seam: {required_generic}")

    plugin_api = install_core_contract_stubs()
    _install_media_contracts(plugin_api)
    _install_generic_core_storage_stubs()
    sys.path.insert(0, str(package))
    managed = importlib.import_module(IMPORT_PACKAGE)
    runtime = importlib.import_module(f"{IMPORT_PACKAGE}.runtime")
    legacy = importlib.import_module(f"{IMPORT_PACKAGE}.legacy_control")

    if (managed.MODULE_VERSION, managed.MODULE_BUILD) != ("2.1.1", 2):
        raise AssertionError("Scrypted repair release identity changed")
    if managed.MODULE_MANIFEST.entrypoints != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
        raise AssertionError("Scrypted repair entrypoint is not generation-safe")
    if managed.MODULE_MANIFEST.requires_core != ">=2.3.1 <3.0.0":
        raise AssertionError("Scrypted repair Core compatibility changed")
    if managed.PLUGIN.runtime_executor is None or managed.PLUGIN.media_executor is None:
        raise AssertionError("Scrypted repair lost runtime/media ownership")

    canonical_document = {
        "runtime": {"local_agent": {"credential_secret_refs": {}}},
        "sites": [
            {
                "id": "broadleaf",
                "objects": [
                    {
                        "id": "arrrrr2_scrypted",
                        "address": "192.168.3.9",
                        "capabilities": [
                            {
                                "providers": [
                                    {
                                        "adapter": "scrypted",
                                        "enabled": True,
                                        "config": {
                                            "operation": "inventory",
                                            "socket": "/run/monitorbox-scrypted/bridge.sock",
                                            "excluded_camera_names": ["Ignored Camera"],
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
    }

    class FakeStore:
        def __init__(self, root):
            self.root = Path(root)

        def exists(self):
            return True

        def load(self):
            return SimpleNamespace(data=canonical_document)

    class FakeSecrets:
        values = {
            "scrypted_username": "legacy-user",
            "scrypted_password": "legacy-password",
        }

        def __init__(self, root):
            self.root = Path(root)

        def exists(self, secret_id):
            return secret_id in self.values

        def read(self, secret_id):
            return self.values[secret_id]

    legacy.CanonicalConfigStore = FakeStore
    legacy.ProtectedSecretStore = FakeSecrets
    recovered = legacy.resolve_legacy_worker_config()
    if recovered is None:
        raise AssertionError("Scrypted repair could not reconstruct persisted worker control")
    if recovered["base_url"] != "https://192.168.3.9:10443":
        raise AssertionError(f"legacy Scrypted base URL fallback changed: {recovered!r}")
    if recovered["socket"] != "/run/monitorbox-scrypted/bridge.sock":
        raise AssertionError(f"legacy Scrypted socket projection changed: {recovered!r}")
    if recovered["username"] != "legacy-user" or recovered["password"] != "legacy-password":
        raise AssertionError("legacy Scrypted protected credentials were not recovered")
    if recovered["excluded_camera_names"] != ("Ignored Camera",):
        raise AssertionError("legacy Scrypted excluded-camera policy changed")

    # Prove the managed worker consumes that reconstruction when an early-2.1
    # persisted runtime check contains operation/socket but no control fields.
    runtime.resolve_legacy_worker_config = lambda: dict(recovered)
    bridge = runtime._BridgeWorker()
    captured = []

    async def capture(config):
        captured.append(config)

    bridge._ensure_locked = capture
    returned_socket = await bridge.ensure(
        {
            "operation": "inventory",
            "socket": "/run/monitorbox-scrypted/bridge.sock",
        },
        wait_for_control=False,
    )
    if returned_socket != "/run/monitorbox-scrypted/bridge.sock" or len(captured) != 1:
        raise AssertionError("Scrypted worker did not consume module-owned legacy control")
    config = captured[0]
    if config.base_url != "https://192.168.3.9:10443" or config.username != "legacy-user":
        raise AssertionError("Scrypted worker reconstruction lost canonical/secret authority")

    # Once a worker generation is active, camera checks may reuse it without
    # repeatedly rereading canonical authority.
    bridge._last_config = config
    runtime.resolve_legacy_worker_config = lambda: (_ for _ in ()).throw(
        AssertionError("active Scrypted worker unexpectedly reread legacy control")
    )
    captured.clear()
    camera_socket = await bridge.ensure(
        {"operation": "camera_state", "socket": config.socket, "camera_id": "front-door"},
        wait_for_control=True,
    )
    if camera_socket != config.socket or captured != [config]:
        raise AssertionError("Scrypted child checks stopped reusing active module-owned worker control")

    print("managed Scrypted 2.1.1 build 2 persisted-generation acceptance: PASS", flush=True)


def main() -> None:
    asyncio.run(accept())


if __name__ == "__main__":
    main()
