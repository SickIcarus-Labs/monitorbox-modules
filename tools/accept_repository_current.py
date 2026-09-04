#!/usr/bin/env python3
"""Extend stable repository acceptance through current semantic releases.

Historical release assertions remain byte/shape strict in ``accept_repository``.
This adapter validates current Portainer v1.1.0 build 6 plus UI v1.1.0 build 8
and UI v1.1.1 build 9, then delegates signing/digest/index checks to the stable
acceptance implementation.
"""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable

CURRENT_PORTAINER = (stable.PORTAINER_ID, "1.1.0", 6)
CURRENT_UI8 = (stable.UI_ID, "1.1.0", 8)
CURRENT_UI9 = (stable.UI_ID, "1.1.1", 9)
CURRENT_ONLY = {CURRENT_PORTAINER, CURRENT_UI8, CURRENT_UI9}
HISTORICAL_RELEASES = set(stable.EXPECTED_RELEASES)
CURRENT_RELEASES = HISTORICAL_RELEASES | CURRENT_ONLY
_STABLE_PACKAGE_SHAPE = stable._package_shape


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


def _accept_current_portainer(root: Path, source: dict) -> None:
    release = _release(source, CURRENT_PORTAINER)
    manifest = release["manifest"]
    if manifest.get("entrypoints") != {"integration": "monitorbox_portainer_b6:PLUGIN"}:
        raise AssertionError("Portainer v1.1.0 build 6 entrypoint is not generation-safe")
    if manifest.get("module_type") != "integration" or manifest.get("lifecycle_policy") != "optional":
        raise AssertionError("Portainer v1.1.0 build 6 lifecycle/type contract changed")
    if manifest.get("requires_core") != ">=2.3.0 <3.0.0":
        raise AssertionError("Portainer v1.1.0 build 6 Core compatibility changed")

    package_path = root / "packages" / release["package"]
    if not package_path.is_file():
        raise AssertionError(f"generated package is missing: {package_path.name}")
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        stable._portainer_package_shape(archive, names, 6)
        suggestions = archive.read("monitorbox_portainer_b6/suggestions.py").decode("utf-8")
        required = (
            '"monitoring_coverage"',
            '"status": "covered"',
            '"kind": "provider_inventory"',
            '"source_label": "Portainer"',
        )
        missing = [marker for marker in required if marker not in suggestions]
        if missing:
            raise AssertionError(
                f"Portainer v1.1.0 build 6 omitted monitoring-coverage markers: {missing}"
            )


def _ui_package(root: Path, source: dict, identity: tuple[str, str, int], package: str, expected_assets: set[str]) -> tuple[zipfile.ZipFile, str]:
    release = _release(source, identity)
    package_path = root / "packages" / release["package"]
    if not package_path.is_file():
        raise AssertionError(f"generated package is missing: {package_path.name}")
    archive = zipfile.ZipFile(package_path)
    root_name = f"{package}/"
    expected_names = {f"{root_name}__init__.py"} | {
        f"{root_name}assets/{name}" for name in expected_assets
    }
    names = set(archive.namelist())
    if names != expected_names:
        archive.close()
        raise AssertionError(
            f"{identity} package shape changed: "
            f"missing={sorted(expected_names-names)}, extra={sorted(names-expected_names)}"
        )
    stable._assert_python_syntax(archive, names, root_name)
    return archive, root_name


def _accept_current_ui8(root: Path, source: dict) -> None:
    release = _release(source, CURRENT_UI8)
    manifest = release["manifest"]
    if manifest.get("entrypoints") != {"webui": "monitorbox_ui_b8:install"}:
        raise AssertionError("UI v1.1.0 build 8 entrypoint is not generation-safe")
    if manifest.get("module_type") != "ui" or manifest.get("lifecycle_policy") != "required":
        raise AssertionError("UI v1.1.0 build 8 lifecycle/type contract changed")
    if manifest.get("requires_core") != ">=2.2.2 <3.0.0":
        raise AssertionError("UI v1.1.0 build 8 Core compatibility changed")

    expected_assets = {
        "discovery-v22.js", "endpoint-prefill-v22.js", "service-presentation.js",
        "service-presentation.css", "discovery-presentation.css",
        "discovery-coverage.js", "discovery-coverage.css",
    }
    archive, root_name = _ui_package(root, source, CURRENT_UI8, "monitorbox_ui_b8", expected_assets)
    with archive:
        adapter = archive.read(f"{root_name}__init__.py").decode("utf-8")
        adapter_required = (
            "managed UI 1.1.0 build 8",
            '"discovery-coverage.js": "text/javascript"',
            '"discovery-coverage.css": "text/css"',
            '/settings/discover',
            '/static/discovery-coverage.js',
            '/static/discovery-coverage.css',
        )
        missing = [marker for marker in adapter_required if marker not in adapter]
        if missing:
            raise AssertionError(f"UI build 8 adapter omitted coverage assets: {missing}")

        coverage_js = archive.read(f"{root_name}assets/discovery-coverage.js").decode("utf-8")
        required_js = (
            "monitoring_coverage",
            "Already monitored via ${coverage.sourceLabel}",
            "Add configured monitor",
            "New / not yet monitored",
            "Already monitored",
            "configuration change${staged===1?'':'s'} selected",
        )
        missing = [marker for marker in required_js if marker not in coverage_js]
        if missing:
            raise AssertionError(f"UI build 8 omitted coverage/action contract markers: {missing}")
        if "Portainer" in coverage_js or "source==='portainer'" in coverage_js:
            raise AssertionError("UI build 8 must consume generic coverage truth without Portainer branching")

        hierarchy = archive.read(f"{root_name}assets/service-presentation.js").decode("utf-8")
        for marker in (
            "function serviceComposeProvenance(service)",
            "function providerPresentationModel(site)",
            "kind:'provider_workload'",
        ):
            if marker not in hierarchy:
                raise AssertionError(f"UI build 8 regressed Service hierarchy marker {marker!r}")


def _accept_current_ui9(root: Path, source: dict) -> None:
    release = _release(source, CURRENT_UI9)
    manifest = release["manifest"]
    if manifest.get("entrypoints") != {"webui": "monitorbox_ui_b9:install"}:
        raise AssertionError("UI v1.1.1 build 9 entrypoint is not generation-safe")
    if manifest.get("module_type") != "ui" or manifest.get("lifecycle_policy") != "required":
        raise AssertionError("UI v1.1.1 build 9 lifecycle/type contract changed")
    if manifest.get("requires_core") != ">=2.2.2 <3.0.0":
        raise AssertionError("UI v1.1.1 build 9 Core compatibility changed")

    expected_assets = {
        "discovery-v22.js", "endpoint-prefill-v22.js", "service-presentation.js",
        "service-presentation.css", "discovery-presentation.css",
        "discovery-coverage.js", "discovery-coverage.css",
        "network-traffic-presentation.js", "service-hierarchy-interactions.js",
    }
    archive, root_name = _ui_package(root, source, CURRENT_UI9, "monitorbox_ui_b9", expected_assets)
    with archive:
        adapter = archive.read(f"{root_name}__init__.py").decode("utf-8")
        required_adapter = (
            "managed UI 1.1.1 build 9",
            '"network-traffic-presentation.js": "text/javascript"',
            '"service-hierarchy-interactions.js": "text/javascript"',
            '/static/network-traffic-presentation.js',
            '/static/service-hierarchy-interactions.js',
            'request.path == "/"',
        )
        missing = [marker for marker in required_adapter if marker not in adapter]
        if missing:
            raise AssertionError(f"UI build 9 adapter omitted dashboard deltas: {missing}")

        traffic = archive.read(f"{root_name}assets/network-traffic-presentation.js").decode("utf-8")
        required_traffic = (
            "traffic-detail provider or its configuration is unavailable",
            "Throughput above remains valid from counter telemetry",
            "attribution_available:false",
            "does not coerce malformed producer data",
        )
        missing = [marker for marker in required_traffic if marker not in traffic]
        if missing:
            raise AssertionError(f"UI build 9 omitted traffic presentation markers: {missing}")
        forbidden_traffic = (
            "uiBuild9BusiestCounterSeries",
            "renderLiveOverview=function",
            "liveChart=function",
        )
        present = [marker for marker in forbidden_traffic if marker in traffic]
        if present:
            raise AssertionError(
                f"UI build 9 must not mask malformed producer telemetry or replace baseline chart rendering: {present}"
            )

        hierarchy_patch = archive.read(f"{root_name}assets/service-hierarchy-interactions.js").decode("utf-8")
        required_hierarchy = (
            "uiBuild9ProviderPresentationUrl",
            "app.serviceStackExpansion",
            "details[data-compose-stack]",
            ".service-compose-members a.icon-outbound",
        )
        missing = [marker for marker in required_hierarchy if marker not in hierarchy_patch]
        if missing:
            raise AssertionError(f"UI build 9 omitted hierarchy interaction markers: {missing}")

        coverage_js = archive.read(f"{root_name}assets/discovery-coverage.js").decode("utf-8")
        if "monitoring_coverage" not in coverage_js or "Already monitored" not in coverage_js:
            raise AssertionError("UI build 9 regressed build-8 discovery coverage semantics")
        hierarchy = archive.read(f"{root_name}assets/service-presentation.js").decode("utf-8")
        if "function providerPresentationModel(site)" not in hierarchy:
            raise AssertionError("UI build 9 regressed provider-backed Service hierarchy")


def _current_package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _accept_current_portainer(root, source)
    _accept_current_ui8(root, source)
    _accept_current_ui9(root, source)

    historical = copy.deepcopy(source)
    historical["modules"] = [
        item
        for item in historical.get("modules", [])
        if stable._release_identity(item) not in CURRENT_ONLY
    ]
    saved = stable.EXPECTED_RELEASES
    stable.EXPECTED_RELEASES = HISTORICAL_RELEASES
    try:
        _STABLE_PACKAGE_SHAPE(root, historical)
    finally:
        stable.EXPECTED_RELEASES = saved


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _current_package_shape
    stable.main()


if __name__ == "__main__":
    main()
