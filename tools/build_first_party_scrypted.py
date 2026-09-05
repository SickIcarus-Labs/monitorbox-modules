#!/usr/bin/env python3
"""Build the independently managed Scrypted integration for MonitorBox 2.3 Core."""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.scrypted"
MODULE_VERSION = "1.0.0"
MODULE_BUILD = 1
IMPORT_PACKAGE = "monitorbox_scrypted_b1"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
CORE_SOURCE_SHA = "ba89f9623bfa1b406720444bf7ca51f5dc3b04bb"

SOURCE_BLOBS = {
    "__init__.py": "b59f0e93c7b10a1fb31745227c791607dfba59c7",
    "adoption.py": "66e0b3fc87a6365f4bca62990390131c201b7a9b",
    "onboarding.py": "f7045fc0d31d6722c472ef3cf70732ca203f1969",
    "runtime.py": "d130aa3ea5a9abe118ae7c96e66f2d4968479425",
}

_CORE_IMPORT_REWRITES = (
    ("from ...plugin_api", "from monitorbox.v2.plugin_api"),
)
_BUNDLED_ENTRYPOINT = 'entrypoints={"integration": "monitorbox.v2.integrations.scrypted:PLUGIN"}'
_MANAGED_ENTRYPOINT = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
_OLD_CORE_REQUIREMENT = 'requires_core=">=2.2.2 <3.0.0"'
_NEW_CORE_REQUIREMENT = 'requires_core=">=2.3.0 <3.0.0"'


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _source_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "scrypted" / "1.0.0-build1"
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    expected_names = set(SOURCE_BLOBS)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SystemExit(
            f"Scrypted 1.0.0 build 1 source shape changed: missing={missing}, extra={extra}"
        )

    result: dict[str, bytes] = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"Scrypted 1.0.0 build 1 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    for old, new in _CORE_IMPORT_REWRITES:
        text = text.replace(old, new)

    entrypoint_count = text.count(_BUNDLED_ENTRYPOINT)
    requirement_count = text.count(_OLD_CORE_REQUIREMENT)
    if name == "__init__.py":
        if entrypoint_count != 1:
            raise SystemExit(
                f"Scrypted bundled entrypoint contract changed in {name}: found {entrypoint_count}"
            )
        if requirement_count != 1:
            raise SystemExit(
                f"Scrypted Core requirement contract changed in {name}: found {requirement_count}"
            )
        text = text.replace(_BUNDLED_ENTRYPOINT, _MANAGED_ENTRYPOINT, 1)
        text = text.replace(_OLD_CORE_REQUIREMENT, _NEW_CORE_REQUIREMENT, 1)
    elif entrypoint_count or requirement_count:
        raise SystemExit(f"unexpected Scrypted manifest contract found in {name}")

    forbidden = (
        "from ...plugin_api",
        "monitorbox.v2.integrations.scrypted:PLUGIN",
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"Scrypted managed namespace rewrite incomplete in {name}: {remaining}")
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
        f"source={CORE_SOURCE_SHA} source_files={len(SOURCE_BLOBS)} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name != FILENAME
    )
    if unexpected:
        raise SystemExit(f"unexpected managed Scrypted packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
