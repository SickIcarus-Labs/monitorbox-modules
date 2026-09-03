#!/usr/bin/env python3
"""Exercise managed Portainer through the exact certified Core provider-authority seam.

This script is intended to run from an environment that supplies the certified
MonitorBox Core runtime. The public module repository owns package/repository
bytes only; Core remains the authority for admission, persistence, effective
source composition, provider registry construction, and lifecycle transitions.
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
MODULE_BUILD = 2
IMPORT_PACKAGE = "monitorbox_portainer_b2"


def _provider_registry(runtime: ModuleManagementRuntime):
    return load_provider_registry(runtime.effective_source(BundledModuleSource()))


def _assert_managed_portainer(runtime: ModuleManagementRuntime) -> None:
    registry = _provider_registry(runtime)
    definition = registry.require("portainer")
    if registry.module_id_for_plugin("portainer") != MODULE_ID:
        raise AssertionError("Portainer registry owner is not the managed module identity")
    if registry.runtime_executor_owner_for_adapter("portainer") is not definition:
        raise AssertionError("managed Portainer does not own the portainer runtime adapter")
    executor = definition.runtime_executor
    if executor is None:
        raise AssertionError("managed Portainer has no runtime executor")
    if executor.__class__.__module__ != IMPORT_PACKAGE:
        raise AssertionError(
            f"Portainer executed through {executor.__class__.__module__!r}; "
            f"expected generation-safe managed package {IMPORT_PACKAGE!r}"
        )
    if definition.connection is None or definition.validation is None:
        raise AssertionError("managed Portainer omitted connection/validation ownership")
    if definition.candidate_adoption is None or definition.candidate_review is None:
        raise AssertionError("managed Portainer omitted discovery lifecycle ownership")


async def _accept(root: Path) -> None:
    source = json.loads((root / "catalog.source.json").read_text(encoding="utf-8"))
    release = next(
        (
            item
            for item in source["modules"]
            if item["manifest"]["module_id"] == MODULE_ID
            and item["manifest"]["version"] == MODULE_VERSION
            and item["manifest"]["build"] == MODULE_BUILD
        ),
        None,
    )
    if release is None:
        raise AssertionError("Portainer build 2 is missing from catalog.source.json")
    if release["manifest"]["entrypoints"] != {"integration": f"{IMPORT_PACKAGE}:PLUGIN"}:
        raise AssertionError("Portainer catalog entrypoint is not generation-safe")

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
        entry = next(
            (
                item
                for item in snapshot.entries
                if item.manifest.module_id == MODULE_ID
                and item.manifest.version == MODULE_VERSION
                and item.manifest.build == MODULE_BUILD
            ),
            None,
        )
        if entry is None:
            raise AssertionError("signed catalog did not expose Portainer build 2")

        artifact, payload = await client.provide(entry)
        installed = management.install_verified(artifact, payload)
        if installed.active.manifest.module_id != MODULE_ID or installed.active.manifest.build != MODULE_BUILD:
            raise AssertionError("Portainer build 2 did not become active managed authority")
        if installed.previous is not None:
            raise AssertionError("first managed Portainer install unexpectedly has a previous artifact")
        _assert_managed_portainer(management)

        restarted = ModuleManagementRuntime.for_root(temp / "appliance")
        _assert_managed_portainer(restarted)
        record = next(
            item for item in restarted.state.installed_records() if item.module_id == MODULE_ID
        )
        if not record.enabled or record.lifecycle_state != "active":
            raise AssertionError("managed Portainer authority did not persist across runtime reconstruction")

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
        _assert_managed_portainer(restarted)

    print(
        "frozen Core managed Portainer acceptance: PASS "
        "(install -> managed registry -> restart -> disabled suppression -> reactivate)"
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    asyncio.run(_accept(root))


if __name__ == "__main__":
    main()
