#!/usr/bin/env python3
"""Stage Phase-6B HTTP 1.0.1 build 2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODULE_ID = "com.sickicarus.monitorbox.http"
PREDECESSOR = (MODULE_ID, "1.0.0", 1)
RELEASE = (MODULE_ID, "1.0.1", 2)
ENTRY = {
    "manifest": {
        "module_id": MODULE_ID,
        "display_name": "HTTP(S) Integration",
        "version": "1.0.1",
        "build": 2,
        "schema": 1,
        "state_schema": 1,
        "module_type": "integration",
        "entrypoints": {"integration": "monitorbox_http_v101_b2:PLUGIN"},
        "requires_core": ">=2.3.1 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "optional",
    },
    "package": "com.sickicarus.monitorbox.http-1.0.1-build2.zip",
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
            raise SystemExit(f"catalog release conflicts with Phase-6B contract: {RELEASE}")
        print("HTTP 1.0.1 build 2 already staged")
        return False
    indexes = [index for index, item in enumerate(modules) if identity(item) == PREDECESSOR]
    if len(indexes) != 1:
        raise SystemExit(
            f"expected exactly one immutable HTTP predecessor {PREDECESSOR}, found {len(indexes)}"
        )
    modules.insert(indexes[0] + 1, ENTRY)
    path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
    print("staged HTTP 1.0.1 build 2")
    return True


def main() -> None:
    stage(Path(__file__).resolve().parent.parent / "catalog.source.json")


if __name__ == "__main__":
    main()
