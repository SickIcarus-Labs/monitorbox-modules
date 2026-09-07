#!/usr/bin/env python3
"""Extend first-party repository acceptance through standalone UI 1.1.3 build 11."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_backup_restore as previous

UI11 = (stable.UI_ID, "1.1.3", 11)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {UI11}
EXPECTED_ASSETS = {
    "advanced-dirty-state.js",
    "advanced-v22-polish.js",
    "conceptual-presentation.js",
    "dashboard-widgets.js",
    "dashboard.css",
    "dashboard.html",
    "dashboard.js",
    "followup-beta-polish.js",
    "global-debug.css",
    "global-debug.js",
    "http-v22-polish.js",
    "live-ping.js",
    "live-telemetry.js",
    "modules.css",
    "modules.html",
    "modules.js",
    "onboarding-v22-acceptance.js",
    "operation-progress.js",
    "policy-ui.js",
    "quick-add.js",
    "settings-v22-shell.js",
    "v1-beta-hotfix.css",
    "v1-beta-hotfix.js",
    "v1-beta-polish.css",
    "v1-beta-polish.js",
    "v1-detail-parity.css",
    "v1-detail-parity.js",
    "v1-global-diagnostics.js",
    "v1-parity.css",
    "v1-parity.js",
    "v22-shell.css",
    "v22-shell.js",
    "workspace-finish.js",
    "workspace-state.js",
    "discovery-v22.js",
    "endpoint-prefill-v22.js",
    "service-presentation.js",
    "service-presentation.css",
    "discovery-presentation.css",
    "discovery-coverage.js",
    "discovery-coverage.css",
    "network-traffic-presentation.js",
    "service-hierarchy-interactions.js",
    "service-hierarchy-physical-fixes.js",
}


def _release(source: dict) -> dict:
    for item in source.get("modules", []):
        if stable._release_identity(item) == UI11:
            return item
    raise AssertionError("standalone UI 1.1.3 build 11 is missing from catalog.source.json")


def _validate_ui11(root: Path, source: dict) -> None:
    release = _release(source)
    manifest = release["manifest"]
    expected_manifest = {
        "module_id": stable.UI_ID,
        "display_name": "MonitorBox UI",
        "version": "1.1.3",
        "build": 11,
        "schema": 1,
        "state_schema": 1,
        "module_type": "ui",
        "entrypoints": {"webui": "monitorbox_ui_b11:install"},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    }
    if manifest != expected_manifest:
        raise AssertionError(f"UI 1.1.3 build 11 manifest mismatch: {manifest!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.ui-1.1.3-build11.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("standalone UI build 11 package is missing or misnamed")

    root_name = "monitorbox_ui_b11/"
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        expected_names = {f"{root_name}__init__.py"} | {
            f"{root_name}assets/{name}" for name in EXPECTED_ASSETS
        }
        if names != expected_names:
            raise AssertionError(
                "standalone UI build 11 package shape changed: "
                f"missing={sorted(expected_names-names)}, extra={sorted(names-expected_names)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed UI build 11 may not shadow the Core monitorbox namespace")
        stable._assert_python_syntax(archive, names, root_name)
        adapter = archive.read(f"{root_name}__init__.py").decode("utf-8")

    required = (
        "Standalone managed MonitorBox UI 1.1.3 build 11",
        "from monitorbox.v2.build_info import current_build_identity",
        'app.router.add_get("/", dashboard)',
        'app.router.add_get("/modules", modules)',
        'app.router.add_get("/api/v2/build", build_identity)',
        'app.router.add_get("/static/icons/{name}", service_icon)',
        'app.router.add_get("/static/{name}", asset)',
        '"service-hierarchy-physical-fixes.js": "text/javascript"',
        '"onboarding-v22-acceptance.js": "text/javascript"',
    )
    missing = [marker for marker in required if marker not in adapter]
    if missing:
        raise AssertionError(f"standalone UI build 11 runtime markers missing: {missing}")

    forbidden = (
        "monitorbox.v2.modules.ui",
        "factory_install",
        "FACTORY_BUILD",
        "FACTORY_VERSION",
        "factory.asset",
        "factory.dashboard",
    )
    present = [marker for marker in forbidden if marker in adapter]
    if present:
        raise AssertionError(
            "standalone UI build 11 resurrects retired Core UI authority: "
            f"{present}"
        )


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _validate_ui11(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item for item in prior.get("modules", []) if stable._release_identity(item) != UI11
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
