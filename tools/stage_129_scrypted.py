#!/usr/bin/env python3
"""Stage Scrypted 2.2.0 build 5 signed capability-discovery release."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODULE_ID = "com.sickicarus.monitorbox.scrypted"
PREDECESSOR = (MODULE_ID, "2.1.3", 4)
RELEASE = (MODULE_ID, "2.2.0", 5)
CAPABILITY_DETECTION = {
    "schema": 2,
    "discovery_hints": {"schema": 1, "tcp_ports": [10443, 11080]},
    "matches": [
        {
            "id": "workload-image",
            "confidence": "detected",
            "all": [
                {"fact": "workload.image", "op": "contains", "value": "/scrypted"}
            ],
        },
        {
            "id": "compose-service",
            "confidence": "detected",
            "all": [
                {"fact": "workload.compose_service", "op": "equals", "value": "scrypted"}
            ],
        },
        {
            "id": "management-port",
            "confidence": "possible",
            "all": [
                {"fact": "network.port", "op": "equals", "value": "10443"}
            ],
        },
        {
            "id": "http-port",
            "confidence": "possible",
            "all": [
                {"fact": "network.port", "op": "equals", "value": "11080"}
            ],
        },
    ],
}
ENTRY = {
    "manifest": {
        "module_id": MODULE_ID,
        "display_name": "Scrypted Integration",
        "description": "Monitors Scrypted service health and camera availability, snapshots, and streams.",
        "version": "2.2.0",
        "build": 5,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": "monitorbox_scrypted_v220_b5:PLUGIN"},
        "requires_core": ">=2.4.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
        "capability_detection": CAPABILITY_DETECTION,
    },
    "package": "com.sickicarus.monitorbox.scrypted-2.2.0-build5.zip",
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
            raise SystemExit(f"catalog release conflicts with #129 contract: {RELEASE}")
        print("Scrypted 2.2.0 build 5 already staged")
        return False
    indexes = [index for index, item in enumerate(modules) if identity(item) == PREDECESSOR]
    if len(indexes) != 1:
        raise SystemExit(
            f"expected exactly one immutable Scrypted predecessor {PREDECESSOR}, found {len(indexes)}"
        )
    modules.insert(indexes[0] + 1, ENTRY)
    path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged Scrypted 2.2.0 build 5")
    return True


def main() -> None:
    stage(Path(__file__).resolve().parent.parent / "catalog.source.json")


if __name__ == "__main__":
    main()
