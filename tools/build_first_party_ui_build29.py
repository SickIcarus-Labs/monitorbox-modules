#!/usr/bin/env python3
"""Build P2 Phase-2 physical-correction UI v1.1.16 build 29.

Build 29 supersedes failed dev build 28 after Broad Leaf physical review:
- #297 renders only bounded normalized recommendation explanations and consumes
  provider relationship evidence instead of presenting provenance as a reason;
- #209 removes provider-covered adoption/promotion as a second monitoring state;
- #302 resolves the UI module description on the actual Modules runtime surface;
- #268 is unchanged after physical PASS.
"""

from __future__ import annotations

import hashlib
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
import build_first_party_ui_build27 as build27
import build_first_party_ui_build28 as previous

UI_VERSION = "1.1.16"
UI_BUILD = 29
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
RELEASE29 = stable.Release(
    build=UI_BUILD,
    certified_sha="p2-phase2-physical-corrections",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("phase2-physical-fixes.js",))
SOURCE_BLOBS = {
    "phase2-physical-fixes.js": "e89df520d659deeb18dc72d7d1b2c2a3291275c1",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-29 {seam} seam changed: {old[:160]!r}")
    return payload.replace(old, new, 1)


def _build29_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build28_assets(root)
    source_root = root / "sources" / "ui" / "1.1.16-build29"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.16 build-29 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )
    for name, expected in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        if _git_blob_sha(payload) != expected:
            raise SystemExit(f"UI build-29 source blob changed for {name}")

    assets["discovery-coverage.js"] = (
        assets["discovery-coverage.js"].rstrip()
        + b"\n\n"
        + (source_root / "phase2-physical-fixes.js").read_bytes()
    )

    assets["modules.js"] = _replace_once(
        assets["modules.js"],
        b'description.textContent = text(module.description, "No module description is published.");',
        b'description.textContent = text(module.description || module.installed?.description || module.available?.description || module.installed?.manifest?.description || module.available?.manifest?.description, module.module_id === "com.sickicarus.monitorbox.ui" ? "MonitorBox web interface, shared application shell, and operator presentation." : "No module description is published.");',
        "runtime module description",
    )

    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assets[name] = assets[name].replace(b"1.1.15-28", b"1.1.16-29")
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    payload = _replace_once(
        payload,
        b"Standalone managed MonitorBox UI 1.1.15 build 28.",
        b"Standalone managed MonitorBox UI 1.1.16 build 29.",
        "standalone release identity",
    )
    return payload.replace(b"1.1.15-28", b"1.1.16-29")


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build29_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 29 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8, build9.RELEASE9, build10.RELEASE10, build11.RELEASE11,
        build12.RELEASE12, build13.RELEASE13, build14.RELEASE14, build15.RELEASE15,
        build16.RELEASE16, build17.RELEASE17, build18.RELEASE18, build19.RELEASE19,
        build20.RELEASE20, accepted.RELEASE23, build27.RELEASE27, previous.RELEASE28,
        RELEASE29,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
