#!/usr/bin/env python3
"""Extend first-party repository acceptance through SNMP v1.0.1 build 2."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_nut as previous

SNMP_ID = "com.sickicarus.monitorbox.snmp"
SNMP_BUILD1 = (SNMP_ID, "1.0.0", 1)
SNMP_RELEASE = (SNMP_ID, "1.0.1", 2)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {SNMP_BUILD1, SNMP_RELEASE}


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


def _expected_manifest(version: str, build: int, entrypoint: str) -> dict:
    return {
        "module_id": SNMP_ID,
        "display_name": "SNMP Integration",
        "version": version,
        "build": build,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": entrypoint},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    }


def _accept_build1(root: Path, source: dict) -> None:
    release = _release(source, SNMP_BUILD1)
    manifest = release["manifest"]
    expected_manifest = _expected_manifest("1.0.0", 1, "monitorbox_snmp_b1:PLUGIN")
    if manifest != expected_manifest:
        raise AssertionError(f"immutable SNMP v1.0.0 build 1 manifest changed: {manifest!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.snmp-1.0.0-build1.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("immutable SNMP v1.0.0 build 1 package is missing or misnamed")

    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        expected_names = {"monitorbox_snmp_b1/__init__.py"}
        if names != expected_names:
            raise AssertionError(
                f"SNMP v1.0.0 build 1 package shape changed: "
                f"missing={sorted(expected_names - names)}, extra={sorted(names - expected_names)}"
            )
        stable._assert_python_syntax(archive, names, "monitorbox_snmp_b1/")
        source_text = archive.read("monitorbox_snmp_b1/__init__.py").decode("utf-8")

    required = (
        'MODULE_VERSION = "1.0.0"',
        "MODULE_BUILD = 1",
        'entrypoints={"integration": "monitorbox_snmp_b1:PLUGIN"}',
    )
    if any(marker not in source_text for marker in required):
        raise AssertionError("immutable SNMP build 1 package identity changed")


def _accept_build2(root: Path, source: dict) -> None:
    release = _release(source, SNMP_RELEASE)
    manifest = release["manifest"]
    expected_manifest = _expected_manifest("1.0.1", 2, "monitorbox_snmp_b2:PLUGIN")
    if manifest != expected_manifest:
        raise AssertionError(f"SNMP v1.0.1 build 2 manifest changed: {manifest!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.snmp-1.0.1-build2.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("SNMP v1.0.1 build 2 generated package is missing or misnamed")

    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        expected_names = {
            "monitorbox_snmp_b2/__init__.py",
            "monitorbox_snmp_b2/runtime.py",
        }
        if names != expected_names:
            raise AssertionError(
                f"SNMP v1.0.1 build 2 package shape changed: "
                f"missing={sorted(expected_names - names)}, extra={sorted(names - expected_names)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed SNMP package may not shadow Core's monitorbox namespace")
        stable._assert_python_syntax(archive, names, "monitorbox_snmp_b2/")
        source_text = archive.read("monitorbox_snmp_b2/__init__.py").decode("utf-8")
        runtime_text = archive.read("monitorbox_snmp_b2/runtime.py").decode("utf-8")

    required_root = (
        'MODULE_ID = "com.sickicarus.monitorbox.snmp"',
        'MODULE_VERSION = "1.0.1"',
        "MODULE_BUILD = 2",
        "from monitorbox.v2.adapters import AdapterRunner",
        "from monitorbox.v2.config import CheckConfig",
        "from monitorbox.v2.model import State",
        "from monitorbox.v2.plugin_api import (",
        "from .runtime import SnmpRuntimeExecutor",
        "runtime_executor=_SNMP_RUNTIME",
        'runtime_adapter_kinds=("snmp",)',
        'entrypoints={"integration": "monitorbox_snmp_b2:PLUGIN"}',
        'requires_core=">=2.3.0 <3.0.0"',
        'requires_runtime_api=">=1 <2"',
    )
    missing = [marker for marker in required_root if marker not in source_text]
    if missing:
        raise AssertionError(f"SNMP build 2 package root omitted contract markers: {missing}")

    required_runtime = (
        "class SnmpRuntimeExecutor:",
        "RuntimeExecutionRequest",
        "RuntimeExecutionResult",
        'state="unknown"',
        '"failure_kind": "monitor_dependency"',
        'args += ["-v1", "-c", community]',
        'args += ["-v2c", "-c", community]',
        "asyncio.wait_for(",
    )
    missing_runtime = [marker for marker in required_runtime if marker not in runtime_text]
    if missing_runtime:
        raise AssertionError(f"SNMP build 2 runtime omitted truth/bound markers: {missing_runtime}")

    forbidden = (
        "from ...adapters",
        "from ...config",
        "from ...model",
        "from ...plugin_api",
        "monitorbox.v2.integrations.snmp:PLUGIN",
    )
    present = [
        marker
        for marker in forbidden
        if marker in source_text or marker in runtime_text
    ]
    if present:
        raise AssertionError(f"SNMP managed namespace rewrite is incomplete: {present}")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _accept_build1(root, source)
    _accept_build2(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) not in {SNMP_BUILD1, SNMP_RELEASE}
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
