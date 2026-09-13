#!/usr/bin/env python3
"""Build Scrypted 2.2.0 build 5 signed capability-discovery release."""
from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_scrypted as base
import build_first_party_scrypted_213 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "2.2.0"
MODULE_BUILD = 5
IMPORT_PACKAGE = "monitorbox_scrypted_v220_b5"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-2.1.3-build4.zip"
SOURCE_DELTA = "2.2.0-build5"
SOURCE_BLOBS = {"__init__.py": "ecfcdcc99ecb5f946eed1120578a68cbd64f4668"}


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _configure() -> None:
    previous._configure()
    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base._MANAGED_ENTRYPOINT = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
    base.PREVIOUS_FILENAMES = set(base.PREVIOUS_FILENAMES) | {PREVIOUS_FILENAME}

    original_source_files = base._python_source_files
    original_rewrite = base._rewrite_source

    def source_files_build5(root: Path) -> dict[str, bytes]:
        files = original_source_files(root)
        files.update(
            base._verified_delta(
                root,
                SOURCE_DELTA,
                SOURCE_BLOBS,
                "Scrypted 2.2.0 build 5 capability-discovery delta",
            )
        )
        return files

    def rewrite_build5(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name == "__init__.py":
            text = _replace_once(
                text,
                'requires_core=">=2.3.1 <3.0.0"',
                'requires_core=">=2.4.0 <3.0.0"',
                "Scrypted capability-discovery Core requirement",
            )
        return text.encode("utf-8")

    base._python_source_files = source_files_build5
    base._rewrite_source = rewrite_build5


def build(root: Path, output_dir: Path) -> Path:
    previous_package = output_dir / PREVIOUS_FILENAME
    if not previous_package.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous_package}; build 5 must not recreate build 4"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected Scrypted 2.2.0 build-5 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
