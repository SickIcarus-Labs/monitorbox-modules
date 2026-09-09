#!/usr/bin/env python3
"""Extend the standalone managed UI chain through v1.1.11 build 19.

Build 19 repairs derived-child manual refresh by consuming explicit provider
execution provenance and absorbs the predeclared Discoveries disclosure-state
polish dividend. Core remains unchanged.
"""

from __future__ import annotations

from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_current as build9
import build_first_party_ui_build10 as build10
import build_first_party_ui_build11 as build11
import build_first_party_ui_build12 as build12
import build_first_party_ui_build13 as build13
import build_first_party_ui_build14 as build14
import build_first_party_ui_build15 as build15
import build_first_party_ui_build16 as build16
import build_first_party_ui_build17 as build17
import build_first_party_ui_build18 as previous

UI_VERSION = "1.1.11"
UI_BUILD = 19
RELEASE19 = stable.Release(
    build=UI_BUILD,
    certified_sha="phase3-derived-check-provenance-and-discovery-disclosure",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("phase3-p1.js", "phase3-p1.css"))


def _build19_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build18_assets(root)
    source_root = root / "sources" / "ui" / "1.1.11-build19"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.11 build-19 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )
    for name in SOURCE_FILES:
        assets[name] = (source_root / name).read_bytes()
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    replacements = (
        (
            b"Standalone managed MonitorBox UI 1.1.10 build 18.",
            b"Standalone managed MonitorBox UI 1.1.11 build 19.",
        ),
        (
            b'    "phase2-physical-repairs5.js": "text/javascript",\n}',
            b'    "phase2-physical-repairs5.js": "text/javascript",\n'
            b'    "phase3-p1.js": "text/javascript",\n'
            b'    "phase3-p1.css": "text/css",\n}',
        ),
        (
            b'_PHASE2_PHYSICAL5_SCRIPT = \'<script src="/static/phase2-physical-repairs5.js" defer></script>\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
            b'_PHASE2_PHYSICAL5_SCRIPT = \'<script src="/static/phase2-physical-repairs5.js" defer></script>\'\n'
            b'_PHASE3_P1_SCRIPT = \'<script src="/static/phase3-p1.js" defer></script>\'\n'
            b'_PHASE3_DISCLOSURE_STYLE = \'<link rel="stylesheet" href="/static/phase3-p1.css">\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
        ),
        (
            b'    if additions and "</body>" in markup:\n'
            b'        response.text = markup.replace("</body>", "".join(additions) + "</body>")',
            b'    if request.path == "/" and _PHASE3_P1_SCRIPT not in markup:\n'
            b'        additions.append(_PHASE3_P1_SCRIPT)\n'
            b'    if request.path == "/settings/discover" and _PHASE3_DISCLOSURE_STYLE not in markup:\n'
            b'        additions.append(_PHASE3_DISCLOSURE_STYLE)\n'
            b'    if additions and "</body>" in markup:\n'
            b'        response.text = markup.replace("</body>", "".join(additions) + "</body>")',
        ),
    )
    for old, new in replacements:
        if payload.count(old) != 1:
            raise SystemExit(f"UI build-19 standalone seam changed: {old[:100]!r}")
        payload = payload.replace(old, new, 1)
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build19_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 19 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8,
        build9.RELEASE9,
        build10.RELEASE10,
        build11.RELEASE11,
        build12.RELEASE12,
        build13.RELEASE13,
        build14.RELEASE14,
        build15.RELEASE15,
        build16.RELEASE16,
        build17.RELEASE17,
        previous.RELEASE18,
        RELEASE19,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
