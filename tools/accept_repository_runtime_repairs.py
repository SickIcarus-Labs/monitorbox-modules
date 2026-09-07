#!/usr/bin/env python3
"""Extend signed repository acceptance through current SNMP/Scrypted repairs."""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_provider_repairs as previous

SNMP_ID = "com.sickicarus.monitorbox.snmp"
SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"
SNMP_BUILD6 = (SNMP_ID, "1.0.4", 6)
SNMP_BUILD7 = (SNMP_ID, "1.0.5", 7)
SCRYPTED_BUILD3 = (SCRYPTED_ID, "2.1.2", 3)
OPTIONAL_CURRENT = {SNMP_BUILD6, SNMP_BUILD7, SCRYPTED_BUILD3}


def _release(source: dict, identity: tuple[str, str, int]) -> dict:
    for item in source.get("modules", []):
        if stable._release_identity(item) == identity:
            return item
    raise AssertionError(f"runtime-repair release {identity} is missing")


def _manifest(module_id: str, display: str, version: str, build: int, entrypoint: str) -> dict:
    return {
        "module_id": module_id,
        "display_name": display,
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


def _accept_snmp6(root: Path, source: dict) -> None:
    release = _release(source, SNMP_BUILD6)
    expected = _manifest(SNMP_ID, "SNMP Integration", "1.0.4", 6, "monitorbox_snmp_b6:PLUGIN")
    if release.get("manifest") != expected:
        raise AssertionError("SNMP build 6 manifest changed")
    package = root / "packages" / release["package"]
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required = {"monitorbox_snmp_b6/runtime.py", "pysnmp/smi/builder.py"}
        if required - names:
            raise AssertionError(f"SNMP build 6 omitted assets: {sorted(required-names)}")
        text = archive.read("pysnmp/smi/builder.py").decode()
    if "_get_files" not in text or "isinstance(mibSource, DirMibSource)" not in text:
        raise AssertionError("SNMP build 6 lost Python-3.13 ZIP/MIB repair")


def _accept_snmp7(root: Path, source: dict) -> None:
    release = _release(source, SNMP_BUILD7)
    expected = _manifest(SNMP_ID, "SNMP Integration", "1.0.5", 7, "monitorbox_snmp_v105_b7:PLUGIN")
    if release.get("manifest") != expected:
        raise AssertionError("SNMP build 7 manifest changed")
    package = root / "packages" / release["package"]
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required = {
            "monitorbox_snmp_v105_b7/runtime.py",
            "monitorbox_snmp_v105_b7/v3_isolation.py",
            "pysnmp/smi/builder.py",
        }
        if required - names:
            raise AssertionError(f"SNMP build 7 omitted assets: {sorted(required-names)}")
        runtime = archive.read("monitorbox_snmp_v105_b7/runtime.py").decode()
        policy = archive.read("monitorbox_snmp_v105_b7/v3_isolation.py").decode()
        builder = archive.read("pysnmp/smi/builder.py").decode()
    required_markers = (
        "with_fresh_engine(hlapi, operation)",
        "is_auth_observer_loss(detail)",
        "wrong snmp pdu digest",
    )
    blob = runtime + policy
    missing = [marker for marker in required_markers if marker not in blob]
    if missing:
        raise AssertionError(f"SNMP build 7 omitted isolation markers: {missing}")
    if "_get_files" not in builder:
        raise AssertionError("SNMP build 7 lost build-6 ZIP/MIB compatibility")


def _accept_scrypted3(root: Path, source: dict) -> None:
    release = _release(source, SCRYPTED_BUILD3)
    expected = _manifest(
        SCRYPTED_ID,
        "Scrypted Integration",
        "2.1.2",
        3,
        "monitorbox_scrypted_v212_b3:PLUGIN",
    )
    if release.get("manifest") != expected:
        raise AssertionError("Scrypted build 3 manifest changed")
    package = root / "packages" / release["package"]
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        required = {
            "monitorbox_scrypted_v212_b3/runtime.py",
            "monitorbox_scrypted_v212_b3/state_socket.py",
            "monitorbox_scrypted_v212_b3/onboarding.py",
        }
        if required - names:
            raise AssertionError(f"Scrypted build 3 omitted assets: {sorted(required-names)}")
        runtime = archive.read("monitorbox_scrypted_v212_b3/runtime.py").decode()
        onboarding = archive.read("monitorbox_scrypted_v212_b3/onboarding.py").decode()
    if "await self._bridge.start(context.state_root)" not in runtime:
        raise AssertionError("Scrypted build 3 stopped consuming Core state_root")
    if "/run/monitorbox-scrypted" in onboarding:
        raise AssertionError("Scrypted build 3 onboarding resurrected unmanaged /run state")


def _current_releases(source: dict) -> set[tuple[str, str, int]]:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    current = set(previous._current_releases(source))
    current.update(identity for identity in OPTIONAL_CURRENT if identity in identities)
    return current


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    expected = _current_releases(source)
    if identities != expected or len(source.get("modules", [])) != len(expected):
        raise AssertionError(f"expected runtime-repair catalog {sorted(expected)}, got {sorted(identities)}")

    if SNMP_BUILD6 in identities:
        _accept_snmp6(root, source)
    if SNMP_BUILD7 in identities:
        _accept_snmp7(root, source)
    if SCRYPTED_BUILD3 in identities:
        _accept_scrypted3(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item for item in prior.get("modules", [])
        if stable._release_identity(item) not in OPTIONAL_CURRENT
    ]
    previous._package_shape(root, prior)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    source = json.loads((root / "catalog.source.json").read_text(encoding="utf-8"))
    stable.EXPECTED_RELEASES = _current_releases(source)
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
