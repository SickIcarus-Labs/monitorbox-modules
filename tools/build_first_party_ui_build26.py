#!/usr/bin/env python3
"""Build the Phase-1 wrap-up UI v1.1.14 build 26.

Build 26 keeps rejected physical candidates 24/25 immutable while closing the
remaining Phase-1 shell blockers: persistent Debug access (#289), generation-
coherent static assets / raw-page resilience (#303), and navigation performance
(#304). It remains the same unaccepted v1.1.14 logical patch after build 23.
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
import build_first_party_ui_build25 as previous

UI_VERSION = "1.1.14"
UI_BUILD = 26
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
RELEASE26 = stable.Release(
    build=UI_BUILD,
    certified_sha="p2-phase1-debug-static-coherence-performance",
    version=UI_VERSION,
)
SOURCE_FILES = frozenset(("app-shell.js", "app-shell-final.css"))


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-26 {seam} seam changed: {old[:160]!r}")
    return payload.replace(old, new, 1)


def _replace_region(payload: bytes, start_marker: bytes, end_marker: bytes, replacement: bytes, seam: str) -> bytes:
    start = payload.find(start_marker)
    end = payload.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise SystemExit(f"UI build-26 {seam} region changed")
    return payload[:start] + replacement.rstrip() + b"\n\n" + payload[end:]


def _build26_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build25_assets(root)
    source_root = root / "sources" / "ui" / "1.1.14-build26"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(
            "UI 1.1.14 build-26 delta shape changed: "
            f"missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}"
        )

    shell = (source_root / "app-shell.js").read_bytes()
    if b"UI_GENERATION = '1.1.14-26'" not in shell:
        raise SystemExit("UI build-26 shell generation identity drifted")
    assets["app-shell.js"] = shell
    assets["app-shell.css"] = (
        assets["app-shell.css"].replace(b"1.1.14-25", b"1.1.14-26").rstrip()
        + b"\n\n"
        + (source_root / "app-shell-final.css").read_bytes()
    )
    assets["monitorbox.webmanifest"] = assets["monitorbox.webmanifest"].replace(
        b"1.1.14-25", b"1.1.14-26"
    )
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    payload = _replace_once(
        payload,
        b"Standalone managed MonitorBox UI 1.1.14 build 25.",
        b"Standalone managed MonitorBox UI 1.1.14 build 26.",
        "standalone release identity",
    )
    payload = payload.replace(b"1.1.14-25", b"1.1.14-26")

    generation_helpers = r'''_UI_GENERATION = "1.1.14-26"
_STATIC_REFERENCE_RE = re.compile(
    r'(?P<prefix>(?:src|href)=["\'])/static/(?P<name>[A-Za-z0-9._-]+)(?:\?[^"\']*)?(?P<suffix>["\'])'
)


def _version_managed_assets(markup: str) -> str:
    """Attach this exact UI generation to managed static references.

    HTML remains freshness-checked, while immutable generation URLs let browsers
    reuse coherent CSS/JS without a validation round-trip on every page navigation.
    """
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in ASSETS:
            return match.group(0)
        return (
            f'{match.group("prefix")}/static/{name}?v={_UI_GENERATION}'
            f'{match.group("suffix")}'
        )

    return _STATIC_REFERENCE_RE.sub(replace, markup)


'''.encode("utf-8")
    payload = _replace_once(
        payload,
        b'_APP_SHELL_STYLE = \'<link rel="stylesheet" href="/static/app-shell.css?v=1.1.14-26">\'\n',
        generation_helpers
        + b'_APP_SHELL_STYLE = \'<link rel="stylesheet" href="/static/app-shell.css?v=1.1.14-26">\'\n',
        "generation helper insertion",
    )

    old_shell_tail = b'''        if _APP_SHELL_SCRIPT not in markup and "</body>" in markup:\n            markup = markup.replace("</body>", _APP_SHELL_SCRIPT + "</body>", 1)\n        response.text = markup\n    return response\n'''
    new_shell_tail = b'''        if _APP_SHELL_SCRIPT not in markup and "</body>" in markup:\n            markup = markup.replace("</body>", _APP_SHELL_SCRIPT + "</body>", 1)\n        markup = _version_managed_assets(markup)\n        response.text = markup\n        response.headers["X-MonitorBox-UI-Generation"] = _UI_GENERATION\n    return response\n'''
    payload = _replace_once(
        payload,
        old_shell_tail,
        new_shell_tail,
        "generation-versioned HTML references",
    )

    asset_handler = r'''async def asset(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    content_type = ASSETS.get(name)
    if content_type is None:
        raise web.HTTPNotFound()

    requested_generation = request.query.get("v")
    if requested_generation and requested_generation != _UI_GENERATION:
        # Stale HTML/BFCache references are redirected to the active generation instead
        # of receiving mismatched bytes or a transient 404 during an update boundary.
        raise web.HTTPTemporaryRedirect(
            location=f"/static/{name}?v={_UI_GENERATION}"
        )

    immutable = requested_generation == _UI_GENERATION
    headers = {
        "Cache-Control": (
            "public, max-age=31536000, immutable" if immutable else "no-cache"
        ),
        "X-MonitorBox-UI-Generation": _UI_GENERATION,
    }
    resource = _resource(name)
    if content_type == "image/png":
        return web.Response(
            body=resource.read_bytes(),
            content_type=content_type,
            headers=headers,
        )
    return web.Response(
        text=resource.read_text(encoding="utf-8"),
        content_type=content_type,
        charset="utf-8",
        headers=headers,
    )
'''.encode("utf-8")
    payload = _replace_region(
        payload,
        b"async def asset(request: web.Request) -> web.Response:\n",
        b"async def service_icon(request: web.Request) -> web.Response:\n",
        asset_handler,
        "managed static asset handler",
    )
    return payload


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build26_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 26 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def main() -> None:
    # Builds 24/25 were immutable but rejected physical candidates. Build 26 remains
    # the same logical v1.1.14 patch and follows accepted build23 in catalog history.
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8, build9.RELEASE9, build10.RELEASE10, build11.RELEASE11,
        build12.RELEASE12, build13.RELEASE13, build14.RELEASE14, build15.RELEASE15,
        build16.RELEASE16, build17.RELEASE17, build18.RELEASE18, build19.RELEASE19,
        build20.RELEASE20, accepted.RELEASE23, RELEASE26,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
