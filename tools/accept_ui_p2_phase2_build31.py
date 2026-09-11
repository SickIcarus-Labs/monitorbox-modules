#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path

import build_first_party_ui_build31 as candidate
import stage_p2_phase2_ui_build31 as stager

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    assert candidate.UI_VERSION == "1.1.18"
    assert candidate.UI_BUILD == 31
    assert candidate.UI_GENERATION == "1.1.18-31"
    assert stager.RELEASE == ("com.sickicarus.monitorbox.ui", "1.1.18", 31)
    assert stager.ENTRY["manifest"]["requires_core"].startswith(">=2.4.1")
    assets = candidate._build31_assets(ROOT)
    discovery = assets["discovery-coverage.js"].decode("utf-8")
    service = assets["service-presentation.js"].decode("utf-8")
    standalone = candidate._standalone_application().decode("utf-8")
    for needle in (
        "monitoring_suppressed",
        "monitoring_state",
        "Keep monitoring",
        "Stop monitoring",
        "Start monitoring",
        "provider-unified-monitoring",
    ):
        assert needle in discovery, needle
    for forbidden in ("Add configured monitor", "Keep existing coverage", "provider-covered-static')"):
        assert forbidden not in discovery, forbidden
    assert "monitoring_suppressions" in service
    assert "portainer:${identity}" in service
    assert "Standalone managed MonitorBox UI 1.1.18 build 31." in standalone
    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assert b"1.1.18-31" in assets[name], name
    print("P2 Phase-2 UI build31 unified-monitoring package acceptance: PASS")


if __name__ == "__main__":
    main()
