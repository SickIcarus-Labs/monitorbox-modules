#!/usr/bin/env python3
"""Build Scrypted 2.4.0 build 7 with Core-transactional child adoption."""
from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_scrypted as base
import build_first_party_scrypted_230 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "2.4.0"
MODULE_BUILD = 7
IMPORT_PACKAGE = "monitorbox_scrypted_v240_b7"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = previous.FILENAME
SOURCE_DELTA = "2.4.0-build7"
ADOPTION_BLOB = "f56a64d333c641a98d96357923febf9900507c9e"


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

    def source_files_build7(root: Path) -> dict[str, bytes]:
        files = original_source_files(root)
        path = root / "sources" / "scrypted" / SOURCE_DELTA / "adoption.py"
        payload = path.read_bytes()
        actual = base._git_blob_sha(payload)
        if actual != ADOPTION_BLOB:
            raise SystemExit(
                f"Scrypted 2.4.0 adoption drift: expected {ADOPTION_BLOB}, got {actual}"
            )
        files["adoption.py"] = payload
        return files

    def rewrite_build7(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name == "__init__.py":
            text = _replace_once(
                text,
                'requires_core=">=2.4.0 <3.0.0"',
                'requires_core=">=2.6.0 <3.0.0"',
                "Scrypted candidate-adoption Core requirement",
            )
        return text.encode("utf-8")

    base._python_source_files = source_files_build7
    base._rewrite_source = rewrite_build7


def build(root: Path, output_dir: Path) -> Path:
    predecessor = output_dir / PREVIOUS_FILENAME
    if not predecessor.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {predecessor}; build 7 must not recreate build 6"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected Scrypted 2.4.0 build-7 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
