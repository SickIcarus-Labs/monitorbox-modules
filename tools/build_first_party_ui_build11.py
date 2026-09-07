#!/usr/bin/env python3
"""Extend the certified UI release chain through standalone v1.1.3 build 11.

Builds 2-10 remain immutable release history and intentionally retain their certified
MonitorBox 2.3 factory-UI dependency. Build 11 is the migration release for pruned Core:
it owns the complete normal-UI application/static payload and contains no import of
``monitorbox.v2.modules.ui``. Core supplies only generic runtime/configuration APIs and
product icon resources.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build10 as previous

UI_VERSION = "1.1.3"
UI_BUILD = 11
RELEASE11 = stable.Release(
    build=UI_BUILD,
    certified_sha="core-prune-standalone-ui",
    version=UI_VERSION,
)
_IMMUTABLE_BUILD10_SHA256 = "149d9907a80c316d45e7060d4c9afb041ce8c6ae07d4888460daaca78079a45e"

# Frozen base assets are byte-identical copies of the last Core-resident normal UI
# immediately before #181 removes that implementation. Build-10 managed deltas are
# layered over this base below, preserving the certified visible behavior while moving
# ownership into the managed package.
BASE_ASSET_BLOBS = {
    "advanced-dirty-state.js": "6860f3583b392851d7bec5bffbbb4cd9943f2a9b",
    "advanced-v22-polish.js": "d0794f3d1d05c773040284a22b508949f6675038",
    "conceptual-presentation.js": "563205ec080de0bd7dbd81233cdb7420c67a3b79",
    "dashboard-widgets.js": "a9e387c9f22b8c947786557c1276d1826212642b",
    "dashboard.css": "1dac1137572474e0bab7b4cf6c2800a38e055a46",
    "dashboard.html": "02a8abf9d911effcc0e15b7d4fe619b5fcc18de9",
    "dashboard.js": "fa7211fa4de1880955953d01553d6cb3da2ba2df",
    "followup-beta-polish.js": "0a8c8d62254353129f8e17e22ddbfab9fada6962",
    "global-debug.css": "38e6c248473eb732cb79bd1ebd937bebf051caae",
    "global-debug.js": "12f4ad30740dadd7bcb7807edb928469019813c0",
    "http-v22-polish.js": "6a3dee5ff82e6783f50e7b72132f16bcb1008805",
    "live-ping.js": "7bc89621603ad6521989f95e6f3792d22e237767",
    "live-telemetry.js": "9abe805d66386c7f07c66db6536a6ea0ee0e4cec",
    "modules.css": "1313503641ff6c8a757269c851e8fb300ff0c3b8",
    "modules.html": "47117fe0615dc7752f3833514624c06d4beebcb0",
    "modules.js": "c259074e82dee065b179792bc3502cf1f23f2d9d",
    "onboarding-v22-acceptance.js": "6f8d332292e45dba16e25d564832a58eddd33747",
    "operation-progress.js": "ae2fd01454d8e0ebe6fa37fa158a16e23e06f83d",
    "policy-ui.js": "15a167852f2811709e1b48592d2c0eeed8ecd69a",
    "quick-add.js": "ee1eea6f65ca47bda9b50b7f4093805ea3276f0b",
    "settings-v22-shell.js": "dc16576d3eb4e8b3224ee4efa488484c6616bd83",
    "v1-beta-hotfix.css": "863280d0cfce6a6b29392b20eb592c7beb23cd8b",
    "v1-beta-hotfix.js": "45f9f633cb5fd673f0e6061bfe3b58925d1cfed9",
    "v1-beta-polish.css": "f56d2a146dfa04b13417446f1fcb8cc929216209",
    "v1-beta-polish.js": "dcc7da4553a319f636a7ef3f1f88b44e96dceac7",
    "v1-detail-parity.css": "591c1767ce49bbc0fe00f14e7996d2f417b8d379",
    "v1-detail-parity.js": "cdc0dfece993dedcf3c6a0cb32347b3c1583a5f9",
    "v1-global-diagnostics.js": "fe15b31ce9f06bb795c3ed91c00c2073e803b162",
    "v1-parity.css": "a80d62127b08921b1e9098e37fadc35b289c767d",
    "v1-parity.js": "48c8373659982e71cafd21c58284263ebaa66f8c",
    "v22-shell.css": "4d084fce04e7d6a5b57bd2c0fd7d199095126d57",
    "v22-shell.js": "07a9dfd434698051be4c0fd0b17363023bfbbfda",
    "workspace-finish.js": "8048b8e95fe394ec4f33c9ab0b748b3c0646c803",
    "workspace-state.js": "5ce4811b8864582d720b4f492c2abc3b72181063",
}


def _standalone_application() -> bytes:
    return r'''"""Standalone managed MonitorBox UI 1.1.3 build 11.

Owns the complete normal UI after the Core factory implementation is retired.
"""

from __future__ import annotations

import re
from html import escape as html_escape
from importlib.resources import files

from aiohttp import web

from monitorbox.v2.build_info import current_build_identity


ASSETS = {
    "dashboard.css": "text/css",
    "service-presentation.css": "text/css",
    "v1-parity.css": "text/css",
    "v1-detail-parity.css": "text/css",
    "v1-beta-polish.css": "text/css",
    "v1-beta-hotfix.css": "text/css",
    "global-debug.css": "text/css",
    "v22-shell.css": "text/css",
    "modules.css": "text/css",
    "dashboard.js": "text/javascript",
    "conceptual-presentation.js": "text/javascript",
    "service-presentation.js": "text/javascript",
    "v1-parity.js": "text/javascript",
    "v1-detail-parity.js": "text/javascript",
    "v1-global-diagnostics.js": "text/javascript",
    "v1-beta-polish.js": "text/javascript",
    "v1-beta-hotfix.js": "text/javascript",
    "global-debug.js": "text/javascript",
    "operation-progress.js": "text/javascript",
    "live-ping.js": "text/javascript",
    "live-telemetry.js": "text/javascript",
    "dashboard-widgets.js": "text/javascript",
    "policy-ui.js": "text/javascript",
    "quick-add.js": "text/javascript",
    "v22-shell.js": "text/javascript",
    "workspace-state.js": "text/javascript",
    "workspace-finish.js": "text/javascript",
    "discovery-v22.js": "text/javascript",
    "advanced-v22-polish.js": "text/javascript",
    "advanced-dirty-state.js": "text/javascript",
    "http-v22-polish.js": "text/javascript",
    "settings-v22-shell.js": "text/javascript",
    "followup-beta-polish.js": "text/javascript",
    "onboarding-v22-acceptance.js": "text/javascript",
    "modules.js": "text/javascript",
    "endpoint-prefill-v22.js": "text/javascript",
    "discovery-presentation.css": "text/css",
    "discovery-coverage.js": "text/javascript",
    "discovery-coverage.css": "text/css",
    "network-traffic-presentation.js": "text/javascript",
    "service-hierarchy-interactions.js": "text/javascript",
    "service-hierarchy-physical-fixes.js": "text/javascript",
}
SERVICE_ICON_RE = re.compile(r"^[a-z0-9_-]+\.svg$")
_ADVANCED_POLISH_SCRIPT = '<script src="/static/advanced-v22-polish.js" defer></script>'
_ADVANCED_DIRTY_STATE_SCRIPT = '<script src="/static/advanced-dirty-state.js" defer></script>'
_HTTP_POLISH_SCRIPT = '<script src="/static/http-v22-polish.js" defer></script>'
_SETTINGS_SHELL_SCRIPT = '<script src="/static/settings-v22-shell.js" defer></script>'
_FOLLOWUP_BETA_POLISH_SCRIPT = '<script src="/static/followup-beta-polish.js" defer></script>'
_ONBOARDING_ACCEPTANCE_SCRIPT = '<script src="/static/onboarding-v22-acceptance.js" defer></script>'
_ENDPOINT_PREFILL_SCRIPT = '<script src="/static/endpoint-prefill-v22.js" defer></script>'
_DISCOVERY_PRESENTATION_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-presentation.css">'
_DISCOVERY_COVERAGE_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-coverage.css">'
_DISCOVERY_COVERAGE_SCRIPT = '<script src="/static/discovery-coverage.js" defer></script>'
_NETWORK_TRAFFIC_SCRIPT = '<script src="/static/network-traffic-presentation.js" defer></script>'
_SERVICE_HIERARCHY_INTERACTIONS_SCRIPT = '<script src="/static/service-hierarchy-interactions.js" defer></script>'
_SERVICE_HIERARCHY_PHYSICAL_SCRIPT = '<script src="/static/service-hierarchy-physical-fixes.js" defer></script>'
_DISCOVERY_PRESENTATION_PATHS = frozenset(("/settings/quick-add", "/settings/discover"))


def _resource(name: str):
    return files(__package__).joinpath("assets", name)


def _service_icon_resource(name: str):
    if not SERVICE_ICON_RE.fullmatch(name):
        return None
    resource = files("monitorbox").joinpath("static", "icons", name)
    return resource if resource.is_file() else None


@web.middleware
async def v22_settings_presentation(request: web.Request, handler):
    response = await handler(request)
    if (
        isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        markup = response.text
        scripts: list[str] = []
        if request.path == "/settings" or request.path.startswith("/settings/"):
            scripts.append(_FOLLOWUP_BETA_POLISH_SCRIPT)
        if request.path.startswith("/settings/"):
            scripts.append(_SETTINGS_SHELL_SCRIPT)
        if request.path == "/settings/advanced":
            scripts.extend((_ADVANCED_POLISH_SCRIPT, _ADVANCED_DIRTY_STATE_SCRIPT))
        elif request.path == "/settings/quick-add":
            scripts.append(_HTTP_POLISH_SCRIPT)
        if request.path in {
            "/settings/quick-add",
            "/settings/advanced/rerun-first-launch",
        }:
            scripts.append(_ONBOARDING_ACCEPTANCE_SCRIPT)
        if scripts and "</body>" in markup:
            missing = [script for script in scripts if script not in markup]
            if missing:
                response.text = markup.replace("</body>", "".join(missing) + "</body>")
    return response


@web.middleware
async def managed_ui_presentation(request: web.Request, handler):
    response = await handler(request)
    if not (
        isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        return response
    markup = response.text
    additions: list[str] = []
    if request.path == "/":
        if _NETWORK_TRAFFIC_SCRIPT not in markup:
            additions.append(_NETWORK_TRAFFIC_SCRIPT)
        if _SERVICE_HIERARCHY_INTERACTIONS_SCRIPT not in markup:
            additions.append(_SERVICE_HIERARCHY_INTERACTIONS_SCRIPT)
        if _SERVICE_HIERARCHY_PHYSICAL_SCRIPT not in markup:
            additions.append(_SERVICE_HIERARCHY_PHYSICAL_SCRIPT)
    elif request.path in _DISCOVERY_PRESENTATION_PATHS:
        if _DISCOVERY_PRESENTATION_STYLESHEET not in markup:
            additions.append(_DISCOVERY_PRESENTATION_STYLESHEET)
        if request.path == "/settings/discover":
            if _DISCOVERY_COVERAGE_STYLESHEET not in markup:
                additions.append(_DISCOVERY_COVERAGE_STYLESHEET)
            if _DISCOVERY_COVERAGE_SCRIPT not in markup:
                additions.append(_DISCOVERY_COVERAGE_SCRIPT)
        if request.path == "/settings/quick-add" and _ENDPOINT_PREFILL_SCRIPT not in markup:
            additions.append(_ENDPOINT_PREFILL_SCRIPT)
    if additions and "</body>" in markup:
        response.text = markup.replace("</body>", "".join(additions) + "</body>")
    return response


async def dashboard(_: web.Request) -> web.Response:
    identity = current_build_identity()
    markup = _resource("dashboard.html").read_text(encoding="utf-8")
    markup = markup.replace("__MONITORBOX_BUILD_LABEL__", html_escape(identity.display))
    return web.Response(
        text=markup,
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def modules(_: web.Request) -> web.Response:
    identity = current_build_identity()
    markup = _resource("modules.html").read_text(encoding="utf-8")
    markup = markup.replace("__MONITORBOX_BUILD_LABEL__", html_escape(identity.display))
    return web.Response(
        text=markup,
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def build_identity(_: web.Request) -> web.Response:
    return web.json_response(current_build_identity().as_dict())


async def asset(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    content_type = ASSETS.get(name)
    if content_type is None:
        raise web.HTTPNotFound()
    return web.Response(
        text=_resource(name).read_text(encoding="utf-8"),
        content_type=content_type,
        charset="utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def service_icon(request: web.Request) -> web.Response:
    resource = _service_icon_resource(request.match_info["name"])
    if resource is None:
        raise web.HTTPNotFound()
    return web.Response(
        body=resource.read_bytes(),
        content_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


def install(app: web.Application) -> None:
    # aiohttp composes middlewares in reverse list order. Preserve the certified
    # managed-build-10 layering: managed presentation wraps the original v2.2 shell.
    app.middlewares.append(managed_ui_presentation)
    app.middlewares.append(v22_settings_presentation)
    app.router.add_get("/", dashboard)
    app.router.add_get("/modules", modules)
    app.router.add_get("/api/v2/build", build_identity)
    app.router.add_get("/static/icons/{name}", service_icon)
    app.router.add_get("/static/{name}", asset)


__all__ = ["install"]
'''.encode("utf-8")


def _base_assets(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "ui" / "1.1.3-build11" / "base"
    expected = set(BASE_ASSET_BLOBS)
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != expected:
        raise SystemExit(
            "UI 1.1.3 build-11 standalone base shape changed: "
            f"missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )
    assets: dict[str, bytes] = {}
    for name, expected_blob in BASE_ASSET_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = stable._git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI 1.1.3 build-11 base drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        assets[name] = payload
    return assets


def _build11_assets(root: Path) -> dict[str, bytes]:
    assets = _base_assets(root)
    # Retain every managed delta through 1.1.2 build 10. This intentionally
    # replaces the frozen base discovery/service assets and adds build-8/9/10 assets.
    assets.update(previous._build10_assets(root))
    return assets


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build11_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit(
            "standalone UI build 11 unexpectedly references retired Core UI authority: "
            + ", ".join(sorted(offenders))
        )
    return files


def _requested_output_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args, _ = parser.parse_known_args()
    return args.output_dir


def _assert_immutable(path: Path, expected: str, label: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(
            f"immutable {label} package drift: expected {expected}, got {actual}"
        )


def main() -> None:
    output_dir = _requested_output_dir()
    stable.RELEASES = stable.RELEASES + (
        previous.previous.RELEASE8,
        previous.previous.RELEASE9,
        previous.RELEASE10,
        RELEASE11,
    )
    stable._package_files = _package_files
    stable.main()

    build10 = output_dir / f"{stable.MODULE_ID}-{previous.RELEASE10.version}-build{previous.RELEASE10.build}.zip"
    _assert_immutable(build10, _IMMUTABLE_BUILD10_SHA256, "UI 1.1.2 build-10")


if __name__ == "__main__":
    main()
