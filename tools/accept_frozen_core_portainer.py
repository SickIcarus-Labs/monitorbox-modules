#!/usr/bin/env python3
"""Exercise current managed Portainer through the exact certified Core provider-authority seam.

This script must run with the accepted MonitorBox Core runtime importable. It
proves the real packaged entrypoint can be admitted and imported by Core, then
exercises the production-relevant build-2 -> build-4 update path. This catches
cross-file/import failures that package syntax checks cannot detect.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from build_repository import build as build_repository
from monitorbox.v2.module_management_runtime import ModuleManagementRuntime
from monitorbox.v2.module_repository import RepositoryTrustRoot, TrustedModuleRepositoryClient
from monitorbox.v2.plugin_api.module_management import RepositoryDefinition
from monitorbox.v2.plugin_api.module_runtime import BundledModuleSource
from monitorbox.v2.plugin_api.provider_authority import load_provider_registry

REPOSITORY_ID = "official"
DISPLAY_NAME = "MonitorBox Official"
SIGNATURE_IDENTITY = "acceptance-ephemeral-ed25519"
MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.0.0"
BASE_BUILD = 2
TARGET_BUILD = 4


def _provider_registry(runtime: ModuleManagementRuntime):
    return load_provider_registry(runtime.effective_source(BundledModuleSource()))


def _assert_managed_portainer(
    runtime: ModuleManagementRuntime,
    expected_build: int,
) -> None:
    registry = _provider_registry(runtime)
    definition = registry.require("portainer")
    if registry.module_id_for_plugin("portainer") != MODULE_ID:
        raise AssertionError("Portainer registry owner is not the managed module identity")
    if registry.runtime_executor_owner_for_adapter("portainer") is not definition:
        raise AssertionError("managed Portainer does not own the portainer runtime adapter")
    executor = definition.runtime_executor
    if executor is None:
        raise AssertionError("managed Portainer has no runtime executor")
    expected_package = f"monitorbox_portainer_b{expected_build}"
    if executor.__class__.__module__ != expected_package:
        raise AssertionError(
            f"Portainer build {expected_build} executed through "
            f"{executor.__class__.__module__!r}; expected {expected_package!r}"
        )
    if definition.connection is None or definition.validation is None:
        raise AssertionError("managed Portainer omitted connection/validation ownership")
    if definition.candidate_adoption is None or definition.candidate_review is None:
        raise AssertionError("managed Portainer omitted discovery lifecycle ownership")


def _release(source: dict, build: int) -> dict:
    release = next(
        (
            item
            for item in source["modules"]
            if item["manifest"]["module_id"] == MODULE_ID
            and item["manifest"]["version"] == MODULE_VERSION
            and item["manifest"]["build"] == build
        ),
        None,
    )
    if release is None:
        raise AssertionError(f"Portainer build {build} is missing from catalog.source.json")
    expected_package = f"monitorbox_portainer_b{build}"
    if release["manifest"]["entrypoints"] != {
        "integration": f"{expected_package}:PLUGIN"
    }:
        raise AssertionError(f"Portainer build {build} catalog entrypoint is not generation-safe")
    return release


async def _accept(root: Path) -> None:
    source = json.loads((root / "catalog.source.json").read_text(encoding="utf-8"))
    _release(source, BASE_BUILD)
    _release(source, TARGET_BUILD)

    with tempfile.TemporaryDirectory(prefix="monitorbox-portainer-module-") as directory:
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
        entries = {
            item.manifest.build: item
            for item in snapshot.entries
            if item.manifest.module_id == MODULE_ID
            and item.manifest.version == MODULE_VERSION
        }
        if BASE_BUILD not in entries or TARGET_BUILD not in entries:
            raise AssertionError(
                f"signed catalog omitted required Portainer builds: {sorted(entries)}"
            )

        base_artifact, base_payload = await client.provide(entries[BASE_BUILD])
        installed_base = management.install_verified(base_artifact, base_payload)
        if installed_base.active.manifest.build != BASE_BUILD:
            raise AssertionError("Portainer build 2 did not become active managed authority")
        if installed_base.previous is not None:
            raise AssertionError("first managed Portainer install unexpectedly has a previous artifact")
        _assert_managed_portainer(management, BASE_BUILD)

        target_artifact, target_payload = await client.provide(entries[TARGET_BUILD])
        installed_target = management.install_verified(target_artifact, target_payload)
        if installed_target.active.manifest.build != TARGET_BUILD:
            raise AssertionError("Portainer build 4 did not become active managed authority")
        if installed_target.previous is None or installed_target.previous.manifest.build != BASE_BUILD:
            raise AssertionError("Portainer build-2 -> build-4 update did not retain build 2 for rollback")
        _assert_managed_portainer(management, TARGET_BUILD)

        restarted = ModuleManagementRuntime.for_root(temp / "appliance")
        _assert_managed_portainer(restarted, TARGET_BUILD)
        record = next(
            item for item in restarted.state.installed_records() if item.module_id == MODULE_ID
        )
        if not record.enabled or record.lifecycle_state != "active":
            raise AssertionError("managed Portainer build 4 authority did not persist across restart")
        if record.previous is None or record.previous.manifest.build != BASE_BUILD:
            raise AssertionError("managed Portainer build 4 lost rollback state across restart")

        rolled_back = restarted.manager.rollback(MODULE_ID)
        if rolled_back.active.manifest.build != BASE_BUILD:
            raise AssertionError("Portainer rollback did not restore build 2")
        _assert_managed_portainer(restarted, BASE_BUILD)

        reinstalled = restarted.install_verified(target_artifact, target_payload)
        if reinstalled.active.manifest.build != TARGET_BUILD:
            raise AssertionError("Portainer build 4 could not be reactivated after rollback")
        _assert_managed_portainer(restarted, TARGET_BUILD)

        disabled = restarted.manager.set_enabled(MODULE_ID, False)
        if disabled.enabled or disabled.lifecycle_state != "disabled":
            raise AssertionError("optional managed Portainer could not be disabled")
        disabled_registry = _provider_registry(restarted)
        if disabled_registry.get("portainer") is not None:
            raise AssertionError(
                "disabled managed Portainer leaked through to managed or bundled provider authority"
            )

        reenabled = restarted.manager.set_enabled(MODULE_ID, True)
        if not reenabled.enabled or reenabled.lifecycle_state != "active":
            raise AssertionError("managed Portainer could not be re-enabled")
        _assert_managed_portainer(restarted, TARGET_BUILD)

    print(
        "frozen Core managed Portainer acceptance: PASS "
        "(build 2 -> build 4 -> restart -> rollback -> build 4 -> disable/reactivate)"
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    asyncio.run(_accept(root))


if __name__ == "__main__":
    main()
