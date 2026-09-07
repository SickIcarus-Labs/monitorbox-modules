#!/usr/bin/env python3
"""Extend signed repository acceptance through the pruned-Core provider repairs."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_ui_build11 as previous

NUT_ID = "com.sickicarus.monitorbox.nut"
SNMP_ID = "com.sickicarus.monitorbox.snmp"
SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"

NUT_RELEASE = (NUT_ID, "1.0.1", 2)
SNMP_RELEASE = (SNMP_ID, "1.0.3", 4)
SCRYPTED_RELEASE = (SCRYPTED_ID, "2.1.1", 2)
NEW_RELEASES = {NUT_RELEASE, SNMP_RELEASE, SCRYPTED_RELEASE}
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | NEW_RELEASES


def _release(source: dict, identity: tuple[str, str, int]) -> dict:
    for item in source.get("modules", []):
        if stable._release_identity(item) == identity:
            return item
    raise AssertionError(f"provider repair release {identity} is missing from catalog.source.json")


def _expected_manifest(
    module_id: str,
    display_name: str,
    version: str,
    build: int,
    entrypoint: str,
) -> dict:
    return {
        "module_id": module_id,
        "display_name": display_name,
        "version": version,
        "build": build,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": entrypoint},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    }


def _accept_nut(root: Path, source: dict) -> None:
    release = _release(source, NUT_RELEASE)
    expected_manifest = _expected_manifest(
        NUT_ID,
        "NUT UPS Integration",
        "1.0.1",
        2,
        "monitorbox_nut_b2:PLUGIN",
    )
    if release.get("manifest") != expected_manifest:
        raise AssertionError(f"NUT 1.0.1 build 2 manifest mismatch: {release.get('manifest')!r}")

    package = root / "packages" / release["package"]
    if package.name != "com.sickicarus.monitorbox.nut-1.0.1-build2.zip" or not package.is_file():
        raise AssertionError("NUT 1.0.1 build 2 package is missing or misnamed")
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        expected_names = {
            "monitorbox_nut_b2/__init__.py",
            "monitorbox_nut_b2/runtime.py",
        }
        if names != expected_names:
            raise AssertionError(
                "NUT 1.0.1 build 2 package shape changed: "
                f"missing={sorted(expected_names - names)}, extra={sorted(names - expected_names)}"
            )
        stable._assert_python_syntax(archive, names, "monitorbox_nut_b2/")
        root_text = archive.read("monitorbox_nut_b2/__init__.py").decode("utf-8")
        runtime_text = archive.read("monitorbox_nut_b2/runtime.py").decode("utf-8")
    required = (
        'MODULE_VERSION = "1.0.1"',
        "MODULE_BUILD = 2",
        "NutRuntimeExecutor",
        'runtime_adapter_kinds=("nut",)',
        'entrypoints={"integration": "monitorbox_nut_b2:PLUGIN"}',
        'requires_core=">=2.3.1 <3.0.0"',
        "class NutRuntimeExecutor:",
        '"failure_kind": "monitor_dependency"',
    )
    missing = [marker for marker in required if marker not in root_text + runtime_text]
    if missing:
        raise AssertionError(f"NUT 1.0.1 build 2 omitted runtime ownership markers: {missing}")


def _accept_snmp(root: Path, source: dict) -> None:
    release = _release(source, SNMP_RELEASE)
    expected_manifest = _expected_manifest(
        SNMP_ID,
        "SNMP Integration",
        "1.0.3",
        4,
        "monitorbox_snmp_b4:PLUGIN",
    )
    if release.get("manifest") != expected_manifest:
        raise AssertionError(f"SNMP 1.0.3 build 4 manifest mismatch: {release.get('manifest')!r}")

    package = root / "packages" / release["package"]
    if package.name != "com.sickicarus.monitorbox.snmp-1.0.3-build4.zip" or not package.is_file():
        raise AssertionError("SNMP 1.0.3 build 4 package is missing or misnamed")
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required_files = {
            "monitorbox_snmp_b4/__init__.py",
            "monitorbox_snmp_b4/runtime.py",
            "pysnmp/hlapi/v3arch/asyncio/__init__.py",
            "pyasn1/__init__.py",
        }
        missing_files = sorted(required_files - names)
        if missing_files:
            raise AssertionError(f"SNMP 1.0.3 build 4 omitted managed/vendor files: {missing_files}")
        # PySNMP 7 uses implicit namespace packages. Their directory entries are
        # semantically required by zipimport even though no __init__.py exists.
        required_namespaces = {
            "pysnmp/hlapi/",
            "pysnmp/hlapi/v3arch/",
            "pysnmp/hlapi/v3arch/asyncio/",
        }
        missing_namespaces = sorted(required_namespaces - names)
        if missing_namespaces:
            raise AssertionError(
                f"SNMP 1.0.3 build 4 lost zipimport namespace topology: {missing_namespaces}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("SNMP build 4 may not shadow Core's monitorbox namespace")
        module_python = {
            name for name in names
            if name.startswith("monitorbox_snmp_b4/") and name.endswith(".py")
        }
        stable._assert_python_syntax(archive, module_python, "monitorbox_snmp_b4/")
        root_text = archive.read("monitorbox_snmp_b4/__init__.py").decode("utf-8")
        runtime_text = archive.read("monitorbox_snmp_b4/runtime.py").decode("utf-8")
    required = (
        'MODULE_VERSION = "1.0.3"',
        "MODULE_BUILD = 4",
        "SnmpRuntimeExecutor",
        'runtime_adapter_kinds=("snmp",)',
        'entrypoints={"integration": "monitorbox_snmp_b4:PLUGIN"}',
        'requires_core=">=2.3.1 <3.0.0"',
        "from pysnmp.hlapi.v3arch import asyncio as hlapi",
        '"transport": "pysnmp"',
        'metadata["failure_kind"] = "provider_semantics_unknown"',
        'summary="QNAP storage maintenance: Scrubbing"',
    )
    missing = [marker for marker in required if marker not in root_text + runtime_text]
    if missing:
        raise AssertionError(f"SNMP 1.0.3 build 4 omitted self-contained runtime markers: {missing}")
    for forbidden in ("snmpget", "create_subprocess_exec", "monitorbox.v2.integrations.snmp"):
        if forbidden in root_text + runtime_text:
            raise AssertionError(f"SNMP 1.0.3 build 4 retained hidden dependency: {forbidden}")


def _accept_scrypted(root: Path, source: dict) -> None:
    release = _release(source, SCRYPTED_RELEASE)
    expected_manifest = _expected_manifest(
        SCRYPTED_ID,
        "Scrypted Integration",
        "2.1.1",
        2,
        "monitorbox_scrypted_v211_b2:PLUGIN",
    )
    if release.get("manifest") != expected_manifest:
        raise AssertionError(f"Scrypted 2.1.1 build 2 manifest mismatch: {release.get('manifest')!r}")

    package = root / "packages" / release["package"]
    if package.name != "com.sickicarus.monitorbox.scrypted-2.1.1-build2.zip" or not package.is_file():
        raise AssertionError("Scrypted 2.1.1 build 2 package is missing or misnamed")
    import_root = "monitorbox_scrypted_v211_b2"
    required_files = {
        f"{import_root}/__init__.py",
        f"{import_root}/runtime.py",
        f"{import_root}/legacy_control.py",
        f"{import_root}/media.py",
        f"{import_root}/bridge/server.mjs",
        f"{import_root}/bridge/node_modules/@scrypted/client/package.json",
        f"{import_root}/bridge/node_modules/ws/package.json",
    }
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        missing_files = sorted(required_files - names)
        if missing_files:
            raise AssertionError(f"Scrypted 2.1.1 build 2 omitted assets: {missing_files}")
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("Scrypted build 2 may not shadow Core's monitorbox namespace")
        python_names = {
            name for name in names
            if name.startswith(f"{import_root}/") and name.endswith(".py")
        }
        stable._assert_python_syntax(archive, python_names, f"{import_root}/")
        root_text = archive.read(f"{import_root}/__init__.py").decode("utf-8")
        runtime_text = archive.read(f"{import_root}/runtime.py").decode("utf-8")
        legacy_text = archive.read(f"{import_root}/legacy_control.py").decode("utf-8")
    required = (
        'entrypoints={"integration": "monitorbox_scrypted_v211_b2:PLUGIN"}',
        'requires_core=">=2.3.1 <3.0.0"',
        "media_executor=_SCRYPTED_MEDIA",
        'MODULE_VERSION = "2.1.1"',
        "MODULE_BUILD = 2",
        "resolve_legacy_worker_config",
        "MONITORBOX_CONFIG_ROOT",
        "credential_secret_refs",
    )
    missing = [marker for marker in required if marker not in root_text + runtime_text + legacy_text]
    if missing:
        raise AssertionError(f"Scrypted 2.1.1 build 2 omitted migration/runtime markers: {missing}")
    for forbidden in (
        "monitorbox.v2.scrypted_worker",
        "monitorbox.v2.scrypted_sidecar_runtime",
        "monitorbox.v2.integrations.scrypted:PLUGIN",
    ):
        if forbidden in root_text + runtime_text + legacy_text:
            raise AssertionError(f"Scrypted 2.1.1 build 2 retained retired Core authority: {forbidden}")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected provider-repair catalog {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _accept_nut(root, source)
    _accept_snmp(root, source)
    _accept_scrypted(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) not in NEW_RELEASES
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
