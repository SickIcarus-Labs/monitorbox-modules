#!/usr/bin/env python3
"""Focused current-catalog acceptance for Scrypted 2.1 media release."""

from __future__ import annotations

import json
from pathlib import Path

import accept_repository_scrypted as scrypted


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    source = json.loads((root / "catalog.source.json").read_text())
    identities = {
        scrypted.stable._release_identity(item)
        for item in source.get("modules", [])
        if item.get("manifest", {}).get("module_id") == scrypted.SCRYPTED_ID
    }
    expected = {scrypted.SCRYPTED_V1, scrypted.SCRYPTED_V2, scrypted.SCRYPTED_V21}
    if identities != expected:
        raise AssertionError(
            f"expected current Scrypted releases {sorted(expected)}, got {sorted(identities)}"
        )
    scrypted._validate_v1(root, source)
    scrypted._validate_worker_release(
        root,
        source,
        scrypted.SCRYPTED_V2,
        scrypted.IMPORT_V2,
        media=False,
    )
    scrypted._validate_worker_release(
        root,
        source,
        scrypted.SCRYPTED_V21,
        scrypted.IMPORT_V21,
        media=True,
    )
    print("Current Scrypted catalog + 2.1 media package shape: PASS", flush=True)


if __name__ == "__main__":
    main()
