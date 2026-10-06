#!/usr/bin/env python3
"""Build Scrypted 2.3.1 build 7 signed Node-loader runtime repair."""
from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_scrypted as base
import build_first_party_scrypted_230 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "2.3.1"
MODULE_BUILD = 7
IMPORT_PACKAGE = "monitorbox_scrypted_v231_b7"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = previous.FILENAME
SOURCE_DELTA = "2.3.1-build7"
SOURCE_BLOBS = {"node_runtime.py": "0f78aabacf0a5018e3e556b0e2bad8be72260084"}


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
        files.update(
            base._verified_delta(
                root,
                SOURCE_DELTA,
                SOURCE_BLOBS,
                "Scrypted 2.3.1 build 7 signed Node-loader delta",
            )
        )
        return files

    def rewrite_build7(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name == "runtime.py":
            text = _replace_once(
                text,
                "import aiohttp\n",
                "import aiohttp\n\nfrom .node_runtime import node_launch_prefix\n",
                "Scrypted signed Node launch import",
            )
            text = _replace_once(
                text,
                '''        node = shutil.which(os.environ.get("MONITORBOX_MODULE_NODE", "node"))\n        if node is None:\n            raise RuntimeError("Node.js runtime is unavailable for the Scrypted module")\n''',
                '''        node_argv = node_launch_prefix()\n''',
                "Scrypted signed Node runtime resolution",
            )
            text = _replace_once(
                text,
                '''        process = await asyncio.create_subprocess_exec(\n            node,\n            str(self._bridge_root / "server.mjs"),\n''',
                '''        process = await asyncio.create_subprocess_exec(\n            *node_argv,\n            str(self._bridge_root / "server.mjs"),\n''',
                "Scrypted signed Node loader invocation",
            )
            if 'create_subprocess_exec(\n            node,' in text:
                raise SystemExit("Scrypted build 7 still executes the signed Node ELF directly")
        return text.encode("utf-8")

    base._python_source_files = source_files_build7
    base._rewrite_source = rewrite_build7


def build(root: Path, output_dir: Path) -> Path:
    previous_package = output_dir / PREVIOUS_FILENAME
    if not previous_package.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous_package}; build 7 must not recreate build 6"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected Scrypted 2.3.1 build-7 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
