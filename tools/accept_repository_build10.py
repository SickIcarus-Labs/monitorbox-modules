#!/usr/bin/env python3
"""Extend repository acceptance through UI v1.1.2 build 10."""

from __future__ import annotations

import copy
from pathlib import Path

import accept_repository as stable
import accept_repository_current as previous

CURRENT_UI10 = (stable.UI_ID, "1.1.2", 10)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {CURRENT_UI10}


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


def _accept_ui10(root: Path, source: dict) -> None:
    release = _release(source, CURRENT_UI10)
    manifest = release["manifest"]
    if manifest.get("entrypoints") != {"webui": "monitorbox_ui_b10:install"}:
        raise AssertionError("UI v1.1.2 build 10 entrypoint is not generation-safe")
    if manifest.get("module_type") != "ui" or manifest.get("lifecycle_policy") != "required":
        raise AssertionError("UI v1.1.2 build 10 lifecycle/type contract changed")
    if manifest.get("requires_core") != ">=2.2.2 <3.0.0":
        raise AssertionError("UI v1.1.2 build 10 Core compatibility changed")

    expected_assets = {
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
    archive, root_name = previous._ui_package(
        root,
        source,
        CURRENT_UI10,
        "monitorbox_ui_b10",
        expected_assets,
    )
    with archive:
        adapter = archive.read(f"{root_name}__init__.py").decode("utf-8")
        required_adapter = (
            "managed UI 1.1.2 build 10",
            '"service-hierarchy-physical-fixes.js": "text/javascript"',
            '/static/service-hierarchy-physical-fixes.js',
            '_SERVICE_HIERARCHY_PHYSICAL_SCRIPT',
        )
        missing = [marker for marker in required_adapter if marker not in adapter]
        if missing:
            raise AssertionError(f"UI build 10 adapter omitted physical-fix assets: {missing}")

        fix = archive.read(
            f"{root_name}assets/service-hierarchy-physical-fixes.js"
        ).decode("utf-8")
        required_fix = (
            "uiBuild10ReconcileCandidate",
            "uiBuild10WorkloadEndpointMatch",
            "uiBuild10SharesOwner",
            "uiBuild10StackKey",
            "encodeURIComponent(environment)",
            "data-compose-stack",
        )
        missing = [marker for marker in required_fix if marker not in fix]
        if missing:
            raise AssertionError(f"UI build 10 omitted physical correction markers: {missing}")
        if "http://${" in fix or "https://${" in fix:
            raise AssertionError("UI build 10 must not fabricate HTTP(S) URLs from provider TCP ports")

        hierarchy = archive.read(
            f"{root_name}assets/service-hierarchy-interactions.js"
        ).decode("utf-8")
        if "app.serviceStackExpansion" not in hierarchy:
            raise AssertionError("UI build 10 lost build-9 disclosure-state support")
        traffic = archive.read(
            f"{root_name}assets/network-traffic-presentation.js"
        ).decode("utf-8")
        if "Throughput above remains valid from counter telemetry" not in traffic:
            raise AssertionError("UI build 10 regressed build-9 traffic presentation truth")


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _accept_ui10(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) != CURRENT_UI10
    ]
    previous._current_package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
