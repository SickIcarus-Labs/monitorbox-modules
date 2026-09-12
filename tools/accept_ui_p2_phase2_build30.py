#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path

import build_first_party_ui_build30 as candidate
import stage_p2_phase2_ui_build30 as stager

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    assert candidate.UI_VERSION == "1.1.17"
    assert candidate.UI_BUILD == 30
    assert candidate.UI_GENERATION == "1.1.17-30"
    assert stager.RELEASE == ("com.sickicarus.monitorbox.ui", "1.1.17", 30)
    assert stager.ENTRY["manifest"]["description"] == "MonitorBox web interface, shared application shell, and operator presentation."
    assets = candidate._build30_assets(ROOT)
    discovery = assets["discovery-coverage.js"].decode("utf-8")
    standalone = candidate._standalone_application().decode("utf-8")
    for needle in (
        "Inter-switch link →",
        "recommendation_relationship",
        "provider-covered-static",
        "Keep monitoring",
        "Monitored",
    ):
        assert needle in discovery, needle
    assert "Standalone managed MonitorBox UI 1.1.17 build 30." in standalone
    assert "1.1.16-29" not in standalone
    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assert b"1.1.17-30" in assets[name], name
    print("P2 Phase-2 UI build30 package/release acceptance: PASS")


if __name__ == "__main__":
    main()
