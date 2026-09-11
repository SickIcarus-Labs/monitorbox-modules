#!/usr/bin/env python3
"""Build UniFi Network v1.0.10 build 11 over immutable build-10 history.

Build 11 preserves authoritative wired-topology peer context on recommended
infrastructure ports so provider-neutral UI can explain *why* a port is
recommended without inferring topology from names, speeds, or port numbers.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_unifi as base
import build_first_party_unifi_b10 as previous

MODULE_ID = "com.sickicarus.monitorbox.unifi"
MODULE_VERSION = "1.0.10"
MODULE_BUILD = 11
IMPORT_PACKAGE = "monitorbox_unifi_b11"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
BUILD11_SOURCE_BLOBS = {
    "recommendation_relationship.py": "2785e57a851da426d1fb6f2b6215c9fa96aacc35",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _source_files(root: Path) -> dict[str, bytes]:
    result = dict(previous._source_files(root))
    source_root = root / "sources" / "unifi" / "1.0.10-build11"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != set(BUILD11_SOURCE_BLOBS):
        raise SystemExit(
            "UniFi 1.0.10 build-11 delta shape changed: "
            f"missing={sorted(set(BUILD11_SOURCE_BLOBS)-actual)}, "
            f"extra={sorted(actual-set(BUILD11_SOURCE_BLOBS))}"
        )
    for name, expected_blob in BUILD11_SOURCE_BLOBS.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"UniFi build-11 source blob changed for {name}: "
                f"expected {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _replace_once(text: str, old: str, new: str, seam: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"UniFi build-11 {seam} seam changed")
    return text.replace(old, new, 1)


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = previous._rewrite_source(name, payload).decode("utf-8")

    if name in {"__init__.py", "runtime.py"}:
        old_entrypoint = f'entrypoints={{"integration": "{previous.IMPORT_PACKAGE}:PLUGIN"}}'
        new_entrypoint = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
        if text.count(old_entrypoint) != 1:
            raise SystemExit(f"UniFi build-11 entrypoint seam changed in {name}")
        text = text.replace(old_entrypoint, new_entrypoint, 1)

    if name == "runtime.py":
        old_version = f'MODULE_VERSION = "{previous.MODULE_VERSION}"'
        old_build = f"MODULE_BUILD = {previous.MODULE_BUILD}"
        if text.count(old_version) != 1 or text.count(old_build) != 1:
            raise SystemExit("UniFi build-11 predecessor identity markers changed")
        text = text.replace(old_version, f'MODULE_VERSION = "{MODULE_VERSION}"', 1)
        text = text.replace(old_build, f"MODULE_BUILD = {MODULE_BUILD}", 1)

    if name == "phase2_policy.py":
        text = _replace_once(
            text,
            "from .discovery_runtime import UniFiRuntimeExecutor as _BaseUniFiRuntimeExecutor\n",
            "from .discovery_runtime import UniFiRuntimeExecutor as _BaseUniFiRuntimeExecutor\n"
            "from .recommendation_relationship import annotate_port_recommendation_relationships\n",
            "relationship import",
        )
        text = _replace_once(
            text,
            '        ports = _enrich_port_roles(metadata.get("ports", []), raw_devices, raw_topology)\n'
            '        health = metadata.get("health", [])\n',
            '        ports = _enrich_port_roles(metadata.get("ports", []), raw_devices, raw_topology)\n'
            '        annotate_port_recommendation_relationships(ports, raw_devices, raw_topology)\n'
            '        health = metadata.get("health", [])\n',
            "relationship projection",
        )

    if name == "discovery.py":
        text = _replace_once(
            text,
            '                        "initial_importance": initial_importance,\n',
            '                        "initial_importance": initial_importance,\n'
            '                        "recommendation_reason": port.get("recommendation_reason"),\n'
            '                        "recommendation_relationship": port.get("recommendation_relationship"),\n',
            "discovery recommendation metadata",
        )

    if f"{previous.IMPORT_PACKAGE}:PLUGIN" in text:
        raise SystemExit(f"UniFi build-11 retained predecessor entrypoint in {name}")
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
        f"build11_sources={len(BUILD11_SOURCE_BLOBS)} entrypoint={IMPORT_PACKAGE}:PLUGIN"
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
