#!/usr/bin/env python3
"""UI54 immutable signed-dev successor to UI54; trusted policy verifies ancestry."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from stage_402_ui_build48 import ENTRY as UI48_ENTRY
from stage_91_ui_build42 import MODULE, identity

TRUNK=(MODULE,"1.12.0",48)
CANDIDATE=(MODULE,"1.17.1",54)
ENTRY=copy.deepcopy(UI48_ENTRY)
ENTRY["manifest"]["version"]="1.17.1"
ENTRY["manifest"]["build"]=54
ENTRY["manifest"]["entrypoints"]={"webui":"monitorbox_ui_b54:install"}
ENTRY["manifest"]["requires_core"]=">=2.7.0 <3.0.0"
ENTRY["package"]="com.sickicarus.monitorbox.ui-1.17.1-build54.zip"


def stage(path:Path)->bool:
    doc=json.loads(path.read_text(encoding="utf-8"))
    entries=doc.get("modules")
    if not isinstance(entries,list):
        raise SystemExit("UI54 requires the cumulative accepted UI48 trunk catalog")
    found=[x for x in entries if identity(x)==CANDIDATE]
    if found:
        if len(found)!=1 or found[0]!=ENTRY:
            raise SystemExit("Conflicting UI54 identity or Core floor")
        return False
    old=[i for i,x in enumerate(entries) if identity(x)==TRUNK]
    if len(old)!=1 or entries[old[0]]!=UI48_ENTRY:
        raise SystemExit("UI54 requires exact unchanged UI48 main baseline")
    if any(identity(x)[0]==MODULE and identity(x)[2]>48 for x in entries):
        raise SystemExit("UI trunk advanced; explicitly reconcile before UI54")
    entries.insert(old[0]+1,ENTRY)
    path.write_text(json.dumps(doc,separators=(",",":"),ensure_ascii=False)+"\n",
                    encoding="utf-8")
    print("UI54 candidate requires Core >=2.7.0; staged in disposable catalog only")
    return True


if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
