#!/usr/bin/env python3
"""Build NUT v1.1.0 build 3 signed bootstrap-discovery release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_first_party_nut as previous

MODULE_ID = previous.MODULE_ID
MODULE_VERSION = "1.1.0"
MODULE_BUILD = 3
IMPORT_PACKAGE = "monitorbox_nut_b3"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
SOURCE_DELTA = "1.1.0-build3"
METADATA_BLOB = "6c169c06f6a2c0d989535d523c9d7592d4f2a2e3"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _metadata(root: Path) -> dict:
    path = root / "sources" / "nut" / SOURCE_DELTA / "metadata.json"
    payload = path.read_bytes()
    actual = previous._git_blob_sha(payload)
    if actual != METADATA_BLOB:
        raise SystemExit(f"NUT 1.1.0 build 3 metadata drift: expected {METADATA_BLOB}, got {actual}")
    data = json.loads(payload)
    if data.get("schema") != 1 or data.get("module_id") != MODULE_ID:
        raise SystemExit("NUT 1.1.0 build 3 metadata contract is malformed")
    return data


def _root_source(root: Path) -> bytes:
    metadata = _metadata(root)
    text = previous._rewrite_root(previous._root_source(root)).decode("utf-8")
    text = _replace_once(text, 'MODULE_VERSION = "1.0.1"', f'MODULE_VERSION = "{MODULE_VERSION}"', "NUT version")
    text = _replace_once(text, "MODULE_BUILD = 2", f"MODULE_BUILD = {MODULE_BUILD}", "NUT build")
    text = _replace_once(
        text,
        'entrypoints={"integration": "monitorbox_nut_b2:PLUGIN"}',
        f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
        "NUT managed entrypoint",
    )
    text = _replace_once(
        text,
        'requires_core=">=2.3.1 <3.0.0"',
        'requires_core=">=2.4.0 <3.0.0"',
        "NUT bootstrap Core requirement",
    )
    text = _replace_once(
        text,
        '    display_name="NUT UPS Integration",\n    version=MODULE_VERSION,\n',
        f'    display_name="NUT UPS Integration",\n    description={metadata["description"]!r},\n    version=MODULE_VERSION,\n',
        "NUT description",
    )
    text = _replace_once(
        text,
        '    publisher_id="com.sickicarus",\n)',
        f'    publisher_id="com.sickicarus",\n    capability_detection={metadata["capability_detection"]!r},\n)',
        "NUT capability detection",
    )
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/__init__.py": _root_source(root),
        f"{IMPORT_PACKAGE}/runtime.py": previous._runtime_source(root),
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = previous._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    expected = set(previous.HISTORICAL_FILENAMES) | {previous.FILENAME, FILENAME}
    unexpected = sorted(
        path.name for path in output_dir.glob(f"{MODULE_ID}-*.zip") if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed NUT packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
