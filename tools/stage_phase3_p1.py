#!/usr/bin/env python3
"""Idempotently stage the September 8 P1 Phase-3 UI + UniFi release set.

Trunk/stable history intentionally trails accepted dev/beta module confidence
history. The release intents separately identify the exact signed-dev semantic
predecessors; this stager therefore inserts each Phase-3 candidate after the
latest immutable trunk predecessor without materializing intermediate dev-only
releases into the stable/trunk catalog.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RELEASES = (
    {
        "predecessor": ("com.sickicarus.monitorbox.ui", "1.1.4", 12),
        "release": ("com.sickicarus.monitorbox.ui", "1.1.11", 19),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.ui",
                "display_name": "MonitorBox UI",
                "version": "1.1.11",
                "build": 19,
                "schema": 1,
                "state_schema": 1,
                "module_type": "ui",
                "entrypoints": {"webui": "monitorbox_ui_b19:install"},
                "requires_core": ">=2.3.1 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "required",
            },
            "package": "com.sickicarus.monitorbox.ui-1.1.11-build19.zip",
        },
    },
    {
        "predecessor": ("com.sickicarus.monitorbox.unifi", "1.0.3", 4),
        "release": ("com.sickicarus.monitorbox.unifi", "1.0.8", 9),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.unifi",
                "display_name": "UniFi Network Integration",
                "version": "1.0.8",
                "build": 9,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_unifi_b9:PLUGIN"},
                "requires_core": ">=2.3.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
            },
            "package": "com.sickicarus.monitorbox.unifi-1.0.8-build9.zip",
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
                raise SystemExit(f"catalog release conflicts with Phase-3 contract: {release}")
            continue

        predecessor = spec["predecessor"]
        indexes = [index for index, item in enumerate(modules) if identity(item) == predecessor]
        if len(indexes) != 1:
            raise SystemExit(
                f"expected exactly one immutable trunk predecessor {predecessor}, found {len(indexes)}"
            )
        modules.insert(indexes[0] + 1, entry)
        changed = True

    if changed:
        path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
        print("staged September 8 P1 Phase-3 UI and UniFi candidates")
    else:
        print("September 8 P1 Phase-3 candidates already staged")
    return changed


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
