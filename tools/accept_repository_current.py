#!/usr/bin/env python3
"""Extend stable repository acceptance through current semantic releases.

Historical release assertions remain byte/shape strict in ``accept_repository``.
This adapter validates only the newly published Portainer v1.1.0 build 6 and
candidate UI v1.1.0 build 8, then delegates all signing/digest/index checks to
the existing stable acceptance implementation.
"""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable

CURRENT_PORTAINER = (stable.PORTAINER_ID, "1.1.0", 6)
CURRENT_UI = (stable.UI_ID, "1.1.0", 8)
CURRENT_ONLY = {CURRENT_PORTAINER, CURRENT_UI}
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


def _accept_current_ui(root: Path, source: dict) -> None:
    release = _release(source, CURRENT_UI)
    manifest = release["manifest"]
    if manifest.get("entrypoints") != {"webui": "monitorbox_ui_b8:install"}:
        raise AssertionError("UI v1.1.0 build 8 entrypoint is not generation-safe")
    if manifest.get("module_type") != "ui" or manifest.get("lifecycle_policy") != "required":
        raise AssertionError("UI v1.1.0 build 8 lifecycle/type contract changed")
    if manifest.get("requires_core") != ">=2.2.2 <3.0.0":
        raise AssertionError("UI v1.1.0 build 8 Core compatibility changed")

    package_path = root / "packages" / release["package"]
    if not package_path.is_file():
        raise AssertionError(f"generated package is missing: {package_path.name}")
    package = "monitorbox_ui_b8"
    root_name = f"{package}/"
    expected_assets = {
        "discovery-v22.js",
        "endpoint-prefill-v22.js",
        "service-presentation.js",
        "service-presentation.css",
        "discovery-presentation.css",
        "discovery-coverage.js",
        "discovery-coverage.css",
    }
    expected_names = {f"{root_name}__init__.py"} | {
        f"{root_name}assets/{name}" for name in expected_assets
    }
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != expected_names:
            raise AssertionError(
                "UI v1.1.0 build 8 package shape changed: "
                f"missing={sorted(expected_names-names)}, extra={sorted(names-expected_names)}"
            )
        stable._assert_python_syntax(archive, names, root_name)
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

        coverage_css = archive.read(f"{root_name}assets/discovery-coverage.css").decode("utf-8")
        required_css = (
            ".discovery-coverage-section",
            ".discovery-proposed-action",
            ".discovery-section-count",
            "min-height: 46px",
            "@media (max-width: 759px)",
        )
        missing = [marker for marker in required_css if marker not in coverage_css]
        if missing:
            raise AssertionError(f"UI build 8 omitted grouped-discovery CSS markers: {missing}")

        # Build 8 composes every certified build-7 capability rather than
        # replacing discovery provenance or provider-backed Service hierarchy.
        discovery = archive.read(f"{root_name}assets/discovery-v22.js").decode("utf-8")
        hierarchy = archive.read(f"{root_name}assets/service-presentation.js").decode("utf-8")
        for marker in (
            "function providerProvenance(item)",
            "renderProviderProvenance(row,item);",
        ):
            if marker not in discovery:
                raise AssertionError(f"UI build 8 regressed provider provenance marker {marker!r}")
        for marker in (
            "function serviceComposeProvenance(service)",
            "function providerPresentationModel(site)",
            "kind:'provider_workload'",
        ):
            if marker not in hierarchy:
                raise AssertionError(f"UI build 8 regressed Service hierarchy marker {marker!r}")


def _current_package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _accept_current_portainer(root, source)
    _accept_current_ui(root, source)

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
