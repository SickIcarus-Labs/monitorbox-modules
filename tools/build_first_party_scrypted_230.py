#!/usr/bin/env python3
"""Build Scrypted 2.3.0 build 6 provider-owned bootstrap-discovery release."""
from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_scrypted as base
import build_first_party_scrypted_220 as previous

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "2.3.0"
MODULE_BUILD = 6
IMPORT_PACKAGE = "monitorbox_scrypted_v230_b6"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = previous.FILENAME
SOURCE_DELTA = "2.3.0-build6"
DISCOVERY_CONTRACT_BLOB = "8f8c3fce4fff7b796292c1e178978ffd16782cfd"


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

    def source_files_build6(root: Path) -> dict[str, bytes]:
        files = original_source_files(root)
        contract = root / "sources" / "scrypted" / SOURCE_DELTA / "discovery_contract.json"
        payload = contract.read_bytes()
        actual = base._git_blob_sha(payload)
        if actual != DISCOVERY_CONTRACT_BLOB:
            raise SystemExit(
                f"Scrypted 2.3.0 discovery-contract drift: expected {DISCOVERY_CONTRACT_BLOB}, got {actual}"
            )
        return files

    def rewrite_build6(name: str, payload: bytes) -> bytes:
        text = original_rewrite(name, payload).decode("utf-8")
        if name == "onboarding.py":
            old = '''                DiscoveryEvidence(\n                    plugin_id="scrypted",\n                    connection_plugin_id="http",\n                    system_id=request.system_id,\n                    kind="http",\n                    label=hint,\n                    endpoint=endpoint,\n                    confidence=DiscoveryConfidence.POSSIBLE,\n                    evidence=f"TCP/{port} is open; product identity requires validation",\n                    default_selected=False,\n                    values={"url": endpoint},\n                )'''
            new = '''                DiscoveryEvidence(\n                    plugin_id="scrypted",\n                    system_id=request.system_id,\n                    kind="scrypted",\n                    label=hint,\n                    endpoint=endpoint,\n                    confidence=DiscoveryConfidence.POSSIBLE,\n                    evidence=f"TCP/{port} is open; Scrypted identity requires provider validation",\n                    default_selected=False,\n                    values={"base_url": endpoint},\n                )'''
            text = _replace_once(text, old, new, "Scrypted provider-owned possible discovery")
            if 'connection_plugin_id="http"' in text:
                raise SystemExit("Scrypted build 6 still delegates discovery candidates to HTTP")
        return text.encode("utf-8")

    base._python_source_files = source_files_build6
    base._rewrite_source = rewrite_build6


def build(root: Path, output_dir: Path) -> Path:
    previous_package = output_dir / PREVIOUS_FILENAME
    if not previous_package.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous_package}; build 6 must not recreate build 5"
        )
    _configure()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected Scrypted 2.3.0 build-6 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
