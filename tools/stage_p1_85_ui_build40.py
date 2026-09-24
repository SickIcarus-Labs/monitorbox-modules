#!/usr/bin/env python3
"""Stage signed-dev successor UI build40 with required Core card contract; no 36-38 lineage."""

from __future__ import annotations

import json
from pathlib import Path

PREDECESSOR = ("com.sickicarus.monitorbox.ui", "1.3.1", 35)
RELEASE = ("com.sickicarus.monitorbox.ui", "1.4.1", 40)

ENTRY = {
    "manifest": {
        "module_id": "com.sickicarus.monitorbox.ui",
        "display_name": "MonitorBox UI",
        "description": "MonitorBox web interface, shared shell and operator presentation.",
        "version": "1.4.1",
        "build": 40,
        "schema": 1,
        "state_schema": 1,
        "module_type": "ui",
        "entrypoints": {"webui": "monitorbox_ui_b40:install"},
        "requires_core": ">=2.6.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    },
    "package": "com.sickicarus.monitorbox.ui-1.4.1-build40.zip",
}


def identity(entry: dict) -> tuple[str, str, int]:
    manifest = entry.get("manifest", {})
    return (
        str(manifest.get("module_id") or ""),
        str(manifest.get("version") or ""),
        int(manifest.get("build") or 0),
    )


def stage(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = data.get("modules")
    if not isinstance(modules, list):
        raise SystemExit("catalog.source.json has no modules list")
    matches = [entry for entry in modules if identity(entry) == RELEASE]
    if matches:
        if len(matches) != 1 or matches[0] != ENTRY:
            raise SystemExit("UI build40 catalog conflict")
        return False
    indexes = [index for index, entry in enumerate(modules) if identity(entry) == PREDECESSOR]
    if len(indexes) != 1:
        raise SystemExit(
            f"expected one accepted UI build35 predecessor, found {len(indexes)}"
        )
    modules.insert(indexes[0] + 1, ENTRY)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged isolated UI 1.4.1 build40")
    return True


def main() -> None:
    stage(Path(__file__).resolve().parent.parent / "catalog.source.json")


if __name__ == "__main__":
    main()
