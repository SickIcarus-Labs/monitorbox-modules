#!/usr/bin/env python3
"""Build UniFi Network v1.0.8 build 9 over immutable build-8 history."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_unifi as base
import build_first_party_unifi_b8 as previous

MODULE_ID = "com.sickicarus.monitorbox.unifi"
MODULE_VERSION = "1.0.8"
MODULE_BUILD = 9
IMPORT_PACKAGE = "monitorbox_unifi_b9"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD9_SOURCE_BLOBS = {
    "phase3_recovery.py": "5a1bbf85f28f75fa789525634d75dc56ed3aa4a6",
}


def _git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    source_root = root / "sources" / "unifi" / "1.0.8-build9"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != set(BUILD9_SOURCE_BLOBS):
        raise SystemExit(
            "UniFi 1.0.8 build-9 delta shape changed: "
            f"missing={sorted(set(BUILD9_SOURCE_BLOBS)-actual)}, "
            f"extra={sorted(actual-set(BUILD9_SOURCE_BLOBS))}"
        )
    for name, expected_blob in BUILD9_SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UniFi build-9 source blob changed for {name}: "
                f"expected {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
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

        import_seam = "import aiohttp\n\n"
        if text.count(import_seam) != 1:
            raise SystemExit("UniFi build-9 runtime import seam changed")
        text = text.replace(
            import_seam,
            import_seam + "from .phase3_recovery import annotate_inventory_provenance\n\n",
            1,
        )

        provenance_seam = (
            '        if vpn_expectations:\n'
            '            metadata["vpn_components"] = self._vpn_components(vpns, vpn_expectations)\n'
            '        state = State.DEGRADED if offline_count or degraded_count else State.HEALTHY\n'
        )
        if text.count(provenance_seam) != 1:
            raise SystemExit("UniFi build-9 inventory provenance seam changed")
        text = text.replace(
            provenance_seam,
            '        if vpn_expectations:\n'
            '            metadata["vpn_components"] = self._vpn_components(vpns, vpn_expectations)\n'
            '        annotate_inventory_provenance(metadata, request.check_id)\n'
            '        state = State.DEGRADED if offline_count or degraded_count else State.HEALTHY\n',
            1,
        )

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
    payload = base._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"build9_sources={len(BUILD9_SOURCE_BLOBS)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
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
