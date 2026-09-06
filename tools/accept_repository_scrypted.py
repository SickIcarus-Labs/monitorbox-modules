#!/usr/bin/env python3
"""Extend first-party repository acceptance through Scrypted v2.1.0 build 1."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_unifi as previous

SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"
SCRYPTED_V1 = (SCRYPTED_ID, "1.0.0", 1)
SCRYPTED_V2 = (SCRYPTED_ID, "2.0.0", 1)
SCRYPTED_V21 = (SCRYPTED_ID, "2.1.0", 1)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {SCRYPTED_V1, SCRYPTED_V2, SCRYPTED_V21}
IMPORT_V1 = "monitorbox_scrypted_b1"
IMPORT_V2 = "monitorbox_scrypted_v2_b1"
IMPORT_V21 = "monitorbox_scrypted_v21_b1"


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


def _manifest(import_package: str, version: str, *, requires_core: str = ">=2.3.0 <3.0.0") -> dict:
    return {
        "module_id": SCRYPTED_ID,
        "display_name": "Scrypted Integration",
        "version": version,
        "build": 1,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": f"{import_package}:PLUGIN"},
        "requires_core": requires_core,
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
    expected_files = {
        f"{IMPORT_V1}/__init__.py",
        f"{IMPORT_V1}/adoption.py",
        f"{IMPORT_V1}/onboarding.py",
        f"{IMPORT_V1}/runtime.py",
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != expected_files:
            raise AssertionError("Scrypted 1.0.0 package shape changed")
        stable._assert_python_syntax(archive, names, f"{IMPORT_V1}/")


def _validate_worker_release(
    root: Path,
    source: dict,
    identity: tuple[str, str, int],
    import_package: str,
    *,
    media: bool,
) -> None:
    version = identity[1]
    requires_core = ">=2.3.1 <3.0.0" if media else ">=2.3.0 <3.0.0"
    release = _release(source, identity)
    expected_manifest = _manifest(import_package, version, requires_core=requires_core)
    if release.get("manifest") != expected_manifest:
        raise AssertionError(f"Scrypted {version} manifest changed: {release.get('manifest')!r}")
    package_path = root / "packages" / release["package"]
    python_files = {
        f"{import_package}/__init__.py",
        f"{import_package}/adoption.py",
        f"{import_package}/onboarding.py",
        f"{import_package}/runtime.py",
    }
    if media:
        python_files.add(f"{import_package}/media.py")
    required_worker_files = {
        f"{import_package}/bridge/server.mjs",
        f"{import_package}/bridge/package.json",
        f"{import_package}/bridge/package-lock.json",
        f"{import_package}/bridge/node_modules/@scrypted/client/package.json",
        f"{import_package}/bridge/node_modules/@scrypted/types/package.json",
        f"{import_package}/bridge/node_modules/ws/package.json",
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        missing = (python_files | required_worker_files) - names
        if missing:
            raise AssertionError(f"Scrypted {version} package omitted assets: {sorted(missing)}")
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed Scrypted package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, python_files, f"{import_package}/")
        texts = {name: archive.read(name).decode("utf-8") for name in python_files}

    root_text = texts[f"{import_package}/__init__.py"]
    runtime_text = texts[f"{import_package}/runtime.py"]
    required_root = [
        'metadata=PluginMetadata(plugin_id="scrypted", display_name="Scrypted")',
        'runtime_adapter_kinds=("scrypted",)',
        f'entrypoints={{"integration": "{import_package}:PLUGIN"}}',
        f'requires_core="{requires_core}"',
    ]
    if media:
        required_root.extend(["ScryptedMediaExecutor", "media_executor=_SCRYPTED_MEDIA"])
    missing_root = [marker for marker in required_root if marker not in root_text]
    if missing_root:
        raise AssertionError(f"Scrypted {version} root omitted markers: {missing_root}")

    runtime_required = (
        f'MODULE_VERSION = "{version}"',
        "class _BridgeWorker:",
        "resources.files(__package__).joinpath(\"bridge\")",
        'os.environ.get("MONITORBOX_MODULE_NODE", "node")',
        '"SCRYPTED_USERNAME": config.username',
        '"failure_kind": "parent_unavailable"',
        '"monitor_dependency"',
    )
    missing_runtime = [marker for marker in runtime_required if marker not in runtime_text]
    if missing_runtime:
        raise AssertionError(f"Scrypted {version} runtime omitted markers: {missing_runtime}")

    if media:
        media_text = texts[f"{import_package}/media.py"]
        media_required = (
            "class ScryptedMediaExecutor:",
            "MediaExecutionRequest",
            "MediaSnapshotResult",
            'operation == "snapshot"',
            'operation == "live"',
            "/snapshot",
            "/live",
        )
        missing_media = [marker for marker in media_required if marker not in media_text]
        if missing_media:
            raise AssertionError(f"Scrypted {version} media facet omitted markers: {missing_media}")

    forbidden = (
        "from ...plugin_api",
        "monitorbox.v2.integrations.scrypted:PLUGIN",
        "/app/bridge/server.mjs",
    )
    present = [marker for marker in forbidden if any(marker in text for text in texts.values())]
    if present:
        raise AssertionError(f"Scrypted {version} managed boundary is incomplete: {present}")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected Scrypted catalog prefix {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )
    _validate_v1(root, source)
    _validate_worker_release(root, source, SCRYPTED_V2, IMPORT_V2, media=False)
    _validate_worker_release(root, source, SCRYPTED_V21, IMPORT_V21, media=True)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) not in {SCRYPTED_V1, SCRYPTED_V2, SCRYPTED_V21}
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
