#!/usr/bin/env python3
"""Build Configuration/Bootstrap v1.0.4 build 5 without rewriting history."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_configuration_bootstrap as base
import build_first_party_configuration_bootstrap_b4 as previous

MODULE_ID = "com.sickicarus.monitorbox.configuration-bootstrap"
MODULE_VERSION = "1.0.4"
MODULE_BUILD = 5
IMPORT_MODULE = "monitorbox_configuration_bootstrap_b5"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset(set(previous.HISTORICAL_FILENAMES) | {previous.FILENAME})
SOURCE_FILES = {
    "monitorbox_configuration_bootstrap_b5.py": "3b806b5e0efc6ddb8e1085f7df2281d70111ba46",
    "monitorbox_configuration_bootstrap_local_access_b5.py": "e140d5d16b6af230bcef4144a34805149f962b50",
}


def _files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "configuration-bootstrap" / "1.0.4-build5"
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    expected_names = set(SOURCE_FILES)
    if actual_names != expected_names:
        raise SystemExit(
            "Configuration/Bootstrap 1.0.4 build 5 delta shape changed: "
            f"expected={sorted(expected_names)}, actual={sorted(actual_names)}"
        )

    files = {previous.SOURCE_NAME: previous._source(root)}
    for name, expected_blob in SOURCE_FILES.items():
        payload = (source_root / name).read_bytes()
        actual_blob = base._git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"Configuration/Bootstrap build 5 source drift for {name}: "
                f"expected Git blob {expected_blob}, got {actual_blob}"
            )
        compile(payload, name, "exec")
        files[name] = payload

    if base._git_blob_sha(files[previous.SOURCE_NAME]) != previous.SOURCE_BLOB:
        raise SystemExit("Configuration/Bootstrap build 4 predecessor source drifted")
    return files


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = base._zip_bytes(_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"entrypoint={IMPORT_MODULE}:install predecessor={previous.FILENAME}"
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
