#!/usr/bin/env python3
"""Extend the standalone managed UI chain through v1.1.4 build 12.

Build 12 is a presentation-only Module Manager release. It preserves the complete
standalone build-11 payload and replaces only the module release-identity renderer,
plus a bounded responsive style delta. Core remains the lifecycle/compatibility
authority; this package only presents the generic module-management API.
"""

from __future__ import annotations

from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build11 as previous

UI_VERSION = "1.1.4"
UI_BUILD = 12
RELEASE12 = stable.Release(
    build=UI_BUILD,
    certified_sha="module-manager-semver-primary",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("modules-render.js", "modules-semver.css"))


def _build12_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build11_assets(root)
    source_root = root / "sources" / "ui" / "1.1.4-build12"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.4 build-12 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )

    base = assets["modules.js"].decode("utf-8")
    start_marker = "  function renderModules() {\n"
    end_marker = "\n  async function loadModel() {"
    start = base.find(start_marker)
    end = base.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("UI build-11 modules.js no longer exposes the certified renderModules seam")

    replacement = (source_root / "modules-render.js").read_text(encoding="utf-8").rstrip() + "\n"
    if "com.sickicarus.monitorbox." in replacement:
        raise SystemExit("UI build-12 renderer must remain module-ID agnostic")
    assets["modules.js"] = (base[:start] + replacement + base[end:]).encode("utf-8")

    style = (source_root / "modules-semver.css").read_bytes()
    assets["modules.css"] = assets["modules.css"].rstrip() + b"\n\n" + style
    return assets


def _standalone_application() -> bytes:
    return previous._standalone_application().replace(
        b"Standalone managed MonitorBox UI 1.1.3 build 11.",
        b"Standalone managed MonitorBox UI 1.1.4 build 12.",
        1,
    )


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build12_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 12 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    stable.RELEASES = stable.RELEASES + (
        previous.previous.previous.RELEASE8,
        previous.previous.previous.RELEASE9,
        previous.previous.RELEASE10,
        previous.RELEASE11,
        RELEASE12,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
