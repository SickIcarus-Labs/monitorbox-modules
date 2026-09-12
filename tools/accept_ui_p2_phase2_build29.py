#!/usr/bin/env python3
"""Static/package acceptance for P2 Phase-2 UI v1.1.16 build 29."""
from __future__ import annotations
from pathlib import Path

import build_first_party_ui_build29 as candidate
import stage_p2_phase2_ui_build29 as stager

ROOT=Path(__file__).resolve().parent.parent


def main()->None:
    assert candidate.UI_VERSION=="1.1.16"
    assert candidate.UI_BUILD==29
    assert candidate.UI_GENERATION=="1.1.16-29"
    assert stager.RELEASE==("com.sickicarus.monitorbox.ui","1.1.16",29)
    assert stager.ENTRY["manifest"]["description"]=="MonitorBox web interface, shared application shell, and operator presentation."
    assert stager.ENTRY["manifest"]["entrypoints"]["webui"]=="monitorbox_ui_b29:install"

    assets=candidate._build29_assets(ROOT)
    discovery=assets["discovery-coverage.js"].decode("utf-8")
    modules=assets["modules.js"].decode("utf-8")
    quick_add=assets["onboarding-v22-acceptance.js"].decode("utf-8")
    standalone=candidate._standalone_application().decode("utf-8")

    for needle in (
        "Other discoveries","Recommended by discovery policy","Keep monitoring",
        "provider-covered-static","Monitored","recommendation_reason",
    ): assert needle in discovery,needle
    assert "Add configured monitor" in discovery  # immutable build-28 history may contain it
    assert "module.installed?.description" in modules
    assert "MonitorBox web interface, shared application shell, and operator presentation." in modules
    assert "phase2P2SortedConnections" in quick_add
    assert "Standalone managed MonitorBox UI 1.1.16 build 29." in standalone
    assert "1.1.15-28" not in standalone
    for name in ("app-shell.js","app-shell.css","monitorbox.webmanifest"):
        assert b"1.1.16-29" in assets[name],name
    print("P2 Phase-2 UI build29 package/release acceptance: PASS")


if __name__=="__main__": main()
