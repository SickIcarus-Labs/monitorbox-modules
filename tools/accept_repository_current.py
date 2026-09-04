#!/usr/bin/env python3
"""Extend the stable repository acceptance through the current Portainer release.

The historical acceptance remains intentionally strict for previously published
artifacts. This adapter adds the v1.1.0 build-6 contract without weakening or
rewriting those historical assertions.
"""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable

CURRENT_PORTAINER = (stable.PORTAINER_ID, "1.1.0", 6)
HISTORICAL_RELEASES = set(stable.EXPECTED_RELEASES)
CURRENT_RELEASES = HISTORICAL_RELEASES | {CURRENT_PORTAINER}
_STABLE_PACKAGE_SHAPE = stable._package_shape


def _current_package_shape(root: Path, source: dict) -> None:
    release = next(
        (
            item
            for item in source.get("modules", [])
            if stable._release_identity(item) == CURRENT_PORTAINER
        ),
        None,
    )
    if release is None:
        raise AssertionError("Portainer v1.1.0 build 6 is missing from catalog.source.json")

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

    # Re-run every historical package assertion against exactly the historical
    # catalog slice, then restore the current release set for signed-index proof.
    historical = copy.deepcopy(source)
    historical["modules"] = [
        item
        for item in historical.get("modules", [])
        if stable._release_identity(item) != CURRENT_PORTAINER
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
