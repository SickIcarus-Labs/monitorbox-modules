#!/usr/bin/env python3
"""Stage exactly one UI49 successor to accepted, published UI48."""
from __future__ import annotations
import copy
import json
from pathlib import Path

from stage_402_ui_build48 import ENTRY as UI48_ENTRY
from stage_91_ui_build42 import MODULE, identity

PREDECESSOR=(MODULE,"1.12.0",48)
RELEASE=(MODULE,"1.13.0",49)
ENTRY=copy.deepcopy(UI48_ENTRY)
ENTRY["manifest"]["version"]="1.13.0"
ENTRY["manifest"]["build"]=49
ENTRY["manifest"]["entrypoints"]={"webui":"monitorbox_ui_b49:install"}
ENTRY["package"]="com.sickicarus.monitorbox.ui-1.13.0-build49.zip"

def stage(path:Path)->bool:
    document=json.loads(path.read_text(encoding="utf-8"))
    entries=document.get("modules")
    if not isinstance(entries,list):
        raise SystemExit("UI49 requires a cumulative signed UI48 catalog")
    found=[row for row in entries if identity(row)==RELEASE]
    if found:
        if len(found)!=1 or found[0]!=ENTRY:
            raise SystemExit("Conflicting immutable UI49 candidate")
        return False
    predecessor=[i for i,row in enumerate(entries) if identity(row)==PREDECESSOR]
    if len(predecessor)!=1 or entries[predecessor[0]]!=UI48_ENTRY:
        raise SystemExit("UI49 requires the exact accepted UI48 source catalog row")
    if any(identity(row)[0]==MODULE and identity(row)[2]>48 for row in entries):
        raise SystemExit("A newer UI is already staged; re-evaluate candidate ancestry")
    entries.insert(predecessor[0]+1,ENTRY)
    path.write_text(json.dumps(document,separators=(",",":"),ensure_ascii=False)+"\n",
                    encoding="utf-8")
    print("Staged exactly one UI 1.13.0 build49 successor to accepted UI48")
    return True

if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
