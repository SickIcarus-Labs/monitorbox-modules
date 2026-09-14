#!/usr/bin/env python3
"""Build UniFi Network v1.0.9 build 10 over immutable build-9 history."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_unifi_b9 as previous

MODULE_ID = "com.sickicarus.monitorbox.unifi"
MODULE_VERSION = "1.0.9"
MODULE_BUILD = 10
IMPORT_PACKAGE = "monitorbox_unifi_b10"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD10_SOURCE_BLOBS = {
    "phase2_policy.py": "60fa36cd1dbb16f098625d105ae7a54a4a9ebb39",
}


def _git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    source_root = root / "sources" / "unifi" / "1.0.9-build10"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != set(BUILD10_SOURCE_BLOBS):
        raise SystemExit(
            "UniFi 1.0.9 build-10 delta shape changed: "
            f"missing={sorted(set(BUILD10_SOURCE_BLOBS)-actual)}, "
            f"extra={sorted(actual-set(BUILD10_SOURCE_BLOBS))}"
        )
    for name, expected_blob in BUILD10_SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UniFi build-10 source blob changed for {name}: "
                f"expected {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    # Reuse build 9's complete managed-namespace/provenance rewrite, then advance
    # only this candidate's immutable package identity.
    text = previous._rewrite_source(name, payload).decode("utf-8")

    if name in {"__init__.py", "runtime.py"}:
        old_entrypoint = f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}'
        new_entrypoint = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
        if text.count(old_entrypoint) != 1:
            raise SystemExit(f"UniFi build-10 entrypoint seam changed in {name}")
        text = text.replace(old_entrypoint, new_entrypoint, 1)

    if name == "runtime.py":
        old_version = f'MODULE_VERSION = "{previous.MODULE_VERSION}"'
        old_build = f"MODULE_BUILD = {previous.MODULE_BUILD}"
        if text.count(old_version) != 1 or text.count(old_build) != 1:
            raise SystemExit("UniFi build-10 predecessor identity markers changed")
        text = text.replace(old_version, f'MODULE_VERSION = "{MODULE_VERSION}"', 1)
        text = text.replace(old_build, f"MODULE_BUILD = {MODULE_BUILD}", 1)

    if f"{previous.IMPORT_PACKAGE}:PLUGIN" in text:
        raise SystemExit(f"UniFi build-10 retained predecessor entrypoint in {name}")
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _source_files(root).items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = previous.base._zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"build10_sources={len(BUILD10_SOURCE_BLOBS)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
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
