#!/usr/bin/env python3
"""Extend first-party repository acceptance through Scrypted v1.0.0 build 1."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_unifi as previous

SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"
SCRYPTED_RELEASE = (SCRYPTED_ID, "1.0.0", 1)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {SCRYPTED_RELEASE}
IMPORT_PACKAGE = "monitorbox_scrypted_b1"


def _release(source: dict) -> dict:
    item = next(
        (
            candidate
            for candidate in source.get("modules", [])
            if stable._release_identity(candidate) == SCRYPTED_RELEASE
        ),
        None,
    )
    if item is None:
        raise AssertionError("current Scrypted release is missing from catalog.source.json")
    return item


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    release = _release(source)
    expected_manifest = {
        "module_id": SCRYPTED_ID,
        "display_name": "Scrypted Integration",
        "version": "1.0.0",
        "build": 1,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": f"{IMPORT_PACKAGE}:PLUGIN"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    }
    if release.get("manifest") != expected_manifest:
        raise AssertionError(f"Scrypted manifest changed: {release.get('manifest')!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.scrypted-1.0.0-build1.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("Scrypted package is missing or misnamed")

    expected_files = {
        f"{IMPORT_PACKAGE}/__init__.py",
        f"{IMPORT_PACKAGE}/adoption.py",
        f"{IMPORT_PACKAGE}/onboarding.py",
        f"{IMPORT_PACKAGE}/runtime.py",
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != expected_files:
            raise AssertionError(
                "Scrypted package shape changed: "
                f"missing={sorted(expected_files - names)}, extra={sorted(names - expected_files)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed Scrypted package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, names, f"{IMPORT_PACKAGE}/")
        texts = {name: archive.read(name).decode("utf-8") for name in expected_files}

    root_text = texts[f"{IMPORT_PACKAGE}/__init__.py"]
    onboarding_text = texts[f"{IMPORT_PACKAGE}/onboarding.py"]
    runtime_text = texts[f"{IMPORT_PACKAGE}/runtime.py"]
    required = (
        'metadata=PluginMetadata(plugin_id="scrypted", display_name="Scrypted")',
        'runtime_adapter_kinds=("scrypted",)',
        "candidate_adoption=_SCRYPTED_ADOPTION",
        f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
        'requires_core=">=2.3.0 <3.0.0"',
    )
    missing = [marker for marker in required if marker not in root_text]
    if missing:
        raise AssertionError(f"Scrypted managed package root omitted contract markers: {missing}")

    runtime_required = (
        'MODULE_ID = "com.sickicarus.monitorbox.scrypted"',
        'MODULE_VERSION = "1.0.0"',
        "MODULE_BUILD = 1",
        '"failure_kind": "parent_unavailable"',
        '"monitor_dependency"',
        '"discovery_evidence": _camera_discovery_evidence(cameras)',
    )
    missing_runtime = [marker for marker in runtime_required if marker not in runtime_text]
    if missing_runtime:
        raise AssertionError(f"Scrypted runtime omitted release/runtime markers: {missing_runtime}")

    onboarding_required = (
        'ConnectionPlan(',
        'CredentialSecretWrite(',
        'title="Scrypted cameras"',
        'operation": "inventory"',
        'validation_worker": "isolated"',
    )
    missing_onboarding = [marker for marker in onboarding_required if marker not in onboarding_text]
    if missing_onboarding:
        raise AssertionError(f"Scrypted onboarding omitted connection/validation markers: {missing_onboarding}")

    forbidden = (
        "from ...plugin_api",
        "monitorbox.v2.integrations.scrypted:PLUGIN",
    )
    present = [marker for marker in forbidden if any(marker in text for text in texts.values())]
    if present:
        raise AssertionError(f"Scrypted managed namespace rewrite is incomplete: {present}")

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) != SCRYPTED_RELEASE
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
