#!/usr/bin/env python3
"""Stage isolated UI41 only in an explicit candidate catalog; never publish on PR."""
from __future__ import annotations

import json
from pathlib import Path

import stage_p1_85_ui_build40 as previous

ENTRY = {
    "manifest": {
        "module_id": "com.sickicarus.monitorbox.ui",
        "display_name": "MonitorBox UI",
        "description": "MonitorBox dashboard card composition, graph shell and recovery-aware settings.",
        "version": "1.5.0",
        "build": 41,
        "schema": 1,
        "state_schema": 1,
        "module_type": "ui",
        "entrypoints": {"webui": "monitorbox_ui_b41:install"},
        "requires_core": ">=2.6.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [],
        "lifecycle_policy": "required",
    },
    "package": "com.sickicarus.monitorbox.ui-1.5.0-build41.zip",
}
IDENTITY = ("com.sickicarus.monitorbox.ui", "1.5.0", 41)


def stage(path: Path) -> bool:
    # UI40 may be in signed dev catalog but not the branch's historical
    # catalog.source.json; construct both only in the requested target.
    previous.stage(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = data.get("modules")
    if not isinstance(modules, list):
        raise SystemExit("Missing module catalog entries")
    existing = [item for item in modules if previous.identity(item) == IDENTITY]
    if existing:
        if existing != [ENTRY]:
            raise SystemExit("Conflicting UI41 catalog identity")
        return False
    predecessors = [
        index for index,item in enumerate(modules)
        if previous.identity(item) == previous.RELEASE
    ]
    if len(predecessors) != 1:
        raise SystemExit("UI41 requires exactly one UI40 predecessor")
    modules.insert(predecessors[0]+1, ENTRY)
    path.write_text(json.dumps(data,separators=(",",":"))+"\n",encoding="utf-8")
    return True


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("catalog",type=Path)
    stage(parser.parse_args().catalog)
