#!/usr/bin/env python3
"""Build deterministic managed UI packages for the frozen MonitorBox 2.3 Core line.

The factory UI is the certified recovery seed bundled with frozen Core. Managed build 2 is an
explicit generation-safe adapter to that seed. Managed build 3 composes only its certified UI
delta over the same seed. This keeps publication independent of private-repository credentials
while preserving exact provenance for every changed build-3 asset.
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
FACTORY_BUILD = 2
CERTIFIED_BUILD2_SHA = "0f1c91e64b7772d757b484cedaec0b9df7cbf82b"
CERTIFIED_BUILD3_SHA = "cc4a82ef4420be3edd8778ac16b5c132917ad22a"
BUILD3_SOURCE_BLOBS = {
    "discovery-v22.js": "4b97daed8a7813499cca57ed08dda708643fae06",
    "endpoint-prefill-v22.js": "675f16a1db88522b9bebce0d3f64751b969c1065",
}


@dataclass(frozen=True, slots=True)
class Release:
    build: int
    certified_sha: str

    @property
    def import_package(self) -> str:
        return f"monitorbox_ui_b{self.build}"

    @property
    def filename(self) -> str:
        return f"{MODULE_ID}-{MODULE_VERSION}-build{self.build}.zip"


RELEASES = (
    Release(build=2, certified_sha=CERTIFIED_BUILD2_SHA),
    Release(build=3, certified_sha=CERTIFIED_BUILD3_SHA),
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


def _build3_adapter() -> bytes:
    return f'''"""Managed MonitorBox UI build 3 composed over the certified factory UI seed."""

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


def _package_files(root: Path, release: Release) -> dict[str, bytes]:
    package = release.import_package
    if release.build == 2:
        return {f"{package}/__init__.py": _build2_adapter()}
    if release.build == 3:
        files = {f"{package}/__init__.py": _build3_adapter()}
        for name, payload in _build3_assets(root).items():
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
