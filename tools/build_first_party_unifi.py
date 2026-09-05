#!/usr/bin/env python3
"""Build the current independently managed UniFi Network integration for MonitorBox 2.3 Core.

UniFi 1.0.0 build 1 and 1.0.1 build 2 remain immutable release history.
1.0.2 build 3 bounds authentication retries so provider-side rate limiting can
expire and recover without a Core rebuild.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.unifi"
MODULE_VERSION = "1.0.2"
MODULE_BUILD = 3
IMPORT_PACKAGE = "monitorbox_unifi_b3"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset(
    {
        f"{MODULE_ID}-1.0.0-build1.zip",
        f"{MODULE_ID}-1.0.1-build2.zip",
    }
)

BASE_SOURCE_BLOBS = {
    "__init__.py": "7a6c9d622aa0ada3f3b5b4a31e3096ff228549bf",
    "adoption.py": "f9753c22931abdf4e20b1930fb39703e8812a7ab",
    "discovery.py": "3652a382a0f6db639b3addd764e52bb22b28a143",
    "discovery_runtime.py": "e930d2ea2a9e5f1fbc2683b8b9feeb782bfdae24",
    "onboarding.py": "f2c4b6b718e722b37bf066016ae2cba69562e194",
    "runtime.py": "77e82812f4da17d20823ef25670c1e68f8ec9325",
    "vertical_runtime.py": "0f28981de155d1e6d030ae2f1ea92b2ad23bbeb9",
}

BUILD2_SOURCE_BLOBS = {
    "discovery_runtime.py": "301edf2e066b59ad0b1722c2d093c2f8d545535f",
}

BUILD3_SOURCE_BLOBS = {
    "discovery_runtime.py": "3e9c904c1fbe68bde080a99f004992c8205e9843",
}

_CORE_IMPORT_REWRITES = (
    ("from ...discovery", "from monitorbox.v2.discovery"),
    ("from ...model", "from monitorbox.v2.model"),
    ("from ...plugin_api", "from monitorbox.v2.plugin_api"),
)
_BUNDLED_ENTRYPOINT = 'entrypoints={"integration": "monitorbox.v2.integrations.unifi:PLUGIN"}'
_MANAGED_ENTRYPOINT = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
_OLD_CORE_REQUIREMENT = 'requires_core=">=2.2.2 <3.0.0"'
_NEW_CORE_REQUIREMENT = 'requires_core=">=2.3.0 <3.0.0"'


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _verified_directory(
    source_root: Path,
    expected_blobs: dict[str, str],
    *,
    label: str,
) -> dict[str, bytes]:
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    expected_names = set(expected_blobs)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SystemExit(f"{label} source shape changed: missing={missing}, extra={extra}")

    result: dict[str, bytes] = {}
    for name, expected_blob in expected_blobs.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"{label} source drift for {name}: expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _source_files(root: Path) -> dict[str, bytes]:
    unifi_root = root / "sources" / "unifi"
    base = _verified_directory(
        unifi_root / "1.0.0-build1",
        BASE_SOURCE_BLOBS,
        label="immutable UniFi 1.0.0 build 1",
    )
    _verified_directory(
        unifi_root / "1.0.1-build2",
        BUILD2_SOURCE_BLOBS,
        label="immutable UniFi 1.0.1 build 2",
    )
    build3 = _verified_directory(
        unifi_root / "1.0.2-build3",
        BUILD3_SOURCE_BLOBS,
        label="UniFi 1.0.2 build 3 auth-backoff delta",
    )
    result = dict(base)
    result.update(build3)
    if set(result) != set(BASE_SOURCE_BLOBS):
        raise SystemExit("UniFi 1.0.2 build 3 composed source shape changed")
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    for old, new in _CORE_IMPORT_REWRITES:
        text = text.replace(old, new)

    entrypoint_count = text.count(_BUNDLED_ENTRYPOINT)
    requirement_count = text.count(_OLD_CORE_REQUIREMENT)
    if name in {"__init__.py", "runtime.py"}:
        if entrypoint_count != 1:
            raise SystemExit(
                f"UniFi bundled entrypoint contract changed in {name}: found {entrypoint_count}"
            )
        if requirement_count != 1:
            raise SystemExit(
                f"UniFi Core requirement contract changed in {name}: found {requirement_count}"
            )
        text = text.replace(_BUNDLED_ENTRYPOINT, _MANAGED_ENTRYPOINT, 1)
        text = text.replace(_OLD_CORE_REQUIREMENT, _NEW_CORE_REQUIREMENT, 1)
    elif entrypoint_count or requirement_count:
        raise SystemExit(f"unexpected UniFi manifest contract found in {name}")

    if name == "runtime.py":
        if text.count('MODULE_VERSION = "1.0.0"') != 1 or text.count("MODULE_BUILD = 1") != 1:
            raise SystemExit("UniFi build 1 release identity markers changed")
        text = text.replace('MODULE_VERSION = "1.0.0"', f'MODULE_VERSION = "{MODULE_VERSION}"', 1)
        text = text.replace("MODULE_BUILD = 1", f"MODULE_BUILD = {MODULE_BUILD}", 1)

    forbidden = (
        "from ...discovery",
        "from ...model",
        "from ...plugin_api",
        "monitorbox.v2.integrations.unifi:PLUGIN",
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"UniFi managed namespace rewrite incomplete in {name}: {remaining}")
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _source_files(root).items()
    }


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
            archive.writestr(
                info,
                files[path],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return output.getvalue()


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = _zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"build3_blob={BUILD3_SOURCE_BLOBS['discovery_runtime.py']} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    expected = set(HISTORICAL_FILENAMES) | {FILENAME}
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed UniFi packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
