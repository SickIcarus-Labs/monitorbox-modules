#!/usr/bin/env python3
"""Stage new UI41 candidate only; no channel promotion or signed artifact rewrite."""
from __future__ import annotations

import json
from pathlib import Path

PREDECESSOR=("com.sickicarus.monitorbox.ui","1.4.1",40)
RELEASE=("com.sickicarus.monitorbox.ui","1.5.0",41)
ACCEPTED_FALLBACK=("com.sickicarus.monitorbox.ui","1.3.1",35)
ENTRY={
    "manifest":{
        "module_id":"com.sickicarus.monitorbox.ui",
        "display_name":"MonitorBox UI",
        "description":"MonitorBox web interface, shared shell and operator presentation.",
        "version":"1.5.0",
        "build":41,
        "schema":1,
        "state_schema":1,
        "module_type":"ui",
        "entrypoints":{"webui":"monitorbox_ui_b41:install"},
        "requires_core":">=2.6.0 <3.0.0",
        "requires_runtime_api":">=1 <2",
        "dependencies":[],
        "publisher_id":"com.sickicarus",
        "permissions":[],
        "lifecycle_policy":"required",
    },
    "package":"com.sickicarus.monitorbox.ui-1.5.0-build41.zip",
}

def identity(row: dict)->tuple[str,str,int]:
    m=row.get("manifest",{})
    return str(m.get("module_id") or ""),str(m.get("version") or ""),int(m.get("build") or 0)

def stage(path:Path)->bool:
    document=json.loads(path.read_text(encoding="utf-8"))
    entries=document.get("modules")
    if not isinstance(entries,list):raise SystemExit("catalog has no modules list")
    matches=[item for item in entries if identity(item)==RELEASE]
    if matches:
        if len(matches)!=1 or matches[0]!=ENTRY:raise SystemExit("UI41 catalog conflict")
        return False
    prior=[i for i,item in enumerate(entries) if identity(item)==PREDECESSOR]
    if not prior:
        # UI40 is already signed on dev, but its draft source predecessor may
        # not yet have entered the branch catalog.source.json. Add *only* the
        # UI41 candidate in this isolated publication; never stage two new UI
        # releases in one intent or rewrite signed build40.
        prior=[i for i,item in enumerate(entries) if identity(item)==ACCEPTED_FALLBACK]
    if len(prior)!=1:raise SystemExit("expected one UI40 or accepted UI35 predecessor")
    entries.insert(prior[0]+1,ENTRY)
    path.write_text(json.dumps(document,separators=(",",":"))+"\n",encoding="utf-8")
    print("staged isolated UI 1.5.0 build41")
    return True

if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
