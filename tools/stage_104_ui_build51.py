#!/usr/bin/env python3
"""Stage exactly one UI51 successor to accepted UI48 trunk; signed UI50 stays immutable."""
from __future__ import annotations
import copy,json
from pathlib import Path
from stage_402_ui_build48 import ENTRY as UI48_ENTRY
from stage_91_ui_build42 import MODULE,identity
PREDECESSOR=(MODULE,"1.12.0",48)
RELEASE=(MODULE,"1.15.0",51)
ENTRY=copy.deepcopy(UI48_ENTRY)
ENTRY["manifest"]["version"]="1.15.0"
ENTRY["manifest"]["build"]=51
ENTRY["manifest"]["entrypoints"]={"webui":"monitorbox_ui_b51:install"}
ENTRY["package"]="com.sickicarus.monitorbox.ui-1.15.0-build51.zip"
def stage(path:Path)->bool:
    doc=json.loads(path.read_text(encoding="utf-8"))
    entries=doc.get("modules")
    if not isinstance(entries,list):
        raise SystemExit("UI51 needs cumulative accepted UI48 trunk catalog")
    found=[r for r in entries if identity(r)==RELEASE]
    if found:
        if len(found)!=1 or found[0]!=ENTRY:
            raise SystemExit("Conflicting immutable UI51 candidate")
        return False
    old=[i for i,row in enumerate(entries) if identity(row)==PREDECESSOR]
    if len(old)!=1 or entries[old[0]]!=UI48_ENTRY:
        raise SystemExit("UI51 requires exact accepted UI48 baseline")
    if any(identity(row)[0]==MODULE and identity(row)[2]>48 for row in entries):
        raise SystemExit("Trunk advanced beyond UI48; reconsider signed-dev supersession")
    entries.insert(old[0]+1,ENTRY)
    path.write_text(json.dumps(doc,separators=(",",":"),ensure_ascii=False)+"\n",
                    encoding="utf-8")
    print("UI51: staged exactly one UI 1.15.0 build51 on accepted UI48 trunk")
    return True
if __name__=="__main__":stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
