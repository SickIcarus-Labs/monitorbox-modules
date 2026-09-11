#!/usr/bin/env python3
"""Structural acceptance for the P2 Phase-1 wrap-up UI v1.1.14 build 26."""
from __future__ import annotations

from pathlib import Path

import build_first_party_ui_build26 as candidate


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets = candidate._build26_assets(root)
    app = candidate._standalone_application()
    shell = assets["app-shell.js"].decode("utf-8")
    shell_css = assets["app-shell.css"].decode("utf-8")

    require(candidate.UI_VERSION == "1.1.14" and candidate.UI_BUILD == 26, "wrong build-26 identity")
    require(candidate.RELEASE26.version == "1.1.14", "build26 semantic version drift")
    require(candidate.accepted.RELEASE23.build == 23, "build26 accepted predecessor must remain build23")
    require(b"Standalone managed MonitorBox UI 1.1.14 build 26." in app, "standalone build26 identity missing")

    # #303: every managed page gets generation-versioned assets, matching generation
    # URLs are immutable, and stale generation requests are redirected to active bytes.
    require(b'_UI_GENERATION = "1.1.14-26"' in app, "server UI generation identity missing")
    require(b"_version_managed_assets" in app, "HTML managed-asset versioning missing")
    require(b"public, max-age=31536000, immutable" in app, "immutable generation cache policy missing")
    require(b"HTTPTemporaryRedirect" in app, "stale-generation redirect missing")
    require(b"X-MonitorBox-UI-Generation" in app, "UI generation diagnostic header missing")
    require(b"requested_generation == _UI_GENERATION" in app, "immutable cache is not generation-gated")

    # #304: shell runtime/site hydration is explicitly off the DOM-content critical path
    # and uses bounded session cache for immediate cross-page shell continuity.
    require("sessionStorage" in shell, "shared shell session cache missing")
    require("requestIdleCallback" in shell, "shell hydration is not deferred to idle/load")
    require("window.addEventListener('load', idle" in shell, "shell hydration is not post-load")
    require("Promise.allSettled" in shell, "independent shell hydration requests lost")
    require("backdrop-filter:none" in shell_css, "expensive sticky-shell blur was not removed")

    # #289: adopt the already-bound dashboard Debug node into the shared shell rather
    # than inventing a disconnected duplicate or losing the diagnostic affordance.
    require("const debugControl = document.getElementById('debug-toggle')" in shell, "legacy Debug control is not adopted")
    require("createShell(meta, debugControl)" in shell, "Debug control is not handed to shared shell")
    require("debugControl.className = 'mb-shell-debug'" in shell, "Debug shell presentation missing")
    require("debug-toggle" not in shell.split("const dashboardActionIds =",1)[1].split(";",1)[0], "Debug still belongs to page-action strip")
    require(".mb-shell-debug" in shell_css, "Debug shell styling missing")

    # The build26 generation must replace rejected build25 cache identities in active
    # shell/manifest assets; immutable old package bytes themselves remain untouched.
    require(b"1.1.14-25" not in assets["app-shell.js"], "stale build25 shell generation leaked")
    require(b"1.1.14-25" not in assets["app-shell.css"], "stale build25 shell CSS generation leaked")
    require(b"1.1.14-25" not in assets["monitorbox.webmanifest"], "stale build25 manifest generation leaked")

    print("P2 Phase-1 UI build26 structural acceptance: PASS")


if __name__ == "__main__":
    main()
