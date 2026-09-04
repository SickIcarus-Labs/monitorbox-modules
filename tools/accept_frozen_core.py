#!/usr/bin/env python3
"""Exercise generated UI packages through the exact frozen Core lifecycle substrate.

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
EXPECTED_RELEASES = (2, 3, 4, 5)


def _ui_releases(source: dict) -> dict[int, dict]:
    releases = {
        item["manifest"]["build"]: item
        for item in source["modules"]
        if item["manifest"]["module_id"] == MODULE_ID
    }
    if tuple(sorted(releases)) != EXPECTED_RELEASES:
        raise AssertionError(
            f"expected UI builds {EXPECTED_RELEASES}, got {tuple(sorted(releases))}"
        )
    return releases


def _assert_package_shape(root: Path, source: dict) -> None:
    by_build = _ui_releases(source)
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
            expected_delta = build_number in {3, 4, 5}
            if (discovery in names) != expected_delta:
                raise AssertionError(
                    f"certified discovery override shape is wrong for build {build_number}"
                )
            if (endpoint in names) != expected_delta:
                raise AssertionError(
                    f"certified endpoint-prefill shape is wrong for build {build_number}"
                )

            hierarchy = {
                f"{import_package}/assets/service-presentation.js",
                f"{import_package}/assets/service-presentation.css",
            }
            if hierarchy.issubset(names) != (build_number == 5):
                raise AssertionError(
                    f"Compose hierarchy override shape is wrong for build {build_number}"
                )


def _effective_package(runtime: ModuleManagementRuntime, build_number: int):
    packages = runtime.effective_source(TestModuleSource(())).packages()
    matches = [package for package in packages if package.manifest.module_id == MODULE_ID]
    if len(matches) != 1:
        raise AssertionError(f"expected one effective managed UI package, got {len(matches)}")
    package = matches[0]
    if package.manifest.build != build_number:
        raise AssertionError(
            f"expected effective {MODULE_ID} build {build_number}, got build {package.manifest.build}"
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
    """Prove the admitted webui entrypoint composes successfully with frozen Core 0547."""

    from aiohttp import web

    package = _effective_package(runtime, build_number)
    app = web.Application()
    package.entrypoints["webui"](app)
    routes = {route.resource.canonical for route in app.router.routes()}
    required = {"/", "/modules", "/api/v2/build", "/static/icons/{name}", "/static/{name}"}
    missing = required - routes
    if missing:
        raise AssertionError(f"managed UI build {build_number} omitted routes: {sorted(missing)}")


def _ui_snapshot_entries(snapshot):
    return [entry for entry in snapshot.entries if entry.manifest.module_id == MODULE_ID]


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
        ui_entries = _ui_snapshot_entries(snapshot)
        if tuple(entry.manifest.build for entry in ui_entries) != EXPECTED_RELEASES:
            raise AssertionError(
                "signed catalog did not expose all certified UI generations in order"
            )

        # Exercise each generation so build 5 cannot hide an admission/entrypoint
        # break behind its predecessor's already-certified path.
        for expected_build in EXPECTED_RELEASES:
            entry = next(item for item in ui_entries if item.manifest.build == expected_build)
            artifact, payload = await client.provide(entry)
            installed = management.install_verified(artifact, payload)
            if installed.active.manifest.build != expected_build:
                raise AssertionError(f"failed to activate UI build {expected_build}")
            _assert_installable(management, expected_build)

        # User-facing rollback from the new build must restore the exact prior
        # managed generation (build 4), not the factory seed or an older delta.
        rolled_back = management.manager.rollback(MODULE_ID)
        if rolled_back.active.manifest.build != 4:
            raise AssertionError("managed UI rollback did not restore build 4")
        _assert_installable(management, 4)

        restarted = ModuleManagementRuntime.for_root(temp / "appliance")
        _assert_installable(restarted, 4)
        record = next(
            item for item in restarted.state.installed_records() if item.module_id == MODULE_ID
        )
        if record.previous is None or record.previous.manifest.build != 5:
            raise AssertionError("rollback did not retain build 5 as the reversible prior generation")

        build5_entry = next(item for item in ui_entries if item.manifest.build == 5)
        build5_artifact, build5_payload = await client.provide(build5_entry)
        reinstalled = restarted.install_verified(build5_artifact, build5_payload)
        if reinstalled.active.manifest.build != 5:
            raise AssertionError("build 5 could not be reactivated after restart/rollback")
        _assert_installable(restarted, 5)

    print(
        "frozen Core managed UI acceptance: PASS "
        "(build 2 -> 3 -> 4 -> 5 -> rollback 4 -> restart -> build 5)"
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    asyncio.run(_accept(root))


if __name__ == "__main__":
    main()
