#!/usr/bin/env python3
"""Extend the certified UI release chain through v1.1.0 build 8.

The historical first-party UI builder remains the byte-stable authority for
builds 2-7. This adapter composes build 8 over build 7 and adds only the generic
monitoring-coverage/action presentation assets required by monitorbox#161/#200.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files
from pathlib import Path

import build_first_party_ui as stable

UI_VERSION = "1.1.0"
UI_BUILD = 8
BUILD8_REFERENCE_SHA = "6f21dd60a7dee3b4545d89572375fa7d518d567c"
BUILD8_SOURCE_BLOBS = {
    "discovery-coverage.js": "6f21dd60a7dee3b4545d89572375fa7d518d567c",
    "discovery-coverage.css": "c6d39f2145943a9991b5626ccdd363245a1e99a4",
}
RELEASE8 = stable.Release(build=UI_BUILD, certified_sha=BUILD8_REFERENCE_SHA, version=UI_VERSION)
_STABLE_PACKAGE_FILES = stable._package_files
_IMMUTABLE_BUILD3_SHA256 = "01220c177bc380c00aa731b738b2804e68aa1e4e6db1598a4a1da10be53304ed"


def _immutable_build3_adapter() -> bytes:
    """Reproduce the originally published UI build-3 adapter byte-for-byte."""
    return f'''"""Managed MonitorBox UI build 3 composed over the certified factory UI seed."""

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
        "managed UI build 3 requires the certified MonitorBox 2.3 factory UI build 2 seed"
    )

_OVERRIDES = frozenset(("discovery-v22.js", "endpoint-prefill-v22.js"))
_ENDPOINT_PREFILL_SCRIPT = '<script src="/static/endpoint-prefill-v22.js" defer></script>'


def _override_resource(name):
    return files(__package__).joinpath("assets", name)


@web.middleware
async def endpoint_prefill_presentation(request, handler):
    response = await handler(request)
    if (
        request.path == "/settings/quick-add"
        and isinstance(response, web.Response)
        and response.content_type == "text/html"
        and response.body
    ):
        markup = response.text
        if _ENDPOINT_PREFILL_SCRIPT not in markup and "</body>" in markup:
            response.text = markup.replace(
                "</body>",
                _ENDPOINT_PREFILL_SCRIPT + "</body>",
            )
    return response


async def asset(request):
    name = request.match_info["name"]
    if name not in _OVERRIDES:
        return await factory.asset(request)
    return web.Response(
        text=_override_resource(name).read_text(encoding="utf-8"),
        content_type="text/javascript",
        charset="utf-8",
        headers={{"Cache-Control": "no-cache"}},
    )


def install(app):
    # Middleware order is intentional. aiohttp applies the list in reverse while
    # composing the handler, making this first middleware outermost. It therefore
    # appends endpoint-prefill after the factory presentation has injected its
    # existing deferred scripts, matching certified build-3 execution order.
    app.middlewares.append(endpoint_prefill_presentation)
    app.middlewares.append(factory.v22_settings_presentation)
    app.router.add_get("/", factory.dashboard)
    app.router.add_get("/modules", factory.modules)
    app.router.add_get("/api/v2/build", factory.build_identity)
    app.router.add_get("/static/icons/{{name}}", factory.service_icon)
    app.router.add_get("/static/{{name}}", asset)


__all__ = ["install"]
'''.encode("utf-8")


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


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build == 3:
        package = release.import_package
        result = {f"{package}/__init__.py": _immutable_build3_adapter()}
        for name, payload in stable._build3_assets(root).items():
            result[f"{package}/assets/{name}"] = payload
        return result
    if release.build != UI_BUILD:
        return _STABLE_PACKAGE_FILES(root, release)
    package = release.import_package
    result = {f"{package}/__init__.py": _managed_build8_adapter()}
    for name, payload in _build8_assets(root).items():
        result[f"{package}/assets/{name}"] = payload
    return result


def _requested_output_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args, _ = parser.parse_known_args()
    return args.output_dir


def main() -> None:
    output_dir = _requested_output_dir()
    stable.RELEASES = stable.RELEASES + (RELEASE8,)
    stable._package_files = _package_files
    stable.main()
    build3 = output_dir / f"{stable.MODULE_ID}-{stable.MODULE_VERSION}-build3.zip"
    actual = hashlib.sha256(build3.read_bytes()).hexdigest()
    if actual != _IMMUTABLE_BUILD3_SHA256:
        raise SystemExit(
            "immutable UI build-3 package drift: "
            f"expected {_IMMUTABLE_BUILD3_SHA256}, got {actual}"
        )


if __name__ == "__main__":
    main()
