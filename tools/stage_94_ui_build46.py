#!/usr/bin/env python3
"""Stage exactly one UI46 dev release over immutable UI42 main source history.

UI45 is already signed in official-dev. Its authority is verified via the
release intent's supersedes_dev proof; do not add or modify UI45 in main.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from stage_91_ui_build42 import ENTRY as UI42_ENTRY, MODULE, identity
from stage_94_ui_build45 import ENTRY as UI45_ENTRY

PREDECESSOR=(MODULE,"1.6.0",42)
RELEASE=(MODULE,"1.10.0",46)
ENTRY=copy.deepcopy(UI45_ENTRY)
ENTRY["manifest"]["version"]="1.10.0"
ENTRY["manifest"]["build"]=46
ENTRY["manifest"]["entrypoints"]={"webui":"monitorbox_ui_b46:install"}
ENTRY["package"]="com.sickicarus.monitorbox.ui-1.10.0-build46.zip"


def stage(path:Path)->bool:
    document=json.loads(path.read_text(encoding="utf-8"))
    entries=document.get("modules")
    if not isinstance(entries,list):
        raise SystemExit("UI46 requires cumulative signed-beta source catalog")
    existing=[row for row in entries if identity(row)==RELEASE]
    if existing:
        if len(existing)!=1 or existing[0]!=ENTRY:
            raise SystemExit("Conflicting immutable UI46 release identity")
        return False
    predecessor=[i for i,row in enumerate(entries) if identity(row)==PREDECESSOR]
    if len(predecessor)!=1 or entries[predecessor[0]]!=UI42_ENTRY:
        raise SystemExit("UI46 requires exact signed-beta UI42 source row")
    if any(identity(row)[0]==MODULE and identity(row)[2]>42 for row in entries):
        raise SystemExit(
            "Newer UI already materialized in trunk; re-evaluate dev supersession"
        )
    entries.insert(predecessor[0]+1,ENTRY)
    path.write_text(
        json.dumps(document,separators=(",",":"),ensure_ascii=False)+"\n",
        encoding="utf-8",
    )
    print("Staged one UI 1.10.0 build46 release; signed UI45 is dev-only predecessor")
    return True


if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
