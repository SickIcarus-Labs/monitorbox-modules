#!/usr/bin/env python3
"""Idempotently stage the September 8 P1 Phase-2 physical-repair release set.

Four module release units share one catalog mutation pass. Configuration/Bootstrap
1.0.3 build 4 and Portainer 1.1.1 build 7 retain their accepted candidates.
UI 1.1.6 build 14 and UniFi 1.0.5 build 6 supersede physically rejected
signed-dev builds 13 and 5 respectively; those rejected dev builds remain signed
dev history but are intentionally not materialized into the graduating catalog.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RELEASES = (
    {
        "predecessor": ("com.sickicarus.monitorbox.configuration-bootstrap", "1.0.1", 2),
        "release": ("com.sickicarus.monitorbox.configuration-bootstrap", "1.0.3", 4),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.configuration-bootstrap",
                "display_name": "Configuration / Bootstrap",
                "version": "1.0.3",
                "build": 4,
                "schema": 1,
                "state_schema": 1,
                "module_type": "configuration",
                "entrypoints": {"configuration": "monitorbox_configuration_bootstrap_b4:install"},
                "requires_core": ">=2.3.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "required",
            },
            "package": "com.sickicarus.monitorbox.configuration-bootstrap-1.0.3-build4.zip",
        },
    },
    {
        "predecessor": ("com.sickicarus.monitorbox.ui", "1.1.4", 12),
        "release": ("com.sickicarus.monitorbox.ui", "1.1.6", 14),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.ui",
                "display_name": "MonitorBox UI",
                "version": "1.1.6",
                "build": 14,
                "schema": 1,
                "state_schema": 1,
                "module_type": "ui",
                "entrypoints": {"webui": "monitorbox_ui_b14:install"},
                "requires_core": ">=2.3.1 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "required",
            },
            "package": "com.sickicarus.monitorbox.ui-1.1.6-build14.zip",
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
        "release": ("com.sickicarus.monitorbox.unifi", "1.0.5", 6),
        "entry": {
            "manifest": {
                "module_id": "com.sickicarus.monitorbox.unifi",
                "display_name": "UniFi Network Integration",
                "version": "1.0.5",
                "build": 6,
                "schema": 1,
                "state_schema": 1,
                "module_type": "integration",
                "entrypoints": {"integration": "monitorbox_unifi_b6:PLUGIN"},
                "requires_core": ">=2.3.0 <3.0.0",
                "requires_runtime_api": ">=1 <2",
                "dependencies": [],
                "publisher_id": "com.sickicarus",
                "permissions": [],
                "lifecycle_policy": "optional",
            },
            "package": "com.sickicarus.monitorbox.unifi-1.0.5-build6.zip",
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
        print("staged September 8 P1 Phase-2 Bootstrap, UI, Portainer, and UniFi candidates")
    else:
        print("September 8 P1 Phase-2 candidates already staged")
    return changed


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
