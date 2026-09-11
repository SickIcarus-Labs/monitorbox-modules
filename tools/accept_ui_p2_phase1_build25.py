#!/usr/bin/env python3
"""Structural acceptance for P2 Phase-1 Broad Leaf correction UI v1.1.14 build 25."""
from __future__ import annotations

from pathlib import Path

import build_first_party_ui_build25 as candidate


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets = candidate._build25_assets(root)
    app = candidate._standalone_application()
    renderer = (root / "sources/ui/1.1.14-build25/modules-render.js").read_text(encoding="utf-8")
    polish = (root / "sources/ui/1.1.14-build25/modules-polish.css").read_text(encoding="utf-8")
    shell_actions = (root / "sources/ui/1.1.14-build25/app-shell-actions.js").read_text(encoding="utf-8")

    require(candidate.UI_VERSION == "1.1.14" and candidate.UI_BUILD == 25, "wrong build-25 identity")
    require(candidate.RELEASE25.version == "1.1.14", "build25 semantic version drift")
    require(candidate.accepted.RELEASE23.build == 23, "build25 catalog predecessor must remain accepted build23")

    # Rejected build24 is an implementation predecessor only; build25 remains the same
    # logical patch but must carry a fresh build cache identity.
    require(b"1.1.14-25" in app and b"1.1.14-24" not in app, "standalone shell cache identity was not advanced")
    require(b"1.1.14-25" in assets["app-shell.js"], "app shell cache identity was not advanced")

    # #286 physical feedback: visible disclosures, fixed scan columns, compact healthy auth,
    # concise official channel labels, and continued Core-action authority.
    require("normalizedRepositoryChannel" in renderer, "repository channel normalization missing")
    require('return "stable";' in renderer and '[["dev", 0], ["beta", 1], ["stable", 2]]' in renderer, "official channel summary contract missing")
    require("modules-disclosure" in renderer, "generic disclosure class missing")
    require("for (const action of allowed) actions.append(mutationButton(module, action));" in renderer, "Core-authorized actions are not independently rendered")
    require("modules-disclosure>summary::before" in polish, "visible disclosure chevron missing")
    require("modules-disclosure[open]>summary::before" in polish, "open disclosure state missing")
    require("grid-template-columns:minmax(0,1fr) 180px 135px" in polish, "shared module columns are not fixed")
    require(".modules-auth:has(.modules-login-form[hidden])" in polish, "healthy auth compaction missing")

    # #289 physical feedback: the host shell consumes all legacy global controls instead
    # of moving a second hamburger/product/site identity into page-local actions.
    for legacy_id in (
        "settingsV22MenuButton",
        "settingsProductHome",
        "settingsBackToMonitoring",
        "settingsV22Spacer",
        "settingsSiteHome",
        "settingsV22Menu",
    ):
        require(legacy_id in shell_actions, f"legacy shell node is not explicitly consumed: {legacy_id}")
    require("actionStrip.append(child)" in shell_actions, "real page-local actions are no longer preserved")

    print("P2 Phase-1 UI build25 structural acceptance: PASS")


if __name__ == "__main__":
    main()
