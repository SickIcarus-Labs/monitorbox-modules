#!/usr/bin/env python3
"""Build UI v1.1.14 build 25 from the rejected build-24 physical candidate.

Build 25 keeps build 24 immutable and carries Broad Leaf physical-review
corrections for the same unaccepted v1.1.14 patch: visible disclosures, aligned
module summary columns, compact healthy authentication, concise repository
channels, and one global shell navigation affordance.
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
import build_first_party_ui_build18 as build18
import build_first_party_ui_build19 as build19
import build_first_party_ui_build20 as build20
import build_first_party_ui_build23 as accepted
import build_first_party_ui_build24 as previous

UI_VERSION = "1.1.14"
UI_BUILD = 25
RELEASE25 = stable.Release(
    build=UI_BUILD,
    certified_sha="p2-phase1-broadleaf-physical-polish",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset((
    "app-shell-actions.js",
    "modules-polish.css",
    "modules-render.js",
))


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-25 {seam} seam changed: {old[:140]!r}")
    return payload.replace(old, new, 1)


def _replace_region(payload: bytes, start_marker: bytes, end_marker: bytes, replacement: bytes, seam: str) -> bytes:
    start = payload.find(start_marker)
    end = payload.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise SystemExit(f"UI build-25 {seam} region changed")
    return payload[:start] + replacement.rstrip() + b"\n\n" + payload[end:]


def _build25_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build24_assets(root)
    source_root = root / "sources" / "ui" / "1.1.14-build25"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.14 build-25 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )

    renderer = (source_root / "modules-render.js").read_bytes()
    if b"com.sickicarus.monitorbox." in renderer:
        raise SystemExit("UI build-25 renderer must remain module-ID/provider agnostic")
    assets["modules.js"] = _replace_region(
        assets["modules.js"],
        b"  function repositoryMutationButton(repository, action) {\n",
        b"  async function loadModel() {",
        renderer,
        "Modules presentation",
    )
    assets["modules.css"] = (
        assets["modules.css"].rstrip()
        + b"\n\n/* P2 Phase 1 Broad Leaf physical polish */\n"
        + (source_root / "modules-polish.css").read_bytes()
    )

    shell_actions = (source_root / "app-shell-actions.js").read_bytes()
    assets["app-shell.js"] = _replace_region(
        assets["app-shell.js"],
        b"  function pageActionsFromLegacy() {\n",
        b"  function createShell(meta) {",
        shell_actions,
        "legacy shell-action migration",
    )

    # Same logical v1.1.14 patch, new immutable physical candidate build. Advance the
    # cache-busting build identity so Safari cannot reuse rejected build-24 shell bytes.
    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assets[name] = assets[name].replace(b"1.1.14-24", b"1.1.14-25")
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    payload = _replace_once(
        payload,
        b"Standalone managed MonitorBox UI 1.1.14 build 24.",
        b"Standalone managed MonitorBox UI 1.1.14 build 25.",
        "standalone release identity",
    )
    payload = payload.replace(b"1.1.14-24", b"1.1.14-25")
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build25_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 25 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    # Build 24 was an immutable dev/physical candidate but was rejected before
    # acceptance. Build 25 remains the same logical v1.1.14 patch and follows the
    # accepted build23 in catalog history while inheriting build24 implementation.
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8, build9.RELEASE9, build10.RELEASE10, build11.RELEASE11,
        build12.RELEASE12, build13.RELEASE13, build14.RELEASE14, build15.RELEASE15,
        build16.RELEASE16, build17.RELEASE17, build18.RELEASE18, build19.RELEASE19,
        build20.RELEASE20, accepted.RELEASE23, RELEASE25,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
