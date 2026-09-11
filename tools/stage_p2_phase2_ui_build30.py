#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

PREDECESSOR = ("com.sickicarus.monitorbox.ui", "1.1.14", 27)
RELEASE = ("com.sickicarus.monitorbox.ui", "1.1.17", 30)

ENTRY = {
    "manifest": {
        "module_id": "com.sickicarus.monitorbox.ui",
        "display_name": "MonitorBox UI",
        "description": "MonitorBox web interface, shared application shell, and operator presentation.",
        "version": "1.1.17",
        "build": 30,
        "schema": 1,
        "state_schema": 1,
        "module_type": "ui",
        "entrypoints": {"webui": "monitorbox_ui_b30:install"},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    },
    "package": "com.sickicarus.monitorbox.ui-1.1.17-build30.zip",
}


def identity(item):
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
    matches = [item for item in modules if identity(item) == RELEASE]
    if matches:
        if len(matches) != 1 or matches[0] != ENTRY:
            raise SystemExit("UI build 30 catalog conflict")
        return False
    indexes = [index for index, item in enumerate(modules) if identity(item) == PREDECESSOR]
    if len(indexes) != 1:
        raise SystemExit(f"expected one UI trunk predecessor, found {len(indexes)}")
    modules.insert(indexes[0] + 1, ENTRY)
    path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged UI 1.1.17 build 30")
    return True


def main() -> None:
    stage(Path(__file__).resolve().parent.parent / "catalog.source.json")


if __name__ == "__main__":
    main()
