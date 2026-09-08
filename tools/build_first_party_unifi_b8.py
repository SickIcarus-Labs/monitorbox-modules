#!/usr/bin/env python3
"""Build UniFi Network v1.0.7 build 8 over immutable build-7 dev history."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_unifi_b7 as previous

MODULE_ID = "com.sickicarus.monitorbox.unifi"
MODULE_VERSION = "1.0.7"
MODULE_BUILD = 8
IMPORT_PACKAGE = "monitorbox_unifi_b8"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD8_OVERRIDE_BLOBS = {
    "phase2_policy.py": "4bebad64517733ce76f3f39b77af6aad42e8fc54",
}


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    delta = previous.previous.previous.previous._verified_directory(
        root / "sources" / "unifi" / "1.0.7-build8",
        BUILD8_OVERRIDE_BLOBS,
        label="UniFi v1.0.7 build 8 physical-repair delta",
    )
    result.update(delta)
    expected = set(previous.previous.previous.previous.BASE_SOURCE_BLOBS) | {"phase2_policy.py"}
    if set(result) != expected:
        raise SystemExit("UniFi build 8 composed source shape changed")
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    base = previous.previous.previous.previous
    for old, new in base._CORE_IMPORT_REWRITES:
        text = text.replace(old, new)

    entrypoint_count = text.count(base._BUNDLED_ENTRYPOINT)
    requirement_count = text.count(base._OLD_CORE_REQUIREMENT)
    if name in {"__init__.py", "runtime.py"}:
        if entrypoint_count != 1:
            raise SystemExit(
                f"UniFi bundled entrypoint contract changed in {name}: found {entrypoint_count}"
            )
        if requirement_count != 1:
            raise SystemExit(
                f"UniFi Core requirement contract changed in {name}: found {requirement_count}"
            )
        managed_entrypoint = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
        text = text.replace(base._BUNDLED_ENTRYPOINT, managed_entrypoint, 1)
        text = text.replace(base._OLD_CORE_REQUIREMENT, base._NEW_CORE_REQUIREMENT, 1)
    elif entrypoint_count or requirement_count:
        raise SystemExit(f"unexpected UniFi manifest contract found in {name}")

    if name == "runtime.py":
        if text.count('MODULE_VERSION = "1.0.0"') != 1 or text.count("MODULE_BUILD = 1") != 1:
            raise SystemExit("UniFi build-1 release identity markers changed")
        text = text.replace('MODULE_VERSION = "1.0.0"', f'MODULE_VERSION = "{MODULE_VERSION}"', 1)
        text = text.replace("MODULE_BUILD = 1", f"MODULE_BUILD = {MODULE_BUILD}", 1)

    forbidden = (
        "from ...discovery",
        "from ...model",
        "from ...plugin_api",
        "monitorbox.v2.integrations.unifi:PLUGIN",
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"UniFi managed namespace rewrite incomplete in {name}: {remaining}")
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _source_files(root).items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = previous.previous.previous.previous._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"build8_overrides={len(BUILD8_OVERRIDE_BLOBS)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    base = previous.previous.previous.previous
    historical = set(base.HISTORICAL_FILENAMES) | {
        base.FILENAME,
        previous.previous.previous.FILENAME,
        previous.previous.FILENAME,
        previous.FILENAME,
    }
    expected = historical | {FILENAME}
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in expected
    )
    if unexpected:
        raise SystemExit(f"unexpected managed UniFi packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
