#!/usr/bin/env python3
"""Extend first-party repository acceptance through NUT v1.0.0 build 1."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_http as previous

NUT_ID = "com.sickicarus.monitorbox.nut"
NUT_RELEASE = (NUT_ID, "1.0.0", 1)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {NUT_RELEASE}


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
        raise AssertionError(f"current release {identity} is missing from catalog.source.json")
    return item


def _accept_nut(root: Path, source: dict) -> None:
    release = _release(source, NUT_RELEASE)
    manifest = release["manifest"]
    expected_manifest = {
        "module_id": NUT_ID,
        "display_name": "NUT UPS Integration",
        "version": "1.0.0",
        "build": 1,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": "monitorbox_nut_b1:PLUGIN"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    }
    if manifest != expected_manifest:
        raise AssertionError(f"NUT v1.0.0 build 1 manifest changed: {manifest!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.nut-1.0.0-build1.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("NUT v1.0.0 build 1 generated package is missing or misnamed")

    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        expected_names = {"monitorbox_nut_b1/__init__.py"}
        if names != expected_names:
            raise AssertionError(
                f"NUT v1.0.0 build 1 package shape changed: "
                f"missing={sorted(expected_names - names)}, extra={sorted(names - expected_names)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed NUT package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, names, "monitorbox_nut_b1/")
        source_text = archive.read("monitorbox_nut_b1/__init__.py").decode("utf-8")

    required = (
        'MODULE_ID = "com.sickicarus.monitorbox.nut"',
        'MODULE_VERSION = "1.0.0"',
        "MODULE_BUILD = 1",
        "from monitorbox.v2.adapters import AdapterRunner",
        "from monitorbox.v2.config import CheckConfig",
        "from monitorbox.v2.model import State",
        "from monitorbox.v2.plugin_api import (",
        'entrypoints={"integration": "monitorbox_nut_b1:PLUGIN"}',
        'requires_core=">=2.3.0 <3.0.0"',
        'requires_runtime_api=">=1 <2"',
    )
    missing = [marker for marker in required if marker not in source_text]
    if missing:
        raise AssertionError(f"NUT managed package root omitted contract markers: {missing}")

    forbidden = (
        "from ...adapters",
        "from ...config",
        "from ...model",
        "from ...plugin_api",
        "monitorbox.v2.integrations.nut:PLUGIN",
    )
    present = [marker for marker in forbidden if marker in source_text]
    if present:
        raise AssertionError(f"NUT managed namespace rewrite is incomplete: {present}")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _accept_nut(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) != NUT_RELEASE
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
