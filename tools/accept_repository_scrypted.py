#!/usr/bin/env python3
"""Extend first-party repository acceptance through Scrypted v2.0.0 build 1."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_unifi as previous

SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"
SCRYPTED_V1 = (SCRYPTED_ID, "1.0.0", 1)
SCRYPTED_V2 = (SCRYPTED_ID, "2.0.0", 1)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {SCRYPTED_V1, SCRYPTED_V2}
IMPORT_V1 = "monitorbox_scrypted_b1"
IMPORT_V2 = "monitorbox_scrypted_v2_b1"


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
        raise AssertionError(f"Scrypted release {identity[1]} build {identity[2]} is missing")
    return item


def _manifest(import_package: str, version: str) -> dict:
    return {
        "module_id": SCRYPTED_ID,
        "display_name": "Scrypted Integration",
        "version": version,
        "build": 1,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": f"{import_package}:PLUGIN"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    }


def _validate_v1(root: Path, source: dict) -> None:
    release = _release(source, SCRYPTED_V1)
    if release.get("manifest") != _manifest(IMPORT_V1, "1.0.0"):
        raise AssertionError(f"Scrypted 1.0.0 manifest changed: {release.get('manifest')!r}")
    package_path = root / "packages" / release["package"]
    if package_path.name != "com.sickicarus.monitorbox.scrypted-1.0.0-build1.zip":
        raise AssertionError("Scrypted 1.0.0 package is misnamed")
    expected_files = {
        f"{IMPORT_V1}/__init__.py",
        f"{IMPORT_V1}/adoption.py",
        f"{IMPORT_V1}/onboarding.py",
        f"{IMPORT_V1}/runtime.py",
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != expected_files:
            raise AssertionError(
                "Scrypted 1.0.0 package shape changed: "
                f"missing={sorted(expected_files - names)}, extra={sorted(names - expected_files)}"
            )
        stable._assert_python_syntax(archive, names, f"{IMPORT_V1}/")


def _validate_v2(root: Path, source: dict) -> None:
    release = _release(source, SCRYPTED_V2)
    if release.get("manifest") != _manifest(IMPORT_V2, "2.0.0"):
        raise AssertionError(f"Scrypted 2.0.0 manifest changed: {release.get('manifest')!r}")
    package_path = root / "packages" / release["package"]
    if package_path.name != "com.sickicarus.monitorbox.scrypted-2.0.0-build1.zip":
        raise AssertionError("Scrypted 2.0.0 package is misnamed")
    python_files = {
        f"{IMPORT_V2}/__init__.py",
        f"{IMPORT_V2}/adoption.py",
        f"{IMPORT_V2}/onboarding.py",
        f"{IMPORT_V2}/runtime.py",
    }
    required_worker_files = {
        f"{IMPORT_V2}/bridge/server.mjs",
        f"{IMPORT_V2}/bridge/package.json",
        f"{IMPORT_V2}/bridge/package-lock.json",
        f"{IMPORT_V2}/bridge/node_modules/@scrypted/client/package.json",
        f"{IMPORT_V2}/bridge/node_modules/@scrypted/types/package.json",
        f"{IMPORT_V2}/bridge/node_modules/ws/package.json",
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        missing = (python_files | required_worker_files) - names
        if missing:
            raise AssertionError(f"Scrypted 2.0.0 package omitted worker assets: {sorted(missing)}")
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed Scrypted package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, python_files, f"{IMPORT_V2}/")
        texts = {name: archive.read(name).decode("utf-8") for name in python_files}

    root_text = texts[f"{IMPORT_V2}/__init__.py"]
    onboarding_text = texts[f"{IMPORT_V2}/onboarding.py"]
    runtime_text = texts[f"{IMPORT_V2}/runtime.py"]
    required_root = (
        'metadata=PluginMetadata(plugin_id="scrypted", display_name="Scrypted")',
        'runtime_adapter_kinds=("scrypted",)',
        "candidate_adoption=_SCRYPTED_ADOPTION",
        f'entrypoints={{"integration": "{IMPORT_V2}:PLUGIN"}}',
        'requires_core=">=2.3.0 <3.0.0"',
    )
    missing_root = [marker for marker in required_root if marker not in root_text]
    if missing_root:
        raise AssertionError(f"Scrypted 2.0.0 package root omitted markers: {missing_root}")

    runtime_required = (
        'MODULE_VERSION = "2.0.0"',
        "class _BridgeWorker:",
        "resources.files(__package__).joinpath(\"bridge\")",
        'os.environ.get("MONITORBOX_MODULE_NODE", "node")',
        '"SCRYPTED_USERNAME": config.username',
        '"failure_kind": "parent_unavailable"',
        '"monitor_dependency"',
        '"discovery_evidence": _camera_discovery_evidence(cameras)',
    )
    missing_runtime = [marker for marker in runtime_required if marker not in runtime_text]
    if missing_runtime:
        raise AssertionError(f"Scrypted 2.0.0 runtime omitted worker markers: {missing_runtime}")

    onboarding_required = (
        "ConnectionPlan(",
        "CredentialSecretWrite(",
        'title="Scrypted cameras"',
        '"operation": "inventory"',
        '"validation_worker": "module_owned"',
    )
    missing_onboarding = [marker for marker in onboarding_required if marker not in onboarding_text]
    if missing_onboarding:
        raise AssertionError(
            f"Scrypted 2.0.0 onboarding omitted module-owned validation markers: {missing_onboarding}"
        )

    forbidden = (
        "from ...plugin_api",
        "monitorbox.v2.integrations.scrypted:PLUGIN",
        "/app/bridge/server.mjs",
    )
    present = [marker for marker in forbidden if any(marker in text for text in texts.values())]
    if present:
        raise AssertionError(f"Scrypted 2.0.0 managed boundary is incomplete: {present}")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _validate_v1(root, source)
    _validate_v2(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) not in {SCRYPTED_V1, SCRYPTED_V2}
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
