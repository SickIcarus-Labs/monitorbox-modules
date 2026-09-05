#!/usr/bin/env python3
"""Extend first-party repository acceptance through Configuration/Bootstrap 1.0.0 build 1."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_wol as previous

MODULE_ID = "com.sickicarus.monitorbox.configuration-bootstrap"
RELEASE = (MODULE_ID, "1.0.0", 1)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {RELEASE}
IMPORT_MODULE = "monitorbox_configuration_bootstrap_b1"
SOURCE_NAME = f"{IMPORT_MODULE}.py"


def _release(source: dict) -> dict:
    item = next(
        (
            candidate
            for candidate in source.get("modules", [])
            if stable._release_identity(candidate) == RELEASE
        ),
        None,
    )
    if item is None:
        raise AssertionError(
            "current Configuration/Bootstrap release is missing from catalog.source.json"
        )
    return item


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    release = _release(source)
    expected_manifest = {
        "module_id": MODULE_ID,
        "display_name": "Configuration / Bootstrap",
        "version": "1.0.0",
        "build": 1,
        "schema": 1,
        "state_schema": 1,
        "module_type": "configuration",
        "entrypoints": {"configuration": f"{IMPORT_MODULE}:install"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    }
    if release.get("manifest") != expected_manifest:
        raise AssertionError(
            f"Configuration/Bootstrap manifest changed: {release.get('manifest')!r}"
        )

    package_path = root / "packages" / release["package"]
    expected_filename = (
        "com.sickicarus.monitorbox.configuration-bootstrap-1.0.0-build1.zip"
    )
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("Configuration/Bootstrap package is missing or misnamed")

    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != {SOURCE_NAME}:
            raise AssertionError(
                "Configuration/Bootstrap package shape changed: "
                f"expected={[SOURCE_NAME]}, actual={sorted(names)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError(
                "managed Configuration/Bootstrap package may not shadow Core's monitorbox namespace"
            )
        compile(archive.read(SOURCE_NAME), SOURCE_NAME, "exec")
        text = archive.read(SOURCE_NAME).decode("utf-8")

    required = (
        "def install(",
        "SetupDraftUi(platform).install(app)",
        "SetupAwareConfigUi(platform, controller).install(app)",
        "SetupAwareApplianceCredentialsUi(platform).install(app)",
        "AbilityDiscoveryUi(platform, controller).install(app)",
        "GuidedSetupUi(platform).install(app)",
        "PolicyUi(platform).install(app)",
        "ui.onboarding.connections.summary_projector = ui.onboarding._summary",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise AssertionError(
            f"Configuration/Bootstrap managed package omitted contract markers: {missing}"
        )

    forbidden = (
        "monitorbox.v2.integrations.",
        "if provider ==",
        "if module_id ==",
        "Scrypted",
        "Portainer",
        "UniFi",
        "SNMP",
        "NUT",
    )
    present = [marker for marker in forbidden if marker in text]
    if present:
        raise AssertionError(
            "Configuration/Bootstrap package contains provider-specific policy: "
            f"{present}"
        )

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) != RELEASE
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
