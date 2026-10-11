#!/usr/bin/env python3
"""Stage unsigned successor Backup/Restore candidate without touching feeds.

This is an *unpromoted* v3-only major release candidate, not a completed
restore product. The release-policy job may run this idempotently in a
scratch publisher checkout, but no cryptographic signing occurs here.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = "com.sickicarus.monitorbox.backup-restore"
PREVIOUS = (MODULE, "1.0.5", 6)
CURRENT = (MODULE, "2.0.0", 7)
ENTRY = {
    "manifest": {
        "module_id": MODULE,
        "display_name": "Backup / Restore",
        "description": "Unsigned native v3 Full ZIP Backup/Restore candidate; restore is disabled pending P0 acceptance.",
        "version": "2.0.0",
        "build": 7,
        "schema": 1,
        "state_schema": 1,
        "module_type": "recovery",
        "entrypoints": {"recovery": "monitorbox_backup_restore_b7:install"},
        "requires_core": ">=3.0.0 <4.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [
            "recovery.snapshot", "recovery.inspect", "recovery.schedule",
            "recovery.destination", "saved-backup-vault",
        ],
        "lifecycle_policy": "optional",
    },
    "package": MODULE + "-2.0.0-build7.zip",
}


def identity(row: dict) -> tuple[str, str, int]:
    item = row.get("manifest", {})
    return (str(item.get("module_id") or ""), str(item.get("version") or ""),
            int(item.get("build") or 0))


def stage(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = data.get("modules")
    if not isinstance(modules, list):
        raise ValueError("module catalog has no module inventory")
    present = [row for row in modules if identity(row) == CURRENT]
    if present:
        if len(present) != 1 or present[0] != ENTRY:
            raise ValueError("conflicting signed-catalog B7 candidate; refusing rewrite")
        return False
    predecessor = [i for i, row in enumerate(modules) if identity(row) == PREVIOUS]
    if len(predecessor) != 1:
        raise ValueError("must preserve exactly one historical signed B6 predecessor")
    modules.insert(predecessor[0]+1, ENTRY)
    path.write_text(json.dumps(data, separators=(",", ":"))+"\n", encoding="utf-8")
    print("staged unsigned Backup/Restore v3 2.0.0 build7 candidate; DO NOT PUBLISH")
    return True


if __name__ == "__main__":
    stage(ROOT / "catalog.source.json")
