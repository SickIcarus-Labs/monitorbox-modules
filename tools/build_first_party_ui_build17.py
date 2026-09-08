#!/usr/bin/env python3
"""Extend the standalone managed UI chain through v1.1.9 build 17.

Build 17 supersedes physically rejected dev-only build 16. It preserves accepted
Phase-2 behavior while adding one final fail-closed #206 reconciliation tier for
a unique semantic canonical/workload match when the canonical side already owns
an explicit safe HTTP(S) URL. Core remains independent.
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
import build_first_party_ui_build16 as previous

UI_VERSION = "1.1.9"
UI_BUILD = 17
RELEASE17 = stable.Release(
    build=UI_BUILD,
    certified_sha="phase2-unique-semantic-service-url-reconciliation",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("phase2-physical-repairs4.js",))


def _build17_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build16_assets(root)
    source_root = root / "sources" / "ui" / "1.1.9-build17"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.9 build-17 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )
    assets["phase2-physical-repairs4.js"] = (
        source_root / "phase2-physical-repairs4.js"
    ).read_bytes()
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    replacements = (
        (
            b"Standalone managed MonitorBox UI 1.1.8 build 16.",
            b"Standalone managed MonitorBox UI 1.1.9 build 17.",
        ),
        (
            b'    "phase2-physical-repairs3.js": "text/javascript",\n}',
            b'    "phase2-physical-repairs3.js": "text/javascript",\n'
            b'    "phase2-physical-repairs4.js": "text/javascript",\n}',
        ),
        (
            b'_PHASE2_PHYSICAL3_SCRIPT = \'<script src="/static/phase2-physical-repairs3.js" defer></script>\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
            b'_PHASE2_PHYSICAL3_SCRIPT = \'<script src="/static/phase2-physical-repairs3.js" defer></script>\'\n'
            b'_PHASE2_PHYSICAL4_SCRIPT = \'<script src="/static/phase2-physical-repairs4.js" defer></script>\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
        ),
        (
            b'    if request.path == "/settings/advanced" and _PHASE2_PHYSICAL3_SCRIPT not in markup:\n'
            b'        additions.append(_PHASE2_PHYSICAL3_SCRIPT)\n'
            b'    if additions and "</body>" in markup:\n',
            b'    if request.path == "/settings/advanced" and _PHASE2_PHYSICAL3_SCRIPT not in markup:\n'
            b'        additions.append(_PHASE2_PHYSICAL3_SCRIPT)\n'
            b'    if request.path == "/" and _PHASE2_PHYSICAL4_SCRIPT not in markup:\n'
            b'        additions.append(_PHASE2_PHYSICAL4_SCRIPT)\n'
            b'    if additions and "</body>" in markup:\n',
        ),
    )
    for old, new in replacements:
        if payload.count(old) != 1:
            raise SystemExit(f"UI build-17 standalone seam changed: {old[:100]!r}")
        payload = payload.replace(old, new, 1)
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build17_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 17 unexpectedly references retired Core UI authority: "
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
        previous.RELEASE16,
        RELEASE17,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
