#!/usr/bin/env python3
"""Package/source acceptance for UI 1.4.0 build38 (#359/#220)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import build_first_party_ui_build38 as candidate

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    files = candidate._package_files(ROOT)
    prefix = candidate.TARGET_IMPORT_PACKAGE + "/"
    assets = {
        path.removeprefix(prefix + "assets/"): payload
        for path, payload in files.items()
        if path.startswith(prefix + "assets/")
    }
    init = files[prefix + "__init__.py"]
    dashboard = assets["dashboard.html"]
    projection = assets["card-projection.js"].decode("utf-8")

    assert b"Standalone managed MonitorBox UI 1.4.0 build 38." in init
    assert candidate.UI_GENERATION.encode() in init
    assert candidate.PARENT_GENERATION.encode() not in init
    assert b"card-projection.js" in dashboard
    assert b"aggregate-evidence.js" not in dashboard

    for required in (
        "site?.cards",
        "dashboard_card",
        "projectedCoreObjects",
        "object.kind === 'host'",
    ):
        assert required in projection, required

    lower = projection.lower()
    for forbidden in ("unifi", "scrypted", "portainer", "nut", "docker"):
        assert forbidden not in lower, forbidden

    with tempfile.TemporaryDirectory() as raw:
        first = candidate.build(ROOT, Path(raw) / "one").read_bytes()
        second = candidate.build(ROOT, Path(raw) / "two").read_bytes()
        assert first == second

    print("UI 1.4.0 build38 card-projection package acceptance passed")


if __name__ == "__main__":
    main()
