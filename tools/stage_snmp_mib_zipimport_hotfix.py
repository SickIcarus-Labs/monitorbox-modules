#!/usr/bin/env python3
"""Idempotently stage the SNMP 1.0.4/build-6 MIB zipimport hotfix."""

from __future__ import annotations

import json
from pathlib import Path

MODULE_ID = "com.sickicarus.monitorbox.snmp"
PREVIOUS = (MODULE_ID, "1.0.4", 5)
HOTFIX = (MODULE_ID, "1.0.4", 6)
HOTFIX_ENTRY = {
    "manifest": {
        "module_id": MODULE_ID,
        "display_name": "SNMP Integration",
        "version": "1.0.4",
        "build": 6,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": "monitorbox_snmp_b6:PLUGIN"},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    },
    "package": "com.sickicarus.monitorbox.snmp-1.0.4-build6.zip",
}


def identity(item: dict) -> tuple[str, str, int]:
    manifest = item.get("manifest", {})
    return (
        str(manifest.get("module_id") or ""),
        str(manifest.get("version") or ""),
        int(manifest.get("build") or 0),
    )


def stage(path: Path) -> bool:
    source = json.loads(path.read_text(encoding="utf-8"))
    modules = source.get("modules")
    if not isinstance(modules, list):
        raise SystemExit("catalog.source.json has no modules list")

    existing = [item for item in modules if identity(item) == HOTFIX]
    if existing:
        if len(existing) != 1 or existing[0] != HOTFIX_ENTRY:
            raise SystemExit("SNMP 1.0.4 build 6 catalog entry conflicts with the hotfix contract")
        print("SNMP 1.0.4 build 6 already staged")
        return False

    previous_indexes = [index for index, item in enumerate(modules) if identity(item) == PREVIOUS]
    if len(previous_indexes) != 1:
        raise SystemExit(
            f"expected exactly one SNMP 1.0.4 build 5 release, found {len(previous_indexes)}"
        )
    modules.insert(previous_indexes[0] + 1, HOTFIX_ENTRY)
    path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged SNMP 1.0.4 build 6 after immutable build 5")
    return True


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
