#!/usr/bin/env python3
"""Stage exactly one UI47 dev release over immutable UI42 main source history.

UI46 is already signed in official-dev. Its authority is verified via the
release intent's supersedes_dev proof; do not add or modify UI46 in main.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from stage_91_ui_build42 import ENTRY as UI42_ENTRY, MODULE, identity
from stage_94_ui_build46 import ENTRY as UI46_ENTRY

PREDECESSOR=(MODULE,"1.6.0",42)
RELEASE=(MODULE,"1.11.0",47)
ENTRY=copy.deepcopy(UI46_ENTRY)
ENTRY["manifest"]["version"]="1.11.0"
ENTRY["manifest"]["build"]=47
ENTRY["manifest"]["entrypoints"]={"webui":"monitorbox_ui_b47:install"}
ENTRY["package"]="com.sickicarus.monitorbox.ui-1.11.0-build47.zip"


def stage(path:Path)->bool:
    document=json.loads(path.read_text(encoding="utf-8"))
    entries=document.get("modules")
    if not isinstance(entries,list):
        raise SystemExit("UI47 requires cumulative signed-beta source catalog")
    existing=[row for row in entries if identity(row)==RELEASE]
    if existing:
        if len(existing)!=1 or existing[0]!=ENTRY:
            raise SystemExit("Conflicting immutable UI47 release identity")
        return False
    predecessor=[i for i,row in enumerate(entries) if identity(row)==PREDECESSOR]
    if len(predecessor)!=1 or entries[predecessor[0]]!=UI42_ENTRY:
        raise SystemExit("UI47 requires exact signed-beta UI42 source row")
    if any(identity(row)[0]==MODULE and identity(row)[2]>42 for row in entries):
        raise SystemExit(
            "Newer UI already materialized in trunk; re-evaluate dev supersession"
        )
    entries.insert(predecessor[0]+1,ENTRY)
    path.write_text(
        json.dumps(document,separators=(",",":"),ensure_ascii=False)+"\n",
        encoding="utf-8",
    )
    print("Staged one UI 1.11.0 build47 release; signed UI46 is dev-only predecessor")
    return True


if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
