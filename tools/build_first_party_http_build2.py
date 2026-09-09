#!/usr/bin/env python3
"""Build HTTP 1.0.1 build 2 startup-convergence release."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_http as previous

MODULE_ID = previous.MODULE_ID
MODULE_VERSION = "1.0.1"
MODULE_BUILD = 2
IMPORT_PACKAGE = "monitorbox_http_v101_b2"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
SOURCE_BLOBS = {
    "__init__.py": "d7bcc4926412d18db7aea04eb2a456acb8c77fc8",
    "startup_confirmation.py": "63112ad3cf57574d5187efc96dbe549878655f70",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _delta_files(root: Path) -> dict[str, bytes]:
    source_root = root / "sources" / "http" / "1.0.1-build2"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    expected = set(SOURCE_BLOBS)
    if actual != expected:
        raise SystemExit(f"HTTP 1.0.1 build 2 source shape changed: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    result: dict[str, bytes] = {}
    for name, expected_blob in SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(f"HTTP 1.0.1 build 2 source drift for {name}: expected Git blob {expected_blob}, got {actual_blob}")
        result[name] = payload
    return result


def _package_files(root: Path) -> dict[str, bytes]:
    old_source = previous._source_files(root)["__init__.py"]
    managed_base = previous._rewrite_source("__init__.py", old_source)
    delta = _delta_files(root)
    return {
        f"{IMPORT_PACKAGE}/_base.py": managed_base,
        f"{IMPORT_PACKAGE}/__init__.py": delta["__init__.py"],
        f"{IMPORT_PACKAGE}/startup_confirmation.py": delta["startup_confirmation.py"],
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = previous._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} entrypoint={IMPORT_PACKAGE}:PLUGIN")
    unexpected = sorted(path.name for path in output_dir.glob(f"{MODULE_ID}-*.zip") if path.name != FILENAME)
    if unexpected:
        raise SystemExit(f"unexpected managed HTTP packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
