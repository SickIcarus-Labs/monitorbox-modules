#!/usr/bin/env python3
"""Build P2 Phase-2 UI v1.1.15 build 28.

Build 28 is a bounded normal-UI polish release for #297, #209, and #268.
It preserves the accepted build-27 shell and signed module description while:
- splitting new Discoveries into Recommended / Other review subgroups;
- normalizing no-op/action copy without changing staged-change semantics; and
- sorting Quick Add Connection cards within their existing groups only.
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
import build_first_party_ui_build27 as previous

UI_VERSION = "1.1.15"
UI_BUILD = 28
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
RELEASE28 = stable.Release(
    build=UI_BUILD,
    certified_sha="p2-phase2-discovery-review-connection-order",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset((
    "discovery-coverage.js",
    "phase2-p2-connections.js",
    "phase2-p2.css",
))


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-28 {seam} seam changed: {old[:160]!r}")
    return payload.replace(old, new, 1)


def _build28_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build27_assets(root)
    source_root = root / "sources" / "ui" / "1.1.15-build28"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.15 build-28 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )

    # Replace the inherited coverage renderer in-place so its private coverage and
    # staged-change authority remains singular. This is not a second renderer.
    assets["discovery-coverage.js"] = (source_root / "discovery-coverage.js").read_bytes()
    assets["discovery-coverage.css"] = (
        assets["discovery-coverage.css"].rstrip()
        + b"\n\n"
        + (source_root / "phase2-p2.css").read_bytes()
    )

    # Quick Add already owns grouping and live card identity. Append a presentation-
    # only wrapper that moves those same cards within each existing group.
    assets["onboarding-v22-acceptance.js"] = (
        assets["onboarding-v22-acceptance.js"].rstrip()
        + b"\n"
        + (source_root / "phase2-p2-connections.js").read_bytes()
    )

    # Advance all active generation references while retaining build-27 shell bytes.
    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assets[name] = assets[name].replace(b"1.1.14-27", b"1.1.15-28")
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    payload = _replace_once(
        payload,
        b"Standalone managed MonitorBox UI 1.1.14 build 27.",
        b"Standalone managed MonitorBox UI 1.1.15 build 28.",
        "standalone release identity",
    )
    payload = payload.replace(b"1.1.14-27", b"1.1.15-28")
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build28_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 28 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8, build9.RELEASE9, build10.RELEASE10, build11.RELEASE11,
        build12.RELEASE12, build13.RELEASE13, build14.RELEASE14, build15.RELEASE15,
        build16.RELEASE16, build17.RELEASE17, build18.RELEASE18, build19.RELEASE19,
        build20.RELEASE20, accepted.RELEASE23, previous.RELEASE27, RELEASE28,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
