#!/usr/bin/env python3
"""Build the final Phase-1 UI v1.1.14 build 27 icon correction.

Build 27 preserves the accepted build-26 shell/Modules behavior while correcting
#290's physical home-screen icon field. Build 26 remains immutable; build 27 is
the same still-unaccepted v1.1.14 logical patch after accepted build 23.
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
import build_first_party_ui_build26 as previous

UI_VERSION = "1.1.14"
UI_BUILD = 27
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
RELEASE27 = stable.Release(
    build=UI_BUILD,
    certified_sha="p2-phase1-dark-monitorbox-brand-field",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset((
    "monitorbox-mark.svg",
    "monitorbox-192.png",
    "monitorbox-512.png",
    "monitorbox-apple-180.png",
    "monitorbox-maskable-512.png",
))


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-27 {seam} seam changed: {old[:160]!r}")
    return payload.replace(old, new, 1)


def _build27_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build26_assets(root)
    source_root = root / "sources" / "ui" / "1.1.14-build27"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.14 build-27 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )

    for name in SOURCE_FILES:
        assets[name] = (source_root / name).read_bytes()

    # The package bytes changed, so advance the active generation everywhere the
    # browser can retain a build-26 static reference. The bright health/status green
    # remains presentation state; only brand-field assets change.
    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assets[name] = assets[name].replace(b"1.1.14-26", b"1.1.14-27")
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    payload = _replace_once(
        payload,
        b"Standalone managed MonitorBox UI 1.1.14 build 26.",
        b"Standalone managed MonitorBox UI 1.1.14 build 27.",
        "standalone release identity",
    )
    payload = payload.replace(b"1.1.14-26", b"1.1.14-27")
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build27_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 27 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    # Builds 24/25/26 were immutable but not accepted as the final Phase-1 release.
    # Build 27 remains the same logical v1.1.14 patch and follows accepted build23
    # in catalog history.
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8, build9.RELEASE9, build10.RELEASE10, build11.RELEASE11,
        build12.RELEASE12, build13.RELEASE13, build14.RELEASE14, build15.RELEASE15,
        build16.RELEASE16, build17.RELEASE17, build18.RELEASE18, build19.RELEASE19,
        build20.RELEASE20, accepted.RELEASE23, RELEASE27,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
