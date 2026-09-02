#!/usr/bin/env python3
"""Exercise generated first-party packages through the exact frozen Core lifecycle substrate.

This script intentionally imports MonitorBox runtime code from its caller. In pre-publication
CI it is run from a test-only branch based on the certified frozen Core SHA; it does not require
or modify MonitorBox Core from this public repository.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from build_repository import build as build_repository
from monitorbox.v2.module_management_runtime import ModuleManagementRuntime
from monitorbox.v2.module_repository import RepositoryTrustRoot, TrustedModuleRepositoryClient
from monitorbox.v2.plugin_api.module_management import RepositoryDefinition
from monitorbox.v2.plugin_api.module_runtime import TestModuleSource

REPOSITORY_ID = "official"
DISPLAY_NAME = "MonitorBox Official"
SIGNATURE_IDENTITY = "acceptance-ephemeral-ed25519"
MODULE_ID = "com.sickicarus.monitorbox.ui"
EXPECTED_RELEASES = (2, 3)


def _assert_package_shape(root: Path, source: dict) -> None:
    by_build = {item["manifest"]["build"]: item for item in source["modules"]}
    if tuple(sorted(by_build)) != EXPECTED_RELEASES:
        raise AssertionError(f"expected UI builds {EXPECTED_RELEASES}, got {tuple(sorted(by_build))}")

    for build_number, item in sorted(by_build.items()):
        package_path = root / "packages" / item["package"]
        import_package = f"monitorbox_ui_b{build_number}"
        expected_entrypoint = f"{import_package}:install"
        if item["manifest"]["entrypoints"] != {"webui": expected_entrypoint}:
            raise AssertionError(f"build {build_number} entrypoint is not generation-specific")
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            if f"{import_package}/__init__.py" not in names:
                raise AssertionError(f"build {build_number} package root is missing")
            if any(name.startswith("monitorbox/") for name in names):
                raise AssertionError("managed UI package may not shadow the loaded Core namespace")

            discovery = f"{import_package}/assets/discovery-v22.js"
            endpoint = f"{import_package}/assets/endpoint-prefill-v22.js"
            expected_delta = build_number == 3
            if (discovery in names) != expected_delta:
                raise AssertionError(
                    "certified discovery override must be absent from build 2 and present in build 3"
                )
            if (endpoint in names) != expected_delta:
                raise AssertionError(
                    "certified endpoint-prefill asset must be absent from build 2 and present in build 3"
                )


def _effective_package(runtime: ModuleManagementRuntime, build_number: int):
    packages = runtime.effective_source(TestModuleSource(())).packages()
    if len(packages) != 1:
        raise AssertionError(f"expected one effective managed package, got {len(packages)}")
    package = packages[0]
    if package.manifest.module_id != MODULE_ID or package.manifest.build != build_number:
        raise AssertionError(
            f"expected effective {MODULE_ID} build {build_number}, got "
            f"{package.manifest.module_id} build {package.manifest.build}"
        )
    entrypoint = package.entrypoints["webui"]
    expected_module = f"monitorbox_ui_b{build_number}"
    if entrypoint.__module__ != expected_module:
        raise AssertionError(
            f"build {build_number} resolved through wrong Python module {entrypoint.__module__!r}; "
            f"expected {expected_module!r}"
        )
    return package


def _assert_installable(runtime: ModuleManagementRuntime, build_number: int) -> None:
    """Prove the admitted webui entrypoint composes successfully with the frozen host API."""

    from aiohttp import web

    package = _effective_package(runtime, build_number)
    app = web.Application()
    package.entrypoints["webui"](app)
    routes = {route.resource.canonical for route in app.router.routes()}
    required = {"/", "/modules", "/api/v2/build", "/static/icons/{name}", "/static/{name}"}
    missing = required - routes
    if missing:
        raise AssertionError(f"managed UI build {build_number} omitted routes: {sorted(missing)}")


async def _accept(root: Path) -> None:
    source = json.loads((root / "catalog.source.json").read_text(encoding="utf-8"))
    _assert_package_shape(root, source)

    with tempfile.TemporaryDirectory(prefix="monitorbox-module-repository-") as directory:
        temp = Path(directory)
        repository_root = temp / "repository"
        repository_root.mkdir()
        shutil.copy2(root / "catalog.source.json", repository_root / "catalog.source.json")
        shutil.copytree(root / "packages", repository_root / "packages")

        private_key = Ed25519PrivateKey.generate()
        build_repository(
            repository_root / "catalog.source.json",
            repository_root / "index.json",
            private_key,
            SIGNATURE_IDENTITY,
        )

        management = ModuleManagementRuntime.for_root(temp / "appliance")
        definition = RepositoryDefinition(
            repository_id=REPOSITORY_ID,
            display_name=DISPLAY_NAME,
            index_url=(repository_root / "index.json").resolve().as_uri(),
            official=True,
            enabled=True,
        )
        management.manager.configure_repository(definition)
        client = TrustedModuleRepositoryClient(
            management.manager,
            trust_roots={
                REPOSITORY_ID: RepositoryTrustRoot(
                    repository_id=REPOSITORY_ID,
                    signature_identity=SIGNATURE_IDENTITY,
                    public_key=private_key.public_key().public_bytes_raw(),
                )
            },
        )

        snapshot = await client.refresh(REPOSITORY_ID)
        if tuple(entry.manifest.build for entry in snapshot.entries) != EXPECTED_RELEASES:
            raise AssertionError("signed catalog did not expose both certified UI generations")

        for expected_build in EXPECTED_RELEASES:
            entry = next(item for item in snapshot.entries if item.manifest.build == expected_build)
            artifact, payload = await client.provide(entry)
            installed = management.install_verified(artifact, payload)
            if installed.active.manifest.build != expected_build:
                raise AssertionError(f"failed to activate UI build {expected_build}")
            _assert_installable(management, expected_build)

        rolled_back = management.manager.rollback(MODULE_ID)
        if rolled_back.active.manifest.build != 2:
            raise AssertionError("managed UI rollback did not restore build 2")
        _assert_installable(management, 2)

        restarted = ModuleManagementRuntime.for_root(temp / "appliance")
        _assert_installable(restarted, 2)
        record = restarted.state.installed_records()[0]
        if record.previous is None or record.previous.manifest.build != 3:
            raise AssertionError("rollback did not retain build 3 as the reversible prior generation")

        build3_entry = next(item for item in snapshot.entries if item.manifest.build == 3)
        build3_artifact, build3_payload = await client.provide(build3_entry)
        reinstalled = restarted.install_verified(build3_artifact, build3_payload)
        if reinstalled.active.manifest.build != 3:
            raise AssertionError("build 3 could not be reactivated after restart/rollback")
        _assert_installable(restarted, 3)

    print(
        "frozen Core managed UI acceptance: PASS "
        "(build 2 -> build 3 -> rollback -> restart -> build 3)"
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    asyncio.run(_accept(root))


if __name__ == "__main__":
    main()
