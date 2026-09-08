#!/usr/bin/env python3
"""Build Configuration/Bootstrap v1.0.2 build 3 without rewriting history."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_configuration_bootstrap as previous

MODULE_ID = "com.sickicarus.monitorbox.configuration-bootstrap"
MODULE_VERSION = "1.0.2"
MODULE_BUILD = 3
IMPORT_MODULE = "monitorbox_configuration_bootstrap_b3"
SOURCE_NAME = f"{IMPORT_MODULE}.py"
SOURCE_BLOB = "4687e4db130f8e3008bf4637336e0537b0424f05"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset(set(previous.HISTORICAL_FILENAMES) | {previous.FILENAME})


def _source(root: Path) -> bytes:
    source_root = root / "sources" / "configuration-bootstrap" / "1.0.2-build3"
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual_names != {SOURCE_NAME}:
        raise SystemExit(
            "Configuration/Bootstrap 1.0.2 build 3 source shape changed: "
            f"expected={[SOURCE_NAME]}, actual={sorted(actual_names)}"
        )
    payload = (source_root / SOURCE_NAME).read_bytes()
    actual_blob = previous._git_blob_sha(payload)
    if actual_blob != SOURCE_BLOB:
        raise SystemExit(
            "Configuration/Bootstrap 1.0.2 build 3 source drift: "
            f"expected Git blob {SOURCE_BLOB}, got {actual_blob}"
        )
    return payload


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = previous._zip_bytes({SOURCE_NAME: _source(root)})
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
