#!/usr/bin/env python3
"""Extend signed repository acceptance through current runtime repairs and UI build 12."""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_provider_repairs as previous
import accept_repository_ui_build11 as ui11

SNMP_ID = "com.sickicarus.monitorbox.snmp"
SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"
UI_ID = stable.UI_ID
SNMP_BUILD6 = (SNMP_ID, "1.0.4", 6)
SNMP_BUILD7 = (SNMP_ID, "1.0.5", 7)
SCRYPTED_BUILD3 = (SCRYPTED_ID, "2.1.2", 3)
UI_BUILD12 = (UI_ID, "1.1.4", 12)
OPTIONAL_CURRENT = {SNMP_BUILD6, SNMP_BUILD7, SCRYPTED_BUILD3, UI_BUILD12}


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


def _accept_ui12(root: Path, source: dict) -> None:
    release = _release(source, UI_BUILD12)
    expected_manifest = {
        "module_id": UI_ID,
        "display_name": "MonitorBox UI",
        "version": "1.1.4",
        "build": 12,
        "schema": 1,
        "state_schema": 1,
        "module_type": "ui",
        "entrypoints": {"webui": "monitorbox_ui_b12:install"},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    }
    if release.get("manifest") != expected_manifest:
        raise AssertionError(f"UI 1.1.4 build 12 manifest mismatch: {release.get('manifest')!r}")

    package = root / "packages" / release["package"]
    if package.name != "com.sickicarus.monitorbox.ui-1.1.4-build12.zip" or not package.is_file():
        raise AssertionError("UI 1.1.4 build 12 package is missing or misnamed")

    root_name = "monitorbox_ui_b12/"
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        expected_names = {f"{root_name}__init__.py"} | {
            f"{root_name}assets/{name}" for name in ui11.EXPECTED_ASSETS
        }
        if names != expected_names:
            raise AssertionError(
                "UI build 12 package shape changed: "
                f"missing={sorted(expected_names-names)}, extra={sorted(names-expected_names)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed UI build 12 may not shadow the Core monitorbox namespace")
        stable._assert_python_syntax(archive, names, root_name)
        adapter = archive.read(f"{root_name}__init__.py").decode("utf-8")
        modules_js = archive.read(f"{root_name}assets/modules.js").decode("utf-8")
        modules_css = archive.read(f"{root_name}assets/modules.css").decode("utf-8")

    required_adapter = (
        "Standalone managed MonitorBox UI 1.1.4 build 12",
        "from monitorbox.v2.build_info import current_build_identity",
        'app.router.add_get("/modules", modules)',
    )
    missing_adapter = [marker for marker in required_adapter if marker not in adapter]
    if missing_adapter:
        raise AssertionError(f"UI build 12 runtime markers missing: {missing_adapter}")

    required_ui = (
        "function semanticRelease(artifact)",
        "function supportFingerprint(module)",
        "function candidateStatus(module)",
        "Packaging/rebuild",
        "Array.isArray(module.actions)",
        'detail("Module API"',
        'detail("Requires Core"',
        'detail("Previous release"',
    )
    missing_ui = [marker for marker in required_ui if marker not in modules_js]
    if missing_ui:
        raise AssertionError(f"UI build 12 semantic release presentation missing: {missing_ui}")
    if "com.sickicarus.monitorbox.portainer" in modules_js:
        raise AssertionError("UI build 12 contains module-specific release presentation")
    if ".modules-release-primary" not in modules_css or ".modules-badge.blocked" not in modules_css:
        raise AssertionError("UI build 12 responsive semantic-release styles are missing")
    if "monitorbox.v2.modules.ui" in adapter:
        raise AssertionError("UI build 12 resurrects retired Core UI authority")


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

    if UI_BUILD12 in identities:
        _accept_ui12(root, source)
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
