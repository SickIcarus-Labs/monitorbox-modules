#!/usr/bin/env python3
"""Extend the certified UI release chain through v1.1.1 build 9.

The historical first-party UI builder remains the byte-stable authority for
builds 2-7. This adapter composes build 8 over build 7 and build 9 over build 8,
adding only generation-safe managed UI deltas.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import build_first_party_ui as stable

BUILD8_VERSION = "1.1.0"
BUILD8 = 8
UI_VERSION = "1.1.1"
UI_BUILD = 9
BUILD8_REFERENCE_SHA = "6f21dd60a7dee3b4545d89572375fa7d518d567c"
BUILD8_SOURCE_BLOBS = {
    "discovery-coverage.js": "6f21dd60a7dee3b4545d89572375fa7d518d567c",
    "discovery-coverage.css": "c6d39f2145943a9991b5626ccdd363245a1e99a4",
}
BUILD9_REFERENCE_SHA = "9160337a8b3a71b86f002ba5f6fbe77106168c1f"
BUILD9_SOURCE_BLOBS = {
    "network-traffic-presentation.js": "9160337a8b3a71b86f002ba5f6fbe77106168c1f",
    "service-hierarchy-interactions.js": "01a2ba843061d46cc9397950bc2f7a1bd8c8ae49",
}
RELEASE8 = stable.Release(build=BUILD8, certified_sha=BUILD8_REFERENCE_SHA, version=BUILD8_VERSION)
RELEASE9 = stable.Release(build=UI_BUILD, certified_sha=BUILD9_REFERENCE_SHA, version=UI_VERSION)
_STABLE_PACKAGE_FILES = stable._package_files


def _build8_assets(root: Path) -> dict[str, bytes]:
    assets = stable._build7_assets(root)
    source_root = root / "sources" / "ui" / "1.1.0-build8"
    expected_names = set(BUILD8_SOURCE_BLOBS)
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise SystemExit(
            "UI 1.1.0 build-8 delta shape changed: "
            f"missing={sorted(expected_names-actual_names)}, extra={sorted(actual_names-expected_names)}"
        )
    for name, expected_blob in BUILD8_SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = stable._git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI 1.1.0 build-8 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        assets[name] = payload
    return assets


def _build9_assets(root: Path) -> dict[str, bytes]:
    assets = _build8_assets(root)
    source_root = root / "sources" / "ui" / "1.1.1-build9"
    expected_names = set(BUILD9_SOURCE_BLOBS)
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise SystemExit(
            "UI 1.1.1 build-9 delta shape changed: "
            f"missing={sorted(expected_names-actual_names)}, extra={sorted(actual_names-expected_names)}"
        )
    for name, expected_blob in BUILD9_SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = stable._git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UI 1.1.1 build-9 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        assets[name] = payload
    return assets


def _managed_build8_adapter() -> bytes:
    return f'''"""Managed MonitorBox UI 1.1.0 build 8 composed over the certified factory UI seed."""

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
        "managed UI 1.1.0 build 8 requires the certified MonitorBox 2.3 factory UI build 2 seed"
    )

_OVERRIDE_TYPES = {{
    "discovery-v22.js": "text/javascript",
    "endpoint-prefill-v22.js": "text/javascript",
    "service-presentation.js": "text/javascript",
    "service-presentation.css": "text/css",
    "discovery-presentation.css": "text/css",
    "discovery-coverage.js": "text/javascript",
    "discovery-coverage.css": "text/css",
}}
_ENDPOINT_PREFILL_SCRIPT = '<script src="/static/endpoint-prefill-v22.js" defer></script>'
_DISCOVERY_PRESENTATION_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-presentation.css">'
_DISCOVERY_COVERAGE_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-coverage.css">'
_DISCOVERY_COVERAGE_SCRIPT = '<script src="/static/discovery-coverage.js" defer></script>'
_DISCOVERY_PRESENTATION_PATHS = frozenset(("/settings/quick-add", "/settings/discover"))


def _override_resource(name):
    return files(__package__).joinpath("assets", name)


@web.middleware
async def managed_discovery_presentation(request, handler):
    response = await handler(request)
    if (
        request.path in _DISCOVERY_PRESENTATION_PATHS
        and isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        markup = response.text
        additions = []
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
    app.middlewares.append(managed_discovery_presentation)
    app.middlewares.append(factory.v22_settings_presentation)
    app.router.add_get("/", factory.dashboard)
    app.router.add_get("/modules", factory.modules)
    app.router.add_get("/api/v2/build", factory.build_identity)
    app.router.add_get("/static/icons/{{name}}", factory.service_icon)
    app.router.add_get("/static/{{name}}", asset)


__all__ = ["install"]
'''.encode("utf-8")


def _managed_build9_adapter() -> bytes:
    return f'''"""Managed MonitorBox UI 1.1.1 build 9 composed over the certified factory UI seed."""

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
        "managed UI 1.1.1 build 9 requires the certified MonitorBox 2.3 factory UI build 2 seed"
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
}}
_ENDPOINT_PREFILL_SCRIPT = '<script src="/static/endpoint-prefill-v22.js" defer></script>'
_DISCOVERY_PRESENTATION_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-presentation.css">'
_DISCOVERY_COVERAGE_STYLESHEET = '<link rel="stylesheet" href="/static/discovery-coverage.css">'
_DISCOVERY_COVERAGE_SCRIPT = '<script src="/static/discovery-coverage.js" defer></script>'
_NETWORK_TRAFFIC_SCRIPT = '<script src="/static/network-traffic-presentation.js" defer></script>'
_SERVICE_HIERARCHY_INTERACTIONS_SCRIPT = '<script src="/static/service-hierarchy-interactions.js" defer></script>'
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
    if release.build not in {BUILD8, UI_BUILD}:
        return _STABLE_PACKAGE_FILES(root, release)
    package = release.import_package
    if release.build == BUILD8:
        result = {f"{package}/__init__.py": _managed_build8_adapter()}
        assets = _build8_assets(root)
    else:
        result = {f"{package}/__init__.py": _managed_build9_adapter()}
        assets = _build9_assets(root)
    for name, payload in assets.items():
        result[f"{package}/assets/{name}"] = payload
    return result


def main() -> None:
    stable.RELEASES = stable.RELEASES + (RELEASE8, RELEASE9)
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
