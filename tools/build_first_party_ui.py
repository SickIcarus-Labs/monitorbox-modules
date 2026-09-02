#!/usr/bin/env python3
"""Build immutable MonitorBox UI module packages from certified upstream commits.

The frozen Core loader imports entrypoints directly from verified ZIPs. Each release therefore
uses a generation-specific top-level package name so Python's module cache cannot alias one
managed generation to another during update/rollback preflight.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

UPSTREAM_REPOSITORY = "SickIcarus-Labs/monitorbox"
UPSTREAM_UI_ROOT = "src/monitorbox/v2/modules/ui"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
USER_AGENT = "monitorbox-modules-first-party-packager/1"


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    build: int
    upstream_sha: str

    @property
    def import_package(self) -> str:
        return f"monitorbox_ui_b{self.build}"

    @property
    def filename(self) -> str:
        return f"com.sickicarus.monitorbox.ui-{self.version}-build{self.build}.zip"


RELEASES = (
    Release(
        version="1.0.0",
        build=2,
        upstream_sha="0f1c91e64b7772d757b484cedaec0b9df7cbf82b",
    ),
    Release(
        version="1.0.0",
        build=3,
        upstream_sha="cc4a82ef4420be3edd8778ac16b5c132917ad22a",
    ),
)


def _request(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _raw_url(sha: str, path: str) -> str:
    quoted = urllib.parse.quote(path, safe="/")
    return f"https://raw.githubusercontent.com/{UPSTREAM_REPOSITORY}/{sha}/{quoted}"


def _contents_url(sha: str, path: str) -> str:
    quoted = urllib.parse.quote(path, safe="/")
    query = urllib.parse.urlencode({"ref": sha})
    return f"https://api.github.com/repos/{UPSTREAM_REPOSITORY}/contents/{quoted}?{query}"


def _read_text(sha: str, path: str) -> str:
    return _request(_raw_url(sha, path)).decode("utf-8")


def _validate_upstream_identity(release: Release) -> None:
    source = _read_text(release.upstream_sha, f"{UPSTREAM_UI_ROOT}/__init__.py")
    expected = {
        "MODULE_ID": "com.sickicarus.monitorbox.ui",
        "MODULE_VERSION": release.version,
        "MODULE_BUILD": str(release.build),
    }
    patterns = {
        "MODULE_ID": r'^MODULE_ID\s*=\s*"([^"]+)"$',
        "MODULE_VERSION": r'^MODULE_VERSION\s*=\s*"([^"]+)"$',
        "MODULE_BUILD": r"^MODULE_BUILD\s*=\s*([0-9]+)$",
    }
    for name, pattern in patterns.items():
        match = re.search(pattern, source, flags=re.MULTILINE)
        if match is None or match.group(1) != expected[name]:
            raise SystemExit(
                f"certified upstream identity mismatch for {release.upstream_sha}: "
                f"expected {name}={expected[name]!r}"
            )


def _static_files(sha: str, path: str) -> dict[str, bytes]:
    listing = json.loads(_request(_contents_url(sha, path)).decode("utf-8"))
    if not isinstance(listing, list):
        raise SystemExit(f"unexpected GitHub contents response for {path}")
    result: dict[str, bytes] = {}
    for item in listing:
        kind = item.get("type")
        item_path = item.get("path")
        if not isinstance(item_path, str):
            raise SystemExit(f"invalid GitHub contents item beneath {path}")
        if kind == "dir":
            result.update(_static_files(sha, item_path))
        elif kind == "file":
            relative = item_path.removeprefix(f"{UPSTREAM_UI_ROOT}/static/")
            if not relative or relative == item_path:
                raise SystemExit(f"static asset escaped UI root: {item_path}")
            result[relative] = _request(_raw_url(sha, item_path))
        else:
            raise SystemExit(f"unsupported GitHub contents item {item_path}: {kind!r}")
    return result


def _application_source(release: Release) -> bytes:
    source = _read_text(release.upstream_sha, f"{UPSTREAM_UI_ROOT}/application.py")
    old_import = "from ...build_info import current_build_identity"
    if source.count(old_import) != 1:
        raise SystemExit(
            f"unexpected build-info import shape in certified UI source {release.upstream_sha}"
        )
    source = source.replace(
        old_import,
        "from monitorbox.v2.build_info import current_build_identity",
    )
    old_resources = 'files("monitorbox.v2.modules.ui.static")'
    if source.count(old_resources) != 1:
        raise SystemExit(
            f"unexpected UI resource-package shape in certified source {release.upstream_sha}"
        )
    source = source.replace(old_resources, f'files("{release.import_package}.static")')
    return source.encode("utf-8")


def _package_files(release: Release) -> dict[str, bytes]:
    _validate_upstream_identity(release)
    package = release.import_package
    files: dict[str, bytes] = {
        f"{package}/__init__.py": (
            '"""Managed MonitorBox UI release generated from a certified upstream commit."""\n\n'
            "from .application import install\n\n"
            '__all__ = ["install"]\n'
        ).encode("utf-8"),
        f"{package}/application.py": _application_source(release),
        f"{package}/static/__init__.py": b'"""Managed MonitorBox UI static resources."""\n',
    }
    for relative, payload in _static_files(
        release.upstream_sha,
        f"{UPSTREAM_UI_ROOT}/static",
    ).items():
        files[f"{package}/static/{relative}"] = payload
    return files


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


def build(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = {release.filename for release in RELEASES}
    for release in RELEASES:
        payload = _zip_bytes(_package_files(release))
        target = output_dir / release.filename
        target.write_bytes(payload)
        print(
            f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
            f"upstream={release.upstream_sha} entrypoint={release.import_package}:install"
        )
    unexpected = sorted(
        path.name
        for path in output_dir.glob("com.sickicarus.monitorbox.ui-*.zip")
        if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed UI packages already present: {unexpected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "packages",
    )
    args = parser.parse_args()
    build(args.output_dir)


if __name__ == "__main__":
    main()
