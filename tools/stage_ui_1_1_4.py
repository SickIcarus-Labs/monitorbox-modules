#!/usr/bin/env python3
"""Idempotently stage MonitorBox UI 1.1.4 build 12 after immutable build 11."""

from __future__ import annotations

import json
from pathlib import Path

MODULE_ID = "com.sickicarus.monitorbox.ui"
PREDECESSOR = (MODULE_ID, "1.1.3", 11)
RELEASE = (MODULE_ID, "1.1.4", 12)
ENTRY = {
    "manifest": {
        "module_id": MODULE_ID,
        "display_name": "MonitorBox UI",
        "version": "1.1.4",
        "build": 12,
        "schema": 1,
        "state_schema": 1,
        "module_type": "ui",
        "entrypoints": {"webui": "monitorbox_ui_b12:install"},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    },
    "package": "com.sickicarus.monitorbox.ui-1.1.4-build12.zip",
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

    existing = [item for item in modules if identity(item) == RELEASE]
    if existing:
        if len(existing) != 1 or existing[0] != ENTRY:
            raise SystemExit(f"catalog release conflicts with UI release contract: {RELEASE}")
        print("MonitorBox UI 1.1.4 build 12 already staged")
        return False

    indexes = [index for index, item in enumerate(modules) if identity(item) == PREDECESSOR]
    if len(indexes) != 1:
        raise SystemExit(f"expected exactly one immutable predecessor {PREDECESSOR}, found {len(indexes)}")
    modules.insert(indexes[0] + 1, ENTRY)
    path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged MonitorBox UI 1.1.4 build 12 after immutable 1.1.3 build 11")
    return True


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
