#!/usr/bin/env python3
"""Extend the standalone managed UI chain through v1.1.12 build 20.

Build 20 makes browser/access-path failure distinct from controller failure,
projects the Bootstrap-owned local recovery address, preserves stale-state age,
and provides a frozen manual debug-copy fallback for insecure HTTP origins.
"""

from __future__ import annotations

from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build19 as previous

UI_VERSION = "1.1.12"
UI_BUILD = 20
RELEASE20 = stable.Release(
    build=UI_BUILD,
    certified_sha="phase3-local-control-plane-and-debug-copy",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("phase3-local-control.js", "phase3-local-control.css"))


def _build20_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build19_assets(root)
    source_root = root / "sources" / "ui" / "1.1.12-build20"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.12 build-20 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )
    for name in SOURCE_FILES:
        assets[name] = (source_root / name).read_bytes()
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    replacements = (
        (
            b"Standalone managed MonitorBox UI 1.1.11 build 19.",
            b"Standalone managed MonitorBox UI 1.1.12 build 20.",
        ),
        (
            b'    "phase3-p1.css": "text/css",\n}',
            b'    "phase3-p1.css": "text/css",\n'
            b'    "phase3-local-control.js": "text/javascript",\n'
            b'    "phase3-local-control.css": "text/css",\n}',
        ),
        (
            b'_PHASE3_DISCLOSURE_STYLE = \'<link rel="stylesheet" href="/static/phase3-p1.css">\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
            b'_PHASE3_DISCLOSURE_STYLE = \'<link rel="stylesheet" href="/static/phase3-p1.css">\'\n'
            b'_PHASE3_LOCAL_SCRIPT = \'<script src="/static/phase3-local-control.js" defer></script>\'\n'
            b'_PHASE3_LOCAL_STYLE = \'<link rel="stylesheet" href="/static/phase3-local-control.css">\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
        ),
        (
            b'    if request.path == "/" and _PHASE3_P1_SCRIPT not in markup:\n'
            b'        additions.append(_PHASE3_P1_SCRIPT)\n'
            b'    if request.path == "/settings/discover" and _PHASE3_DISCLOSURE_STYLE not in markup:\n',
            b'    if request.path == "/" and _PHASE3_P1_SCRIPT not in markup:\n'
            b'        additions.append(_PHASE3_P1_SCRIPT)\n'
            b'    if request.path == "/" and _PHASE3_LOCAL_SCRIPT not in markup:\n'
            b'        additions.extend((_PHASE3_LOCAL_STYLE, _PHASE3_LOCAL_SCRIPT))\n'
            b'    if request.path == "/settings/discover" and _PHASE3_DISCLOSURE_STYLE not in markup:\n',
        ),
    )
    for old, new in replacements:
        if payload.count(old) != 1:
            raise SystemExit(f"UI build-20 standalone seam changed: {old[:100]!r}")
        payload = payload.replace(old, new, 1)
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build20_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 20 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    stable.RELEASES = stable.RELEASES + (
        previous.build9.RELEASE8,
        previous.build9.RELEASE9,
        previous.build10.RELEASE10,
        previous.build11.RELEASE11,
        previous.build12.RELEASE12,
        previous.build13.RELEASE13,
        previous.build14.RELEASE14,
        previous.build15.RELEASE15,
        previous.build16.RELEASE16,
        previous.build17.RELEASE17,
        previous.previous.RELEASE18,
        previous.RELEASE19,
        RELEASE20,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
