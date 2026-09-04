#!/usr/bin/env python3
"""Extend the certified UI release chain through v1.1.2 build 10.

Builds 2-9 remain immutable release history. This adapter composes build 10
over the certified build-9 asset set and adds only the physical Broad Leaf
hierarchy correction for monitorbox#206/#207.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_current as previous

UI_VERSION = "1.1.2"
UI_BUILD = 10
BUILD10_REFERENCE_SHA = "58dc3686ea92369dc5646d7a84cf07bca6e1d0e9"
BUILD10_SOURCE_BLOBS = {
    "service-hierarchy-physical-fixes.js": "58dc3686ea92369dc5646d7a84cf07bca6e1d0e9",
}
RELEASE10 = stable.Release(
    build=UI_BUILD,
    certified_sha=BUILD10_REFERENCE_SHA,
    version=UI_VERSION,
)
_IMMUTABLE_BUILD9_SHA256 = "ba67dd81b8559a4cd26a33fcb9a85e112f9c72bcd85f93e336e2ff92460daa66"


def _build10_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build9_assets(root)
    source_root = root / "sources" / "ui" / "1.1.2-build10"
    expected_names = set(BUILD10_SOURCE_BLOBS)
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise SystemExit(
            "UI 1.1.2 build-10 delta shape changed: "
            f"missing={sorted(expected_names-actual_names)}, extra={sorted(actual_names-expected_names)}"
        )
    for name, expected_blob in BUILD10_SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = stable._git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI 1.1.2 build-10 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        assets[name] = payload
    return assets


def _managed_build10_adapter() -> bytes:
    return f'''"""Managed MonitorBox UI 1.1.2 build 10 composed over the certified factory UI seed."""

from importlib.resources import files

from aiohttp import web
from monitorbox.v2.modules.ui import (
    MODULE_BUILD as FACTORY_BUILD,
    MODULE_ID as FACTORY_ID,
    MODULE_VERSION as FACTORY_VERSION,
)
from monitorbox.v2.modules.ui import application as factory

_EXPECTED = ({stable.MODULE_ID!r}, {stable.MODULE_VERSION!r}, {stable.FACTORY_BUILD})
if (FACTORY_ID, FACTORY_VERSION, FACTORY_BUILD) != _EXPECTED:
    raise ImportError(
        "managed UI 1.1.2 build 10 requires the certified MonitorBox 2.3 factory UI build 2 seed"
    )

_OVERRIDE_TYPES = {{
    "discovery-v22.js": "text/javascript",
    "endpoint-prefill-v22.js": "text/javascript",
    "service-presentation.js": "text/javascript",
    "service-presentation.css": "text/css",
    "discovery-presentation.css": "text/css",
    "discovery-coverage.js": "text/javascript",
    "discovery-coverage.css": "text/css",
    "network-traffic-presentation.js": "text/javascript",
    "service-hierarchy-interactions.js": "text/javascript",
    "service-hierarchy-physical-fixes.js": "text/javascript",
}}
_ENDPOINT_PREFILL_SCRIPT = '<script src="/static/endpoint-prefill-v22.js" defer></script>'
_DISCOVERY_PRESENTATION_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-presentation.css">'
_DISCOVERY_COVERAGE_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-coverage.css">'
_DISCOVERY_COVERAGE_SCRIPT = '<script src="/static/discovery-coverage.js" defer></script>'
_NETWORK_TRAFFIC_SCRIPT = '<script src="/static/network-traffic-presentation.js" defer></script>'
_SERVICE_HIERARCHY_INTERACTIONS_SCRIPT = '<script src="/static/service-hierarchy-interactions.js" defer></script>'
_SERVICE_HIERARCHY_PHYSICAL_SCRIPT = '<script src="/static/service-hierarchy-physical-fixes.js" defer></script>'
_DISCOVERY_PRESENTATION_PATHS = frozenset(("/settings/quick-add", "/settings/discover"))


def _override_resource(name):
    return files(__package__).joinpath("assets", name)


@web.middleware
async def managed_ui_presentation(request, handler):
    response = await handler(request)
    if not (
        isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        return response
    markup = response.text
    additions = []
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


async def asset(request):
    name = request.match_info["name"]
    content_type = _OVERRIDE_TYPES.get(name)
    if content_type is None:
        return await factory.asset(request)
    return web.Response(
        text=_override_resource(name).read_text(encoding="utf-8"),
        content_type=content_type,
        charset="utf-8",
        headers={{"Cache-Control": "no-cache"}},
    )


def install(app):
    app.middlewares.append(managed_ui_presentation)
    app.middlewares.append(factory.v22_settings_presentation)
    app.router.add_get("/", factory.dashboard)
    app.router.add_get("/modules", factory.modules)
    app.router.add_get("/api/v2/build", factory.build_identity)
    app.router.add_get("/static/icons/{{name}}", factory.service_icon)
    app.router.add_get("/static/{{name}}", asset)


__all__ = ["install"]
'''.encode("utf-8")


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    result = {f"{package}/__init__.py": _managed_build10_adapter()}
    for name, payload in _build10_assets(root).items():
        result[f"{package}/assets/{name}"] = payload
    return result


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
        previous.RELEASE8,
        previous.RELEASE9,
        RELEASE10,
    )
    stable._package_files = _package_files
    stable.main()

    build3 = output_dir / f"{stable.MODULE_ID}-{stable.MODULE_VERSION}-build3.zip"
    _assert_immutable(
        build3,
        previous._IMMUTABLE_BUILD3_SHA256,
        "UI build-3",
    )
    build9 = (
        output_dir
        / f"{stable.MODULE_ID}-{previous.RELEASE9.version}-build{previous.RELEASE9.build}.zip"
    )
    _assert_immutable(build9, _IMMUTABLE_BUILD9_SHA256, "UI 1.1.1 build-9")


if __name__ == "__main__":
    main()
