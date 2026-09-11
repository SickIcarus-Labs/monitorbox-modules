#!/usr/bin/env python3
"""Structural acceptance for P2 Phase-1 managed UI v1.1.14 build 24."""
from __future__ import annotations

from pathlib import Path

import build_first_party_ui_build24 as candidate


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    assets = candidate._build24_assets(root)
    app = candidate._standalone_application()
    renderer = (root / "sources/ui/1.1.14-build24/modules-render.js").read_text(encoding="utf-8")
    shell = (root / "sources/ui/1.1.14-build24/app-shell.js").read_text(encoding="utf-8")
    mark = (root / "sources/ui/1.1.14-build24/monitorbox-mark.svg").read_text(encoding="utf-8")

    require(candidate.UI_VERSION == "1.1.14" and candidate.UI_BUILD == 24, "wrong build-24 identity")
    require(candidate.RELEASE24.version == "1.1.14", "release semver drift")
    require(candidate.previous.RELEASE23.build == 23, "build24 must follow accepted build23")

    required_assets = {
        "app-shell.css", "app-shell.js", "monitorbox-mark.svg", "monitorbox-glyph.svg",
        "monitorbox-192.png", "monitorbox-512.png", "monitorbox-apple-180.png",
        "monitorbox-maskable-512.png", "monitorbox.webmanifest", "modules.js", "modules.css",
    }
    require(required_assets <= set(assets), f"missing build24 assets: {sorted(required_assets-set(assets))}")
    for name in ("monitorbox-192.png", "monitorbox-512.png", "monitorbox-apple-180.png", "monitorbox-maskable-512.png"):
        require(assets[name].startswith(b"\x89PNG\r\n\x1a\n"), f"{name} is not PNG")

    # #289/#290: one generic shell, explicit Home hierarchy, runtime/site state,
    # canonical healthy green, and app/home-screen metadata.
    require("MonitorBox Home" in shell and "mb-shell-hierarchy" in shell, "shared shell lacks Home/hierarchy")
    require("/api/v2/build" in shell and "/api/v2/state" in shell, "shell lacks Core/site hydration")
    require("v${version.replace" in shell and "build ${build}" in shell and "bits.push(channel)" in shell, "shell runtime identity is incomplete")
    require("#75d69a" in mark.lower(), "brand mark does not use canonical healthy green")
    require(b"app_shell_presentation" in app and b"app.middlewares.append(app_shell_presentation)" in app, "shared shell middleware is not installed")
    require(b"monitorbox-apple-180.png" in app and b"application/manifest+json" in app, "app/home-screen brand assets are not served")

    # #286: compact/deduped groups and disclosure architecture.
    require('renderModuleGroup("Installed", installed, true)' in renderer, "Installed group must default expanded")
    require('renderModuleGroup("Available", available, false)' in renderer, "Available group must default collapsed")
    require("installedIds" in renderer and "!installedIds.has(module.module_id)" in renderer, "installed/available dedupe missing")
    require("modules-repository-one-line" in renderer and "Repository details" in renderer, "healthy repository summary/detail disclosure missing")
    require("Advanced / Diagnostics" in renderer, "diagnostics disclosure missing")
    require("No module description is published." in renderer, "legacy no-description fallback missing")

    # #287: actions come only from the Core-provided actions array and each is
    # rendered independently; Update must never replace/suppress Remove/Roll Back.
    require("Array.isArray(module.actions) ? module.actions : []" in renderer, "renderer is not driven by Core actions")
    require("for (const action of allowed) actions.append(mutationButton(module, action));" in renderer, "authorized actions are not independently rendered")
    for forbidden in ("lifecycle_policy === \"optional\" ?", "update_available ? mutationButton", "module.module_id ==="):
        require(forbidden not in renderer, f"renderer re-infers provider/lifecycle authority: {forbidden}")

    print("P2 Phase-1 UI build24 structural acceptance: PASS")


if __name__ == "__main__":
    main()
