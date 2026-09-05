#!/usr/bin/env python3
"""Extend first-party repository acceptance through Wake-on-LAN v1.0.0 build 1."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_scrypted as previous

WOL_ID = "com.sickicarus.monitorbox.wol"
WOL_RELEASE = (WOL_ID, "1.0.0", 1)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {WOL_RELEASE}
IMPORT_PACKAGE = "monitorbox_wol_b1"


def _release(source: dict) -> dict:
    item = next(
        (
            candidate
            for candidate in source.get("modules", [])
            if stable._release_identity(candidate) == WOL_RELEASE
        ),
        None,
    )
    if item is None:
        raise AssertionError("current WOL release is missing from catalog.source.json")
    return item


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    release = _release(source)
    expected_manifest = {
        "module_id": WOL_ID,
        "display_name": "Wake-on-LAN Action",
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
        raise AssertionError(f"WOL manifest changed: {release.get('manifest')!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.wol-1.0.0-build1.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("WOL package is missing or misnamed")

    expected_files = {f"{IMPORT_PACKAGE}/__init__.py"}
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != expected_files:
            raise AssertionError(
                "WOL package shape changed: "
                f"missing={sorted(expected_files - names)}, extra={sorted(names - expected_files)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed WOL package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, names, f"{IMPORT_PACKAGE}/")
        text = archive.read(f"{IMPORT_PACKAGE}/__init__.py").decode("utf-8")

    required = (
        'MODULE_ID = "com.sickicarus.monitorbox.wol"',
        'MODULE_VERSION = "1.0.0"',
        "MODULE_BUILD = 1",
        'metadata=PluginMetadata(plugin_id="wol", display_name="Wake-on-LAN")',
        'action_kinds=("wol",)',
        "validate_action_options=_validate_action_options",
        "resolve_action_command_timeout=_command_timeout_seconds",
        f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
        'requires_core=">=2.3.0 <3.0.0"',
        'packet = bytes.fromhex("ff" * 6 + normalized * 16)',
        "socket.SO_BROADCAST",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise AssertionError(f"WOL managed package omitted contract markers: {missing}")

    forbidden = (
        "from ...plugin_api",
        "monitorbox.v2.integrations.wol:PLUGIN",
    )
    present = [marker for marker in forbidden if marker in text]
    if present:
        raise AssertionError(f"WOL managed namespace rewrite is incomplete: {present}")

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) != WOL_RELEASE
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
