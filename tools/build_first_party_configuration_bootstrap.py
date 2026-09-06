#!/usr/bin/env python3
"""Build current Configuration/Bootstrap while preserving immutable build 1."""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.configuration-bootstrap"
MODULE_VERSION = "1.0.1"
MODULE_BUILD = 2
IMPORT_MODULE = "monitorbox_configuration_bootstrap_b2"
SOURCE_NAME = f"{IMPORT_MODULE}.py"
SOURCE_BLOB = "2403fd567061afe3fd30999b749a55fa487e44d4"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset({f"{MODULE_ID}-1.0.0-build1.zip"})


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _source(root: Path) -> bytes:
    source_root = root / "sources" / "configuration-bootstrap" / "1.0.1-build2"
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual_names != {SOURCE_NAME}:
        raise SystemExit(
            "Configuration/Bootstrap 1.0.1 build 2 source shape changed: "
            f"expected={[SOURCE_NAME]}, actual={sorted(actual_names)}"
        )
    payload = (source_root / SOURCE_NAME).read_bytes()
    actual_blob = _git_blob_sha(payload)
    if actual_blob != SOURCE_BLOB:
        raise SystemExit(
            "Configuration/Bootstrap 1.0.1 build 2 source drift: "
            f"expected Git blob {SOURCE_BLOB}, got {actual_blob}"
        )
    return payload


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
    historical = output_dir / next(iter(HISTORICAL_FILENAMES))
    if not historical.is_file():
        raise SystemExit("immutable Configuration/Bootstrap 1.0.0 build 1 package is missing")

    payload = _zip_bytes({SOURCE_NAME: _source(root)})
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"source_blob={SOURCE_BLOB} entrypoint={IMPORT_MODULE}:install"
    )
    expected = set(HISTORICAL_FILENAMES) | {FILENAME}
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in expected
    )
    if unexpected:
        raise SystemExit(
            "unexpected managed Configuration/Bootstrap packages already present: "
            f"{unexpected}"
        )
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
