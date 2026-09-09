#!/usr/bin/env python3
"""Extend the standalone managed UI chain through v1.1.13 build 21.

Build 21 fixes provider-neutral relationship discoverability in Advanced Workspace
and surfaces health-neutral maintenance evidence on healthy dashboard cards.
"""

from __future__ import annotations

from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build20 as previous

UI_VERSION = "1.1.13"
UI_BUILD = 21
RELEASE21 = stable.Release(
    build=UI_BUILD,
    certified_sha="phase6-ui-relationship-and-maintenance-convergence",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("phase6-convergence.js", "phase6-convergence.css"))


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-21 {seam} seam changed: {old[:120]!r}")
    return payload.replace(old, new, 1)


def _build21_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build20_assets(root)
    source_root = root / "sources" / "ui" / "1.1.13-build21"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.13 build-21 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )
    for name in SOURCE_FILES:
        assets[name] = (source_root / name).read_bytes()

    dashboard_html = assets["dashboard.html"]
    dashboard_html = _replace_once(
        dashboard_html,
        b'  <script src="/static/dashboard.js" defer></script>',
        b'  <link rel="stylesheet" href="/static/phase6-convergence.css">\n'
        b'  <script src="/static/phase6-convergence.js" defer></script>\n'
        b'  <script src="/static/dashboard.js" defer></script>',
        "dashboard asset ordering",
    )
    assets["dashboard.html"] = dashboard_html

    dashboard_js = assets["dashboard.js"]
    old_card = (
        b'<span class="card-summary">${esc(worstSummary(object))}</span></button>'
    )
    new_card = (
        b'<span class="card-summary">${esc(worstSummary(object))}</span>'
        b'${globalThis.MonitorBoxPhase6Convergence?.maintenanceMarkup?.(object)||\'\'}'
        b'</button>'
    )
    assets["dashboard.js"] = _replace_once(
        dashboard_js, old_card, new_card, "dashboard maintenance card"
    )

    workspace_js = assets["workspace-state.js"]
    old_workspace = b"    bindPolicyControls();\n    updatePendingUi();\n  }"
    new_workspace = (
        b"    bindPolicyControls();\n"
        b"    updatePendingUi();\n"
        b"    globalThis.MonitorBoxPhase6Convergence?.decorateWorkspace?.(model,document);\n"
        b"  }"
    )
    assets["workspace-state.js"] = _replace_once(
        workspace_js, old_workspace, new_workspace, "workspace relationship hook"
    )
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    replacements = (
        (
            b"Standalone managed MonitorBox UI 1.1.12 build 20.",
            b"Standalone managed MonitorBox UI 1.1.13 build 21.",
        ),
        (
            b'    "phase3-local-control.css": "text/css",\n}',
            b'    "phase3-local-control.css": "text/css",\n'
            b'    "phase6-convergence.js": "text/javascript",\n'
            b'    "phase6-convergence.css": "text/css",\n}',
        ),
        (
            b'_ADVANCED_DIRTY_STATE_SCRIPT = \'<script src="/static/advanced-dirty-state.js" defer></script>\'\n',
            b'_ADVANCED_DIRTY_STATE_SCRIPT = \'<script src="/static/advanced-dirty-state.js" defer></script>\'\n'
            b'_PHASE6_CONVERGENCE_SCRIPT = \'<script src="/static/phase6-convergence.js" defer></script>\'\n'
            b'_PHASE6_CONVERGENCE_STYLE = \'<link rel="stylesheet" href="/static/phase6-convergence.css">\'\n',
        ),
        (
            b'        if request.path == "/settings/advanced":\n'
            b'            scripts.extend((_ADVANCED_POLISH_SCRIPT, _ADVANCED_DIRTY_STATE_SCRIPT))\n',
            b'        if request.path == "/settings/advanced":\n'
            b'            scripts.extend((_ADVANCED_POLISH_SCRIPT, _ADVANCED_DIRTY_STATE_SCRIPT, _PHASE6_CONVERGENCE_STYLE, _PHASE6_CONVERGENCE_SCRIPT))\n',
        ),
    )
    for old, new in replacements:
        payload = _replace_once(payload, old, new, "standalone application")
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build21_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 21 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    stable.RELEASES = stable.RELEASES + (
        previous.previous.build9.RELEASE8,
        previous.previous.build9.RELEASE9,
        previous.previous.build10.RELEASE10,
        previous.previous.build11.RELEASE11,
        previous.previous.build12.RELEASE12,
        previous.previous.build13.RELEASE13,
        previous.previous.build14.RELEASE14,
        previous.previous.build15.RELEASE15,
        previous.previous.build16.RELEASE16,
        previous.previous.build17.RELEASE17,
        previous.previous.previous.RELEASE18,
        previous.previous.RELEASE19,
        previous.RELEASE20,
        RELEASE21,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
