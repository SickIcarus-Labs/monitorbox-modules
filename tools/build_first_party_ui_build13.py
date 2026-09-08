#!/usr/bin/env python3
"""Extend the standalone managed UI chain through v1.1.5 build 13.

Build 13 is a presentation-only September 7 P1 Phase-2 release. It preserves
build-12 behavior and adds one late-loading asset for Quick Add Review truth and
provider-derived display-label cleanup. Core and provider identity remain
unchanged; existing hierarchy URL safety remains authoritative.
"""

from __future__ import annotations

from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_current as build9
import build_first_party_ui_build10 as build10
import build_first_party_ui_build11 as build11
import build_first_party_ui_build12 as previous

UI_VERSION = "1.1.5"
UI_BUILD = 13
RELEASE13 = stable.Release(
    build=UI_BUILD,
    certified_sha="phase2-review-display-truth",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("phase2-p1.js",))


def _build13_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build12_assets(root)
    source_root = root / "sources" / "ui" / "1.1.5-build13"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.5 build-13 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )
    assets["phase2-p1.js"] = (source_root / "phase2-p1.js").read_bytes()
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    replacements = (
        (
            b"Standalone managed MonitorBox UI 1.1.4 build 12.",
            b"Standalone managed MonitorBox UI 1.1.5 build 13.",
        ),
        (
            b'    "service-hierarchy-physical-fixes.js": "text/javascript",\n}',
            b'    "service-hierarchy-physical-fixes.js": "text/javascript",\n'
            b'    "phase2-p1.js": "text/javascript",\n}',
        ),
        (
            b'_SERVICE_HIERARCHY_PHYSICAL_SCRIPT = \'<script src="/static/service-hierarchy-physical-fixes.js" defer></script>\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
            b'_SERVICE_HIERARCHY_PHYSICAL_SCRIPT = \'<script src="/static/service-hierarchy-physical-fixes.js" defer></script>\'\n'
            b'_PHASE2_P1_SCRIPT = \'<script src="/static/phase2-p1.js" defer></script>\'\n'
            b'_DISCOVERY_PRESENTATION_PATHS =',
        ),
        (
            b'    if additions and "</body>" in markup:\n'
            b'        response.text = markup.replace("</body>", "".join(additions) + "</body>")',
            b'    if request.path in {"/", "/settings/quick-add", "/settings/discover"} and _PHASE2_P1_SCRIPT not in markup:\n'
            b'        additions.append(_PHASE2_P1_SCRIPT)\n'
            b'    if additions and "</body>" in markup:\n'
            b'        response.text = markup.replace("</body>", "".join(additions) + "</body>")',
        ),
    )
    for old, new in replacements:
        if payload.count(old) != 1:
            raise SystemExit(f"UI build-13 standalone seam changed: {old[:80]!r}")
        payload = payload.replace(old, new, 1)
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build13_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 13 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    # Name the historical release owners explicitly instead of depending on the
    # implementation-module import chain. That chain is not a public release API
    # and changed when build 10 switched its predecessor module name.
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8,
        build9.RELEASE9,
        build10.RELEASE10,
        build11.RELEASE11,
        previous.RELEASE12,
        RELEASE13,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
