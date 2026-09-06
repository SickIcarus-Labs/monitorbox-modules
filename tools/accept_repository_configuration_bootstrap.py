#!/usr/bin/env python3
"""Repository acceptance through Configuration/Bootstrap 1.0.1 build 2."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_wol as previous

MODULE_ID = "com.sickicarus.monitorbox.configuration-bootstrap"
HISTORICAL_RELEASE = (MODULE_ID, "1.0.0", 1)
RELEASE = (MODULE_ID, "1.0.1", 2)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {HISTORICAL_RELEASE, RELEASE}


def _release(source: dict, identity: tuple[str, str, int]) -> dict:
    item = next(
        (
            candidate
            for candidate in source.get("modules", [])
            if stable._release_identity(candidate) == identity
        ),
        None,
    )
    if item is None:
        raise AssertionError(f"Configuration/Bootstrap release missing: {identity}")
    return item


def _assert_package(
    root: Path,
    release: dict,
    *,
    filename: str,
    source_name: str,
    required: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> None:
    package_path = root / "packages" / release["package"]
    if package_path.name != filename or not package_path.is_file():
        raise AssertionError(f"Configuration/Bootstrap package missing or misnamed: {filename}")
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != {source_name}:
            raise AssertionError(
                "Configuration/Bootstrap package shape changed: "
                f"expected={[source_name]}, actual={sorted(names)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed package may not shadow Core's monitorbox namespace")
        payload = archive.read(source_name)
        compile(payload, source_name, "exec")
        text = payload.decode("utf-8")
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise AssertionError(f"Configuration/Bootstrap package omitted markers: {missing}")
    present = [marker for marker in forbidden if marker in text]
    if present:
        raise AssertionError(f"Configuration/Bootstrap package violates boundary: {present}")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    historical = _release(source, HISTORICAL_RELEASE)
    historical_manifest = {
        "module_id": MODULE_ID,
        "display_name": "Configuration / Bootstrap",
        "version": "1.0.0",
        "build": 1,
        "schema": 1,
        "state_schema": 1,
        "module_type": "configuration",
        "entrypoints": {"configuration": "monitorbox_configuration_bootstrap_b1:install"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    }
    if historical.get("manifest") != historical_manifest:
        raise AssertionError("immutable Configuration/Bootstrap build 1 manifest changed")
    _assert_package(
        root,
        historical,
        filename=f"{MODULE_ID}-1.0.0-build1.zip",
        source_name="monitorbox_configuration_bootstrap_b1.py",
        required=(
            "from monitorbox.v2.modules.configuration_bootstrap import (",
            "FACTORY_BUILD",
            "factory.install(",
        ),
        forbidden=(),
    )

    current = _release(source, RELEASE)
    current_manifest = {
        "module_id": MODULE_ID,
        "display_name": "Configuration / Bootstrap",
        "version": "1.0.1",
        "build": 2,
        "schema": 1,
        "state_schema": 1,
        "module_type": "configuration",
        "entrypoints": {"configuration": "monitorbox_configuration_bootstrap_b2:install"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    }
    if current.get("manifest") != current_manifest:
        raise AssertionError(f"Configuration/Bootstrap build 2 manifest changed: {current.get('manifest')!r}")
    _assert_package(
        root,
        current,
        filename=f"{MODULE_ID}-1.0.1-build2.zip",
        source_name="monitorbox_configuration_bootstrap_b2.py",
        required=(
            "from monitorbox.v2.quick_add_ui import QuickAddUi",
            "from monitorbox.v2.setup_draft_ui import SetupDraftUi",
            "plugin_registry=plugin_registry",
            "def install(",
        ),
        forbidden=(
            "monitorbox.v2.modules.configuration_bootstrap",
            "monitorbox.v2.integrations.",
            "if provider ==",
            "if module_id ==",
            "Scrypted",
            "Portainer",
            "UniFi",
            "SNMP",
            "NUT",
            "FACTORY_",
        ),
    )

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) not in {HISTORICAL_RELEASE, RELEASE}
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
