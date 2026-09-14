#!/usr/bin/env python3
"""Build HTTP(S) v1.1.0 build 3 signed bootstrap-discovery release."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import build_first_party_http as base
import build_first_party_http_build2 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "1.1.0"
MODULE_BUILD = 3
IMPORT_PACKAGE = "monitorbox_http_v110_b3"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-{previous.MODULE_VERSION}-build{previous.MODULE_BUILD}.zip"
SOURCE_DELTA = "1.1.0-build3"
METADATA_BLOB = "bb16c366ed8b864eaabe47766527a7261fa880e4"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _metadata(root: Path) -> dict:
    path = root / "sources" / "http" / SOURCE_DELTA / "metadata.json"
    payload = path.read_bytes()
    actual = base._git_blob_sha(payload)
    if actual != METADATA_BLOB:
        raise SystemExit(f"HTTP 1.1.0 build 3 metadata drift: expected {METADATA_BLOB}, got {actual}")
    data = json.loads(payload)
    if data.get("schema") != 1 or data.get("module_id") != MODULE_ID:
        raise SystemExit("HTTP 1.1.0 build 3 metadata contract is malformed")
    return data


def _package_files(root: Path) -> dict[str, bytes]:
    metadata = _metadata(root)
    predecessor_files = previous._package_files(root)
    output: dict[str, bytes] = {}
    for path, payload in predecessor_files.items():
        name = path.split("/", 1)[1]
        if name == "__init__.py":
            text = payload.decode("utf-8")
            text = _replace_once(
                text,
                f'MODULE_VERSION = "{previous.MODULE_VERSION}"',
                f'MODULE_VERSION = "{MODULE_VERSION}"',
                "HTTP version",
            )
            text = _replace_once(
                text,
                f"MODULE_BUILD = {previous.MODULE_BUILD}",
                f"MODULE_BUILD = {MODULE_BUILD}",
                "HTTP build",
            )
            text = _replace_once(
                text,
                f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}',
                f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
                "HTTP managed entrypoint",
            )
            text = _replace_once(
                text,
                'requires_core=">=2.3.1 <3.0.0"',
                'requires_core=">=2.4.0 <3.0.0"',
                "HTTP bootstrap Core requirement",
            )
            text = _replace_once(
                text,
                '    display_name="HTTP(S) Integration",\n    version=MODULE_VERSION,\n',
                f'    display_name="HTTP(S) Integration",\n    description={metadata["description"]!r},\n    version=MODULE_VERSION,\n',
                "HTTP description",
            )
            text = _replace_once(
                text,
                '    publisher_id="com.sickicarus",\n)',
                f'    publisher_id="com.sickicarus",\n    capability_detection={metadata["capability_detection"]!r},\n)',
                "HTTP capability detection",
            )
            payload = text.encode("utf-8")
        output[f"{IMPORT_PACKAGE}/{name}"] = payload
    return output


def build(root: Path, output_dir: Path) -> Path:
    predecessor = output_dir / PREVIOUS_FILENAME
    if not predecessor.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {predecessor}; build 3 must not recreate build 2"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = base._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
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
