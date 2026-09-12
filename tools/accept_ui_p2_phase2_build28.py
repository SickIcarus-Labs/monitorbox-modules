#!/usr/bin/env python3
"""Static/package acceptance for P2 Phase-2 UI v1.1.15 build 28."""
from __future__ import annotations
from pathlib import Path

import build_first_party_ui_build28 as candidate
import stage_p2_phase2_ui_build28 as stager

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    assert candidate.UI_VERSION == "1.1.15"
    assert candidate.UI_BUILD == 28
    assert candidate.UI_GENERATION == "1.1.15-28"
    assert stager.RELEASE == ("com.sickicarus.monitorbox.ui", "1.1.15", 28)
    manifest = stager.ENTRY["manifest"]
    assert manifest["description"] == "MonitorBox web interface, shared application shell, and operator presentation."
    assert manifest["entrypoints"]["webui"] == "monitorbox_ui_b28:install"

    assets = candidate._build28_assets(ROOT)
    discovery = assets["discovery-coverage.js"].decode("utf-8")
    quick_add = assets["onboarding-v22-acceptance.js"].decode("utf-8")
    css = assets["discovery-coverage.css"].decode("utf-8")
    standalone = candidate._standalone_application().decode("utf-8")

    for needle in (
        "Other discoveries",
        "Recommended by discovery policy",
        "Keep monitoring",
        "Keep existing coverage",
        "discoveryRecommendationSection",
    ):
        assert needle in discovery, needle
    for needle in ("phase2P2SortedConnections", "#newConnections", "#alreadyConfiguredConnections"):
        assert needle in quick_add, needle
    assert "discovery-subsection" in css
    assert "Standalone managed MonitorBox UI 1.1.15 build 28." in standalone
    assert "1.1.14-27" not in standalone
    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assert b"1.1.15-28" in assets[name], name

    print("P2 Phase-2 UI build28 package/release acceptance: PASS")


if __name__ == "__main__":
    main()
