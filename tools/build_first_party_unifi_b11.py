#!/usr/bin/env python3
"""Build UniFi Network v1.1.0 build 11 signed bootstrap-discovery release."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import build_first_party_unifi as base
import build_first_party_unifi_b10 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "1.1.0"
MODULE_BUILD = 11
IMPORT_PACKAGE = "monitorbox_unifi_v110_b11"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-{previous.MODULE_VERSION}-build{previous.MODULE_BUILD}.zip"
SOURCE_DELTA = "1.1.0-build11"
METADATA_BLOB = "59d75b8227c2f933db20be829578f90f56228579"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _metadata(root: Path) -> dict:
    path = root / "sources" / "unifi" / SOURCE_DELTA / "metadata.json"
    payload = path.read_bytes()
    actual = base._git_blob_sha(payload)
    if actual != METADATA_BLOB:
        raise SystemExit(f"UniFi 1.1.0 build 11 metadata drift: expected {METADATA_BLOB}, got {actual}")
    data = json.loads(payload)
    if data.get("schema") != 1 or data.get("module_id") != MODULE_ID:
        raise SystemExit("UniFi 1.1.0 build 11 metadata contract is malformed")
    return data


def _rewrite_source(root: Path, name: str, payload: bytes) -> bytes:
    metadata = _metadata(root)
    text = previous._rewrite_source(name, payload).decode("utf-8")
    if name not in {"__init__.py", "runtime.py"}:
        return text.encode("utf-8")

    text = _replace_once(
        text,
        f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}',
        f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
        f"UniFi {name} managed entrypoint",
    )
    text = _replace_once(
        text,
        base._NEW_CORE_REQUIREMENT,
        'requires_core=">=2.4.0 <3.0.0"',
        f"UniFi {name} bootstrap Core requirement",
    )
    text = _replace_once(
        text,
        '    display_name="UniFi Network Integration",\n    version=MODULE_VERSION,\n',
        f'    display_name="UniFi Network Integration",\n    description={metadata["description"]!r},\n    version=MODULE_VERSION,\n',
        f"UniFi {name} description",
    )
    text = _replace_once(
        text,
        '    publisher_id="com.sickicarus",\n)',
        f'    publisher_id="com.sickicarus",\n    capability_detection={metadata["capability_detection"]!r},\n)',
        f"UniFi {name} capability detection",
    )
    if name == "runtime.py":
        text = _replace_once(
            text,
            f'MODULE_VERSION = "{previous.MODULE_VERSION}"',
            f'MODULE_VERSION = "{MODULE_VERSION}"',
            "UniFi version",
        )
        text = _replace_once(
            text,
            f"MODULE_BUILD = {previous.MODULE_BUILD}",
            f"MODULE_BUILD = {MODULE_BUILD}",
            "UniFi build",
        )
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(root, name, payload)
        for name, payload in previous._source_files(root).items()
    }


def build(root: Path, output_dir: Path) -> Path:
    predecessor = output_dir / PREVIOUS_FILENAME
    if not predecessor.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {predecessor}; build 11 must not recreate build 10"
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
