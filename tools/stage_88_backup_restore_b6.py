#!/usr/bin/env python3
"""Stage exact B/R 1.0.5 build6 development candidate after accepted b5."""
from __future__ import annotations

import json
from pathlib import Path

PREVIOUS = ("com.sickicarus.monitorbox.backup-restore", "1.0.4", 5)
RELEASE = ("com.sickicarus.monitorbox.backup-restore", "1.0.5", 6)
ENTRY = {
    "manifest": {
        "module_id": "com.sickicarus.monitorbox.backup-restore",
        "display_name": "Backup / Restore",
        "version": "1.0.5",
        "build": 6,
        "schema": 1,
        "state_schema": 1,
        "module_type": "recovery",
        "entrypoints": {"recovery": "monitorbox_backup_restore_b6:install"},
        "requires_core": ">=2.6.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [
            "recovery.snapshot", "recovery.inspect", "recovery.schedule",
            "recovery.destination", "saved-backup-vault"
        ],
        "lifecycle_policy": "optional"
    },
    "package": "com.sickicarus.monitorbox.backup-restore-1.0.5-build6.zip"
}

def identity(row: dict) -> tuple[str, str, int]:
    manifest = row.get("manifest", {})
    return (
        str(manifest.get("module_id") or ""),
        str(manifest.get("version") or ""),
        int(manifest.get("build") or 0),
    )

def stage(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("modules")
    if not isinstance(entries, list):
        raise SystemExit("catalog.source.json is missing modules")
    already = [item for item in entries if identity(item) == RELEASE]
    if already:
        if len(already) != 1 or already[0] != ENTRY:
            raise SystemExit("conflicting Backup/Restore b6 candidate")
        return False
    prior = [index for index, item in enumerate(entries) if identity(item) == PREVIOUS]
    if len(prior) != 1:
        raise SystemExit("expected one exact B/R b5 predecessor")
    entries.insert(prior[0] + 1, ENTRY)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged Backup/Restore 1.0.5 build6")
    return True

if __name__ == "__main__":
    stage(Path(__file__).resolve().parent.parent / "catalog.source.json")
