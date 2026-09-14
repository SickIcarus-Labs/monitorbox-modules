#!/usr/bin/env python3
"""Build SNMP v1.1.0 build 9 signed bootstrap-discovery release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_first_party_snmp as base
import build_first_party_snmp_106 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "1.1.0"
MODULE_BUILD = 9
IMPORT_PACKAGE = "monitorbox_snmp_v110_b9"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-{previous.MODULE_VERSION}-build{previous.MODULE_BUILD}.zip"
SOURCE_DELTA = "1.1.0-build9"
METADATA_BLOB = "13af9c9542a9eb69ec7ad68a1ee1020468a36365"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _metadata(root: Path) -> dict:
    path = root / "sources" / "snmp" / SOURCE_DELTA / "metadata.json"
    payload = path.read_bytes()
    actual = base._git_blob_sha(payload)
    if actual != METADATA_BLOB:
        raise SystemExit(f"SNMP 1.1.0 build 9 metadata drift: expected {METADATA_BLOB}, got {actual}")
    data = json.loads(payload)
    if data.get("schema") != 1 or data.get("module_id") != MODULE_ID:
        raise SystemExit("SNMP 1.1.0 build 9 metadata contract is malformed")
    return data


def _configure(root: Path) -> None:
    previous._configure()
    metadata = _metadata(root)

    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base.HISTORICAL_FILENAMES = frozenset(
        set(base.HISTORICAL_FILENAMES) | {PREVIOUS_FILENAME}
    )

    predecessor_rewrite = base._rewrite_source

    def rewrite_build9(name: str, payload: bytes) -> bytes:
        text = predecessor_rewrite(name, payload).decode("utf-8")
        if name != "__init__.py":
            return text.encode("utf-8")
        text = _replace_once(
            text,
            f'MODULE_VERSION = "{previous.MODULE_VERSION}"',
            f'MODULE_VERSION = "{MODULE_VERSION}"',
            "SNMP version",
        )
        text = _replace_once(
            text,
            f"MODULE_BUILD = {previous.MODULE_BUILD}",
            f"MODULE_BUILD = {MODULE_BUILD}",
            "SNMP build",
        )
        text = _replace_once(
            text,
            f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}',
            f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
            "SNMP managed entrypoint",
        )
        text = _replace_once(
            text,
            'requires_core=">=2.3.1 <3.0.0"',
            'requires_core=">=2.4.0 <3.0.0"',
            "SNMP bootstrap Core requirement",
        )
        text = _replace_once(
            text,
            '    display_name="SNMP Integration",\n    version=MODULE_VERSION,\n',
            f'    display_name="SNMP Integration",\n    description={metadata["description"]!r},\n    version=MODULE_VERSION,\n',
            "SNMP description",
        )
        text = _replace_once(
            text,
            '    publisher_id="com.sickicarus",\n)',
            f'    publisher_id="com.sickicarus",\n    capability_detection={metadata["capability_detection"]!r},\n)',
            "SNMP capability detection",
        )
        return text.encode("utf-8")

    base._rewrite_source = rewrite_build9


def build(root: Path, output_dir: Path) -> Path:
    previous_package = output_dir / PREVIOUS_FILENAME
    if not previous_package.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous_package}; build 9 must not recreate build 8"
        )
    _configure(root)
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected SNMP build-9 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
