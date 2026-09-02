#!/usr/bin/env python3
"""Exercise generated first-party packages through the exact frozen Core lifecycle substrate."""

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
EXPECTED_RELEASES = (2, 3)


def _assert_package_shape(root: Path, source: dict) -> None:
    by_build = {item["manifest"]["build"]: item for item in source["modules"]}
    if tuple(sorted(by_build)) != EXPECTED_RELEASES:
        raise AssertionError(f"expected UI builds {EXPECTED_RELEASES}, got {tuple(sorted(by_build))}")

    for build_number, item in sorted(by_build.items()):
        package_name = item["package"]
        package_path = root / "packages" / package_name
        import_package = f"monitorbox_ui_b{build_number}"
        expected_entrypoint = f"{import_package}:install"
        if item["manifest"]["entrypoints"] != {"webui": expected_entrypoint}:
            raise AssertionError(f"build {build_number} entrypoint is not generation-specific")
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            if f"{import_package}/__init__.py" not in names:
                raise AssertionError(f"build {build_number} package root is missing")
            if f"{import_package}/application.py" not in names:
                raise AssertionError(f"build {build_number} application is missing")
            if any(name.startswith("monitorbox/") for name in names):
                raise AssertionError("managed UI package may not shadow the loaded Core namespace")
            endpoint_asset = f"{import_package}/static/endpoint-prefill-v22.js"
            if (endpoint_asset in names) != (build_number == 3):
                raise AssertionError(
                    "certified endpoint-prefill asset must be absent from build 2 and present in build 3"
                )


def _assert_effective_build(runtime: ModuleManagementRuntime, build_number: int) -> None:
    packages = runtime.effective_source(TestModuleSource(())).packages()
    if len(packages) != 1:
        raise AssertionError(f"expected one effective managed package, got {len(packages)}")
    package = packages[0]
    if package.manifest.build != build_number:
        raise AssertionError(
            f"expected effective build {build_number}, got {package.manifest.build}"
        )
    entrypoint = package.entrypoints["webui"]
    expected_module = f"monitorbox_ui_b{build_number}.application"
    if entrypoint.__module__ != expected_module:
        raise AssertionError(
            f"build {build_number} resolved through wrong Python module {entrypoint.__module__!r}; "
            f"expected {expected_module!r}"
        )


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
            entry = next(
                item for item in snapshot.entries if item.manifest.build == expected_build
            )
            artifact, payload = await client.provide(entry)
            installed = management.install_verified(artifact, payload)
            if installed.active.manifest.build != expected_build:
                raise AssertionError(f"failed to activate UI build {expected_build}")
            _assert_effective_build(management, expected_build)

        rolled_back = management.manager.rollback("com.sickicarus.monitorbox.ui")
        if rolled_back.active.manifest.build != 2:
            raise AssertionError("managed UI rollback did not restore build 2")
        _assert_effective_build(management, 2)

        restarted = ModuleManagementRuntime.for_root(temp / "appliance")
        _assert_effective_build(restarted, 2)
        record = restarted.state.installed_records()[0]
        if record.previous is None or record.previous.manifest.build != 3:
            raise AssertionError("rollback did not retain build 3 as the reversible prior generation")

        build3_entry = next(item for item in snapshot.entries if item.manifest.build == 3)
        build3_artifact, build3_payload = await client.provide(build3_entry)
        reinstalled = restarted.install_verified(build3_artifact, build3_payload)
        if reinstalled.active.manifest.build != 3:
            raise AssertionError("build 3 could not be reactivated after restart/rollback")
        _assert_effective_build(restarted, 3)

    print(
        "frozen Core managed UI acceptance: PASS "
        "(build 2 -> build 3 -> rollback -> restart -> build 3)"
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    asyncio.run(_accept(root))


if __name__ == "__main__":
    main()
