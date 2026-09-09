#!/usr/bin/env python3
"""Idempotently stage the #249 crash-atomic Backup / Restore release."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PREDECESSOR = ("com.sickicarus.monitorbox.backup-restore", "1.0.2", 3)
RELEASE = ("com.sickicarus.monitorbox.backup-restore", "1.0.3", 4)
ENTRY = {
    "manifest": {
        "module_id": "com.sickicarus.monitorbox.backup-restore",
        "display_name": "Backup / Restore",
        "version": "1.0.3",
        "build": 4,
        "schema": 1,
        "state_schema": 1,
        "module_type": "recovery",
        "entrypoints": {"recovery": "monitorbox_backup_restore_b4:install"},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [
            "recovery.snapshot",
            "recovery.inspect",
            "recovery.schedule",
            "recovery.destination",
            "saved-backup-vault",
        ],
        "lifecycle_policy": "optional",
    },
    "package": "com.sickicarus.monitorbox.backup-restore-1.0.3-build4.zip",
}


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

    existing = [item for item in modules if identity(item) == RELEASE]
    if existing:
        if len(existing) != 1 or existing[0] != ENTRY:
            raise SystemExit(f"catalog release conflicts with #249 contract: {RELEASE}")
        print("#249 Backup / Restore 1.0.3 build 4 already staged")
        return False

    indexes = [index for index, item in enumerate(modules) if identity(item) == PREDECESSOR]
    if len(indexes) != 1:
        raise SystemExit(
            f"expected exactly one immutable predecessor {PREDECESSOR}, found {len(indexes)}"
        )
    modules.insert(indexes[0] + 1, ENTRY)
    path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged #249 Backup / Restore 1.0.3 build 4")
    return True


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
