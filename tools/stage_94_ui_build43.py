#!/usr/bin/env python3
"""Stage only UI43 over the exact cumulative, already-accepted UI42 source.

Do not regenerate or replace any signed UI42, Backup/Restore or other release.
The trusted main publisher stages the candidate after validating this intent.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from stage_91_ui_build42 import ENTRY as UI42_ENTRY, MODULE, identity

PREDECESSOR=(MODULE,"1.6.0",42)
RELEASE=(MODULE,"1.7.0",43)
ENTRY=copy.deepcopy(UI42_ENTRY)
ENTRY["manifest"]["version"]="1.7.0"
ENTRY["manifest"]["build"]=43
ENTRY["manifest"]["entrypoints"]={"webui":"monitorbox_ui_b43:install"}
ENTRY["package"]="com.sickicarus.monitorbox.ui-1.7.0-build43.zip"


def stage(path:Path)->bool:
    document=json.loads(path.read_text(encoding="utf-8"))
    rows=document.get("modules")
    if not isinstance(rows,list):
        raise SystemExit("UI43 requires the cumulative source catalog")
    existing=[row for row in rows if identity(row)==RELEASE]
    if existing:
        if len(existing)!=1 or existing[0]!=ENTRY:
            raise SystemExit("Conflicting UI43 release identity")
        return False
    predecessor=[i for i,row in enumerate(rows) if identity(row)==PREDECESSOR]
    if len(predecessor)!=1 or rows[predecessor[0]]!=UI42_ENTRY:
        raise SystemExit("UI43 requires exactly the accepted immutable UI42 source")
    if any(identity(row)[0]==MODULE and identity(row)[2]>42 for row in rows):
        raise SystemExit("UI43 would supersede a newer UI source; stop")
    rows.insert(predecessor[0]+1,ENTRY)
    path.write_text(json.dumps(document,separators=(",",":"))+"\n",encoding="utf-8")
    print("Staged only UI 1.7.0 build43 on cumulative 69-release UI42 source")
    return True


if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
