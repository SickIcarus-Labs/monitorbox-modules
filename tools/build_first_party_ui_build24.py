#!/usr/bin/env python3
"""Extend the accepted standalone UI chain through v1.1.14 build 24.

Build 24 is the P2 Phase-1 presentation release: a shared application shell and
brand (#289/#290), plus compact generic Module Management presentation (#286)
while preserving Core-owned lifecycle actions (#287). Core policy/compatibility
and provider authority remain unchanged.
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
import build_first_party_ui_build23 as previous

UI_VERSION = "1.1.14"
UI_BUILD = 24
RELEASE24 = stable.Release(
    build=UI_BUILD,
    certified_sha="p2-phase1-shared-shell-brand-and-compact-modules",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset((
    "app-shell.css",
    "app-shell.js",
    "monitorbox-192.png",
    "monitorbox-512.png",
    "monitorbox-apple-180.png",
    "monitorbox-glyph.svg",
    "monitorbox-mark.svg",
    "monitorbox-maskable-512.png",
    "monitorbox.webmanifest",
    "modules-compact.css",
    "modules-render.js",
))


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-24 {seam} seam changed: {old[:140]!r}")
    return payload.replace(old, new, 1)


def _build24_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build23_assets(root)
    source_root = root / "sources" / "ui" / "1.1.14-build24"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.14 build-24 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )

    # Replace only the generic repository/module presentation seam. Core remains
    # authoritative for actions, compatibility, lifecycle and repository data.
    base = assets["modules.js"]
    start_marker = b"  function repositoryMutationButton(repository, action) {\n"
    end_marker = b"\n  async function loadModel() {"
    start = base.find(start_marker)
    end = base.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("UI build-24 modules.js no longer exposes the certified presentation seam")
    renderer = (source_root / "modules-render.js").read_bytes().rstrip() + b"\n"
    if b"com.sickicarus.monitorbox." in renderer:
        raise SystemExit("UI build-24 renderer must remain module-ID/provider agnostic")
    assets["modules.js"] = base[:start] + renderer + base[end:]
    assets["modules.css"] = (
        assets["modules.css"].rstrip()
        + b"\n\n/* P2 Phase 1 compact Modules presentation */\n"
        + (source_root / "modules-compact.css").read_bytes()
    )

    # The shared shell and brand are first-class managed assets. HTML returned by
    # Core-rendered settings pages receives them from the managed middleware below.
    for name in SOURCE_FILES - {"modules-render.js", "modules-compact.css"}:
        assets[name] = (source_root / name).read_bytes()
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    payload = _replace_once(
        payload,
        b"Standalone managed MonitorBox UI 1.1.13 build 23.",
        b"Standalone managed MonitorBox UI 1.1.14 build 24.",
        "standalone release identity",
    )

    payload = _replace_once(
        payload,
        b'    "phase6-physical-convergence.css": "text/css",\n}',
        b'    "phase6-physical-convergence.css": "text/css",\n'
        b'    "app-shell.css": "text/css",\n'
        b'    "app-shell.js": "text/javascript",\n'
        b'    "monitorbox-mark.svg": "image/svg+xml",\n'
        b'    "monitorbox-glyph.svg": "image/svg+xml",\n'
        b'    "monitorbox-192.png": "image/png",\n'
        b'    "monitorbox-512.png": "image/png",\n'
        b'    "monitorbox-apple-180.png": "image/png",\n'
        b'    "monitorbox-maskable-512.png": "image/png",\n'
        b'    "monitorbox.webmanifest": "application/manifest+json",\n}',
        "managed asset types",
    )

    middleware = b'''\n_APP_SHELL_STYLE = '<link rel="stylesheet" href="/static/app-shell.css?v=1.1.14-24">'\n_APP_SHELL_SCRIPT = '<script src="/static/app-shell.js?v=1.1.14-24" defer></script>'\n_APPLE_TOUCH_ICON = '<link rel="apple-touch-icon" sizes="180x180" href="/static/monitorbox-apple-180.png?v=1.1.14-24">'\n\n\ndef _uses_app_shell(path):\n    return (\n        path == "/"\n        or path.startswith("/modules")\n        or path.startswith("/settings")\n        or path.startswith("/setup")\n    )\n\n\n@web.middleware\nasync def app_shell_presentation(request, handler):\n    response = await handler(request)\n    if (\n        _uses_app_shell(request.path)\n        and isinstance(response, web.Response)\n        and response.content_type == "text/html"\n        and response.body\n    ):\n        markup = response.text\n        if _APP_SHELL_STYLE not in markup and "</head>" in markup:\n            markup = markup.replace("</head>", _APP_SHELL_STYLE + _APPLE_TOUCH_ICON + "</head>", 1)\n        if _APP_SHELL_SCRIPT not in markup and "</body>" in markup:\n            markup = markup.replace("</body>", _APP_SHELL_SCRIPT + "</body>", 1)\n        response.text = markup\n    return response\n\n'''
    payload = _replace_once(
        payload,
        b"\nasync def asset(request):\n",
        middleware + b"async def asset(request):\n",
        "shared shell middleware",
    )

    payload = _replace_once(
        payload,
        b'    if content_type is None:\n        return await factory.asset(request)\n    return web.Response(\n        text=_override_resource(name).read_text(encoding="utf-8"),\n        content_type=content_type,\n        charset="utf-8",\n        headers={"Cache-Control": "no-cache"},\n    )',
        b'    if content_type is None:\n        return await factory.asset(request)\n    resource = _override_resource(name)\n    if content_type == "image/png":\n        return web.Response(\n            body=resource.read_bytes(),\n            content_type=content_type,\n            headers={"Cache-Control": "no-cache"},\n        )\n    return web.Response(\n        text=resource.read_text(encoding="utf-8"),\n        content_type=content_type,\n        charset="utf-8",\n        headers={"Cache-Control": "no-cache"},\n    )',
        "binary managed assets",
    )
    payload = _replace_once(
        payload,
        b"def install(app):\n",
        b"def install(app):\n    app.middlewares.append(app_shell_presentation)\n",
        "shell install hook",
    )
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build24_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 24 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    # Builds 21/22 were dev-only physical candidates and never became trunk catalog
    # history. Build 24 follows the accepted build23 directly.
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8, build9.RELEASE9, build10.RELEASE10, build11.RELEASE11,
        build12.RELEASE12, build13.RELEASE13, build14.RELEASE14, build15.RELEASE15,
        build16.RELEASE16, build17.RELEASE17, build18.RELEASE18, build19.RELEASE19,
        build20.RELEASE20, previous.RELEASE23, RELEASE24,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
