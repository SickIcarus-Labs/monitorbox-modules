#!/usr/bin/env python3
"""Extend first-party repository acceptance through UniFi Network v1.0.0 build 1."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_snmp as previous

UNIFI_ID = "com.sickicarus.monitorbox.unifi"
UNIFI_RELEASE = (UNIFI_ID, "1.0.0", 1)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {UNIFI_RELEASE}
IMPORT_PACKAGE = "monitorbox_unifi_b1"


def _release(source: dict) -> dict:
    item = next(
        (
            candidate
            for candidate in source.get("modules", [])
            if stable._release_identity(candidate) == UNIFI_RELEASE
        ),
        None,
    )
    if item is None:
        raise AssertionError("current UniFi Network release is missing from catalog.source.json")
    return item


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    release = _release(source)
    expected_manifest = {
        "module_id": UNIFI_ID,
        "display_name": "UniFi Network Integration",
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
        raise AssertionError(f"UniFi Network manifest changed: {release.get('manifest')!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.unifi-1.0.0-build1.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("UniFi Network package is missing or misnamed")

    expected_files = {
        f"{IMPORT_PACKAGE}/__init__.py",
        f"{IMPORT_PACKAGE}/adoption.py",
        f"{IMPORT_PACKAGE}/discovery.py",
        f"{IMPORT_PACKAGE}/discovery_runtime.py",
        f"{IMPORT_PACKAGE}/onboarding.py",
        f"{IMPORT_PACKAGE}/runtime.py",
        f"{IMPORT_PACKAGE}/vertical_runtime.py",
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != expected_files:
            raise AssertionError(
                "UniFi Network package shape changed: "
                f"missing={sorted(expected_files - names)}, extra={sorted(names - expected_files)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed UniFi package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, names, f"{IMPORT_PACKAGE}/")
        texts = {
            name: archive.read(name).decode("utf-8")
            for name in expected_files
        }

    root_text = texts[f"{IMPORT_PACKAGE}/__init__.py"]
    runtime_text = texts[f"{IMPORT_PACKAGE}/runtime.py"]
    vertical_text = texts[f"{IMPORT_PACKAGE}/vertical_runtime.py"]
    required = (
        'metadata=PluginMetadata(plugin_id="unifi", display_name="UniFi Network")',
        'runtime_adapter_kinds=("unifi",)',
        "candidate_adoption=_UNIFI_ADOPTION",
        f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
        'requires_core=">=2.3.0 <3.0.0"',
    )
    missing = [marker for marker in required if marker not in root_text]
    if missing:
        raise AssertionError(f"UniFi managed package root omitted contract markers: {missing}")

    runtime_required = (
        'MODULE_ID = "com.sickicarus.monitorbox.unifi"',
        'MODULE_VERSION = "1.0.0"',
        "MODULE_BUILD = 1",
        '_STATE_FILE = "link-expectations.json"',
        '"failure_kind": "unsupported_runtime_operation"',
        f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
    )
    missing_runtime = [marker for marker in runtime_required if marker not in runtime_text]
    if missing_runtime:
        raise AssertionError(f"UniFi runtime omitted release/state markers: {missing_runtime}")

    vertical_required = (
        "_PERSISTENCE_VERSION = 2",
        'Path(context.state_root) / "link-expectations.json"',
        '"failure_kind": "monitor_dependency"',
        '"authoritative": False',
        'State.FAILED, "Switch port is enabled but has no link"',
    )
    missing_vertical = [marker for marker in vertical_required if marker not in vertical_text]
    if missing_vertical:
        raise AssertionError(f"UniFi vertical runtime omitted state/truth markers: {missing_vertical}")

    forbidden = (
        "from ...discovery",
        "from ...model",
        "from ...plugin_api",
        "monitorbox.v2.integrations.unifi:PLUGIN",
    )
    present = [
        marker
        for marker in forbidden
        if any(marker in text for text in texts.values())
    ]
    if present:
        raise AssertionError(f"UniFi managed namespace rewrite is incomplete: {present}")

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) != UNIFI_RELEASE
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
