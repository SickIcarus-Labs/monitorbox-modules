#!/usr/bin/env python3
"""Materialize only the final accepted pending campaign release identities.

Phase-2 source materialization was blocked by the missing trusted-ref plumbing.
Phase-3a subsequently superseded the accepted UI/UniFi Phase-2 identities in
signed dev/beta history. Recovery must therefore stage Bootstrap/Portainer from
Phase 2 and UI/UniFi from Phase 3a in one pass, without inserting superseded
intermediate UI/UniFi releases into trunk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import stage_phase2_p1 as phase2
import stage_phase3_p1 as phase3

RELEASES = (
    phase2.RELEASES[0],  # Configuration/Bootstrap 1.0.3 build 4
    phase2.RELEASES[2],  # Portainer 1.1.1 build 7
    phase3.RELEASES[0],  # UI 1.1.11 build 19
    phase3.RELEASES[1],  # UniFi 1.0.8 build 9
)


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

    changed = False
    for spec in RELEASES:
        release = spec["release"]
        entry = spec["entry"]
        existing = [item for item in modules if identity(item) == release]
        if existing:
            if len(existing) != 1 or existing[0] != entry:
                raise SystemExit(f"catalog release conflicts with accepted contract: {release}")
            continue

        predecessor = spec["predecessor"]
        indexes = [index for index, item in enumerate(modules) if identity(item) == predecessor]
        if len(indexes) != 1:
            raise SystemExit(
                f"expected exactly one immutable trunk predecessor {predecessor}, found {len(indexes)}"
            )
        modules.insert(indexes[0] + 1, entry)
        changed = True

    if changed:
        path.write_text(json.dumps(source, separators=(",", ":")) + "\n", encoding="utf-8")
        print("staged final accepted pending Bootstrap, Portainer, UI, and UniFi releases")
    else:
        print("final accepted pending campaign releases already staged")
    return changed


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    stage(root / "catalog.source.json")


if __name__ == "__main__":
    main()
