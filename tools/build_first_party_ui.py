#!/usr/bin/env python3
"""Build deterministic managed UI packages for the frozen MonitorBox 2.3 Core line.

The factory UI is the certified recovery seed bundled with frozen Core. Managed build 2 is an
explicit generation-safe adapter to that seed. Managed build 3 composes its certified endpoint
prefill/discovery delta over the seed. Managed build 4 is a deliberately narrow successor to
build 3: it adds only bounded provider environment/Compose provenance presentation for #162.
Managed build 5 composes build 4 plus presentation-only Compose stack hierarchy for #171.
Managed UI 1.0.1 build 6 corrects that hierarchy so authoritative provider workload members can
participate in the Service Directory without becoming canonical Core health objects.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.ui"
MODULE_VERSION = "1.0.0"
PATCH_VERSION = "1.0.1"
FACTORY_BUILD = 2
CERTIFIED_BUILD2_SHA = "0f1c91e64b7772d757b484cedaec0b9df7cbf82b"
CERTIFIED_BUILD3_SHA = "cc4a82ef4420be3edd8778ac16b5c132917ad22a"
CERTIFIED_BUILD4_REFERENCE_SHA = "b539759659577ae95782c54aae36fc6ddd830964"
CERTIFIED_BUILD5_REFERENCE_SHA = "804de1c26bb28cfa2ffce65eb1960d3df4f4312a"
CERTIFIED_BUILD6_REFERENCE_SHA = "18eea695a237856fdea8e74c4ff22418fdc5f1ad"
BUILD3_SOURCE_BLOBS = {
    "discovery-v22.js": "4b97daed8a7813499cca57ed08dda708643fae06",
    "endpoint-prefill-v22.js": "675f16a1db88522b9bebce0d3f64751b969c1065",
}
BUILD4_PROVENANCE_SNIPPET_BLOB = "e3028c40c0ff336333d8d66f7e687f32b4928767"
BUILD5_SOURCE_BLOBS = {
    "service-presentation.js": "804de1c26bb28cfa2ffce65eb1960d3df4f4312a",
    "service-presentation.css": "451ae6f906d5bc70e585795dfd835d6111204d2f",
}
BUILD6_PATCH_BLOB = CERTIFIED_BUILD6_REFERENCE_SHA


@dataclass(frozen=True, slots=True)
class Release:
    build: int
    certified_sha: str
    version: str = MODULE_VERSION

    @property
    def import_package(self) -> str:
        return f"monitorbox_ui_b{self.build}"

    @property
    def filename(self) -> str:
        return f"{MODULE_ID}-{self.version}-build{self.build}.zip"


RELEASES = (
    Release(build=2, certified_sha=CERTIFIED_BUILD2_SHA),
    Release(build=3, certified_sha=CERTIFIED_BUILD3_SHA),
    Release(build=4, certified_sha=CERTIFIED_BUILD4_REFERENCE_SHA),
    Release(build=5, certified_sha=CERTIFIED_BUILD5_REFERENCE_SHA),
    Release(build=6, certified_sha=CERTIFIED_BUILD6_REFERENCE_SHA, version=PATCH_VERSION),
)


def _git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _build2_adapter() -> bytes:
    return f'''"""Managed MonitorBox UI build 2 adapter to the certified factory recovery seed."""

from monitorbox.v2.modules.ui import (
    MODULE_BUILD as FACTORY_BUILD,
    MODULE_ID as FACTORY_ID,
    MODULE_VERSION as FACTORY_VERSION,
    install as _factory_install,
)

_EXPECTED = ({MODULE_ID!r}, {MODULE_VERSION!r}, {FACTORY_BUILD})
if (FACTORY_ID, FACTORY_VERSION, FACTORY_BUILD) != _EXPECTED:
    raise ImportError(
        "managed UI build 2 requires the certified MonitorBox 2.3 factory UI build 2 seed"
    )


def install(app):
    _factory_install(app)


__all__ = ["install"]
'''.encode("utf-8")


def _managed_delta_adapter(build: int) -> bytes:
    """Keep byte-identical build-3/build-4 adapter generation immutable."""
    return f'''"""Managed MonitorBox UI build {build} composed over the certified factory UI seed."""

from importlib.resources import files

from aiohttp import web
from monitorbox.v2.modules.ui import (
    MODULE_BUILD as FACTORY_BUILD,
    MODULE_ID as FACTORY_ID,
    MODULE_VERSION as FACTORY_VERSION,
)
from monitorbox.v2.modules.ui import application as factory

_EXPECTED = ({MODULE_ID!r}, {MODULE_VERSION!r}, {FACTORY_BUILD})
if (FACTORY_ID, FACTORY_VERSION, FACTORY_BUILD) != _EXPECTED:
    raise ImportError(
        "managed UI build {build} requires the certified MonitorBox 2.3 factory UI build 2 seed"
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
    app.middlewares.append(endpoint_prefill_presentation)
    app.middlewares.append(factory.v22_settings_presentation)
    app.router.add_get("/", factory.dashboard)
    app.router.add_get("/modules", factory.modules)
    app.router.add_get("/api/v2/build", factory.build_identity)
    app.router.add_get("/static/icons/{{name}}", factory.service_icon)
    app.router.add_get("/static/{{name}}", asset)


__all__ = ["install"]
'''.encode("utf-8")


def _managed_build5_adapter() -> bytes:
    return f'''"""Managed MonitorBox UI build 5 composed over the certified factory UI seed."""

from importlib.resources import files

from aiohttp import web
from monitorbox.v2.modules.ui import (
    MODULE_BUILD as FACTORY_BUILD,
    MODULE_ID as FACTORY_ID,
    MODULE_VERSION as FACTORY_VERSION,
)
from monitorbox.v2.modules.ui import application as factory

_EXPECTED = ({MODULE_ID!r}, {MODULE_VERSION!r}, {FACTORY_BUILD})
if (FACTORY_ID, FACTORY_VERSION, FACTORY_BUILD) != _EXPECTED:
    raise ImportError(
        "managed UI build 5 requires the certified MonitorBox 2.3 factory UI build 2 seed"
    )

_OVERRIDE_TYPES = {{
    "discovery-v22.js": "text/javascript",
    "endpoint-prefill-v22.js": "text/javascript",
    "service-presentation.js": "text/javascript",
    "service-presentation.css": "text/css",
}}
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
    app.middlewares.append(endpoint_prefill_presentation)
    app.middlewares.append(factory.v22_settings_presentation)
    app.router.add_get("/", factory.dashboard)
    app.router.add_get("/modules", factory.modules)
    app.router.add_get("/api/v2/build", factory.build_identity)
    app.router.add_get("/static/icons/{{name}}", factory.service_icon)
    app.router.add_get("/static/{{name}}", asset)


__all__ = ["install"]
'''.encode("utf-8")


def _managed_build6_adapter() -> bytes:
    # Runtime surface is intentionally identical to build 5; only the packaged
    # service-presentation asset gains the 1.0.1 correction delta.
    return _managed_build5_adapter().replace(b"build 5", b"build 6")


def _build3_assets(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "ui" / "1.0.0-build3"
    assets: dict[str, bytes] = {}
    for name, expected_blob in BUILD3_SOURCE_BLOBS.items():
        path = source_root / name
        payload = path.read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"certified UI build-3 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        assets[name] = payload
    return assets


def _build4_assets(root: Path) -> dict[str, bytes]:
    assets = _build3_assets(root)
    snippet_path = root / "sources" / "ui" / "1.0.0-build4" / "provider-provenance-snippet.js"
    snippet = snippet_path.read_bytes()
    actual_blob = _git_blob_sha(snippet)
    if actual_blob != BUILD4_PROVENANCE_SNIPPET_BLOB:
        raise SystemExit(
            "certified UI build-4 provenance snippet drift: "
            f"expected Git blob {BUILD4_PROVENANCE_SNIPPET_BLOB}, got {actual_blob}"
        )

    discovery = assets["discovery-v22.js"].decode("utf-8")
    function_marker = "\n  function addV22Controls(){"
    if discovery.count(function_marker) != 1:
        raise SystemExit("UI build-4 provenance function insertion marker changed")
    discovery = discovery.replace(
        function_marker,
        "\n" + snippet.decode("utf-8").rstrip("\n") + "\n" + function_marker,
        1,
    )

    render_marker = (
        "        if(!item)continue;\n"
        "        const configuredObject=new Set((item.configured_adapters||[])"
    )
    if discovery.count(render_marker) != 1:
        raise SystemExit("UI build-4 provenance render insertion marker changed")
    discovery = discovery.replace(
        render_marker,
        "        if(!item)continue;\n"
        "        renderProviderProvenance(row,item);\n"
        "        const configuredObject=new Set((item.configured_adapters||[])",
        1,
    )
    assets["discovery-v22.js"] = discovery.encode("utf-8")
    return assets


def _build5_assets(root: Path) -> dict[str, bytes]:
    assets = _build4_assets(root)
    source_root = root / "sources" / "ui" / "1.0.0-build5"
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    expected_names = set(BUILD5_SOURCE_BLOBS)
    if actual_names != expected_names:
        raise SystemExit(
            "UI build-5 delta shape changed: "
            f"missing={sorted(expected_names-actual_names)}, extra={sorted(actual_names-expected_names)}"
        )
    for name, expected_blob in BUILD5_SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"certified UI build-5 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        assets[name] = payload
    return assets


def _build6_assets(root: Path) -> dict[str, bytes]:
    assets = _build5_assets(root)
    source_root = root / "sources" / "ui" / "1.0.1-build6"
    expected_names = {"provider-service-hierarchy.js"}
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise SystemExit(
            "UI 1.0.1 build-6 delta shape changed: "
            f"missing={sorted(expected_names-actual_names)}, extra={sorted(actual_names-expected_names)}"
        )
    patch = (source_root / "provider-service-hierarchy.js").read_bytes()
    actual_blob = _git_blob_sha(patch)
    if actual_blob != BUILD6_PATCH_BLOB:
        raise SystemExit(
            "certified UI 1.0.1 build-6 source drift: "
            f"expected Git blob {BUILD6_PATCH_BLOB}, got {actual_blob}"
        )
    assets["service-presentation.js"] = (
        assets["service-presentation.js"].rstrip(b"\n") + b"\n\n" + patch.rstrip(b"\n") + b"\n"
    )
    return assets


def _package_files(root: Path, release: Release) -> dict[str, bytes]:
    package = release.import_package
    if release.build == 2:
        return {f"{package}/__init__.py": _build2_adapter()}
    if release.build in {3, 4}:
        files = {f"{package}/__init__.py": _managed_delta_adapter(release.build)}
        assets = _build3_assets(root) if release.build == 3 else _build4_assets(root)
        for name, payload in assets.items():
            files[f"{package}/assets/{name}"] = payload
        return files
    if release.build == 5:
        files = {f"{package}/__init__.py": _managed_build5_adapter()}
        for name, payload in _build5_assets(root).items():
            files[f"{package}/assets/{name}"] = payload
        return files
    if release.build == 6:
        files = {f"{package}/__init__.py": _managed_build6_adapter()}
        for name, payload in _build6_assets(root).items():
            files[f"{package}/assets/{name}"] = payload
        return files
    raise SystemExit(f"unsupported managed UI build {release.build}")


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[path], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def build(root: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = {release.filename for release in RELEASES}
    for release in RELEASES:
        payload = _zip_bytes(_package_files(root, release))
        target = output_dir / release.filename
        target.write_bytes(payload)
        print(
            f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
            f"certified_source={release.certified_sha} "
            f"entrypoint={release.import_package}:install"
        )
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed UI packages already present: {unexpected}")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
