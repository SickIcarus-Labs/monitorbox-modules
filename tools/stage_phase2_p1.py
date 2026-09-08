#!/usr/bin/env python3
"""Idempotently stage the September 7 P1 Phase-2 module release set.

The three candidates share one catalog mutation pass but remain independent
semantic releases with their own immutable builders and release intents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RELEASES = (
    {
        "predecessor": ("com.sickicarus.monitorbox.ui", "1.1.4", 12),
        "release": ("com.sickicarus.monitorbox.ui", "1.1.5", 13),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.ui",
                "display_name": "MonitorBox UI",
                "version": "1.1.5",
                "build": 13,
                "schema": 1,
                "state_schema": 1,
                "module_type": "ui",
                "entrypoints": {"webui": "monitorbox_ui_b13:install"},
                "requires_core": ">=2.3.1 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "required",
            },
            "package": "com.sickicarus.monitorbox.ui-1.1.5-build13.zip",
        },
    },
    {
        "predecessor": ("com.sickicarus.monitorbox.portainer", "1.1.0", 6),
        "release": ("com.sickicarus.monitorbox.portainer", "1.1.1", 7),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.portainer",
                "display_name": "Portainer Integration",
                "version": "1.1.1",
                "build": 7,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_portainer_b7:PLUGIN"},
                "requires_core": ">=2.3.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
            },
            "package": "com.sickicarus.monitorbox.portainer-1.1.1-build7.zip",
        },
    },
    {
        "predecessor": ("com.sickicarus.monitorbox.unifi", "1.0.3", 4),
        "release": ("com.sickicarus.monitorbox.unifi", "1.0.4", 5),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.unifi",
                "display_name": "UniFi Network Integration",
                "version": "1.0.4",
                "build": 5,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_unifi_b5:PLUGIN"},
                "requires_core": ">=2.3.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
            },
            "package": "com.sickicarus.monitorbox.unifi-1.0.4-build5.zip",
        },
    },
)


def identity(item: dict[str, Any]) -> tuple[str, str, int]:
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
    for spec in RELEASES:
        release = spec["release"]
        entry = spec["entry"]
        existing = [item for item in modules if identity(item) == release]
        if existing:
            if len(existing) != 1 or existing[0] != entry:
                raise SystemExit(f"catalog release conflicts with Phase-2 contract: {release}")
            continue

        predecessor = spec["predecessor"]
        indexes = [index for index, item in enumerate(modules) if identity(item) == predecessor]
        if len(indexes) != 1:
            raise SystemExit(
                f"expected exactly one immutable predecessor {predecessor}, found {len(indexes)}"
            )
        modules.insert(indexes[0] + 1, entry)
        changed = True

    if changed:
        path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
        print("staged September 7 P1 Phase-2 UI, Portainer, and UniFi candidates")
    else:
        print("September 7 P1 Phase-2 candidates already staged")
    return changed


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
