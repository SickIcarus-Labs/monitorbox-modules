#!/usr/bin/env python3
"""Build Portainer 1.4.0 build 10 with Core-transactional workload adoption."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_portainer_b9 as previous

MODULE_ID = "com.sickicarus.monitorbox.portainer"
MODULE_VERSION = "1.4.0"
MODULE_BUILD = 10
IMPORT_PACKAGE = "monitorbox_portainer_b10"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
SOURCE_DELTA = "1.4.0-build10"
ADOPTION_BLOB = "74e1806c55d1c38454f5abefcc16b31fd93cf854"
base = previous.previous.previous.previous


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    source = base._verified_directory(
        root / "sources" / "portainer" / SOURCE_DELTA,
        {"adoption.py": ADOPTION_BLOB},
        label="Portainer v1.4.0 build 10 transactional-adoption delta",
    )
    result.update(source)
    if set(result) != set(base.BASE_SOURCE_BLOBS):
        raise SystemExit("Portainer build 10 composed source shape changed")
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = previous._rewrite_source(name, payload).decode("utf-8")
    if name == "__init__.py":
        text = _replace_once(
            text,
            f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}',
            f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}',
            "Portainer build10 entrypoint",
        )
        text = _replace_once(
            text,
            f'MODULE_VERSION = "{previous.MODULE_VERSION}"',
            f'MODULE_VERSION = "{MODULE_VERSION}"',
            "Portainer build10 version",
        )
        text = _replace_once(
            text,
            f"MODULE_BUILD = {previous.MODULE_BUILD}",
            f"MODULE_BUILD = {MODULE_BUILD}",
            "Portainer build10 build",
        )
        text = _replace_once(
            text,
            'requires_core=">=2.4.0 <3.0.0"',
            'requires_core=">=2.6.0 <3.0.0"',
            "Portainer build10 Core adoption contract",
        )
        text = _replace_once(
            text,
            "managed Portainer build 9 requires",
            "managed Portainer build 10 requires",
            "Portainer build10 compatibility guard",
        )
    if previous.IMPORT_PACKAGE in text:
        raise SystemExit(f"Portainer build10 retained build9 package identity in {name}")
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _source_files(root).items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = base._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    historical = set(base.HISTORICAL_FILENAMES) | {
        base.FILENAME,
        previous.previous.previous.FILENAME,
        previous.previous.FILENAME,
        previous.FILENAME,
    }
    expected = historical | {FILENAME}
    unexpected = sorted(
        path.name for path in output_dir.glob(f"{MODULE_ID}-*.zip") if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed Portainer packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
