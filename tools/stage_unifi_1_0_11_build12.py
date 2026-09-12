#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

PREDECESSOR = ("com.sickicarus.monitorbox.unifi", "1.0.9", 10)
RELEASE = ("com.sickicarus.monitorbox.unifi", "1.0.11", 12)
ENTRY = {
    "manifest": {
        "module_id": "com.sickicarus.monitorbox.unifi",
        "display_name": "UniFi Network Integration",
        "version": "1.0.11",
        "build": 12,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": "monitorbox_unifi_b12:PLUGIN"},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    },
    "package": "com.sickicarus.monitorbox.unifi-1.0.11-build12.zip",
}


def identity(item):
    manifest = item.get("manifest", {})
    return (str(manifest.get("module_id") or ""), str(manifest.get("version") or ""), int(manifest.get("build") or 0))


def stage(path: Path) -> bool:
    source = json.loads(path.read_text(encoding="utf-8"))
    modules = source.get("modules")
    if not isinstance(modules, list):
        raise SystemExit("catalog.source.json has no modules list")
    matches = [item for item in modules if identity(item) == RELEASE]
    if matches:
        if len(matches) != 1 or matches[0] != ENTRY:
            raise SystemExit("UniFi build 12 catalog conflict")
        return False
    indexes = [index for index, item in enumerate(modules) if identity(item) == PREDECESSOR]
    if len(indexes) != 1:
        raise SystemExit(f"expected one UniFi trunk predecessor, found {len(indexes)}")
    modules.insert(indexes[0] + 1, ENTRY)
    path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged UniFi 1.0.11 build 12")
    return True


def main() -> None:
    stage(Path(__file__).resolve().parent.parent / "catalog.source.json")


if __name__ == "__main__":
    main()
