#!/usr/bin/env python3
"""Idempotently stage SNMP 1.0.5/build7 and Scrypted 2.1.2/build3."""

from __future__ import annotations

import json
from pathlib import Path

SNMP_ID = "com.sickicarus.monitorbox.snmp"
SCRYPTED_ID = "com.sickicarus.monitorbox.scrypted"

RELEASES = (
    (
        (SNMP_ID, "1.0.4", 6),
        (SNMP_ID, "1.0.5", 7),
        {
            "manifest": {
                "module_id": SNMP_ID,
                "display_name": "SNMP Integration",
                "version": "1.0.5",
                "build": 7,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_snmp_v105_b7:PLUGIN"},
                "requires_core": ">=2.3.1 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
            },
            "package": "com.sickicarus.monitorbox.snmp-1.0.5-build7.zip",
        },
    ),
    (
        (SCRYPTED_ID, "2.1.1", 2),
        (SCRYPTED_ID, "2.1.2", 3),
        {
            "manifest": {
                "module_id": SCRYPTED_ID,
                "display_name": "Scrypted Integration",
                "version": "2.1.2",
                "build": 3,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_scrypted_v212_b3:PLUGIN"},
                "requires_core": ">=2.3.1 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
            },
            "package": "com.sickicarus.monitorbox.scrypted-2.1.2-build3.zip",
        },
    ),
)


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

    changed = False
    for predecessor, release, entry in RELEASES:
        existing = [item for item in modules if identity(item) == release]
        if existing:
            if len(existing) != 1 or existing[0] != entry:
                raise SystemExit(f"catalog release conflicts with repair contract: {release}")
            print(f"{release[0]} {release[1]} build {release[2]} already staged")
            continue
        indexes = [index for index, item in enumerate(modules) if identity(item) == predecessor]
        if len(indexes) != 1:
            raise SystemExit(
                f"expected exactly one predecessor {predecessor}, found {len(indexes)}"
            )
        modules.insert(indexes[0] + 1, entry)
        changed = True
        print(
            f"staged {release[0]} {release[1]} build {release[2]} "
            f"after immutable {predecessor[1]} build {predecessor[2]}"
        )

    if changed:
        path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
