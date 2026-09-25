#!/usr/bin/env python3
"""Stage UI42 after the beta-accepted UI41 lineage; preserve old ZIPs.

This stacked development branch must not publish a partial dev catalog that
drops already-signed UI41 or Backup/Restore b6. Trusted publication requires
an integrated cumulative source baseline or a separately qualified signed
snapshot integration before moving official-dev.
"""
from __future__ import annotations

import json
from pathlib import Path

MODULE="com.sickicarus.monitorbox.ui"
PREDECESSOR=(MODULE,"1.5.0",41)
RELEASE=(MODULE,"1.6.0",42)
ENTRY={
  "manifest":{
    "module_id":MODULE,
    "display_name":"MonitorBox UI",
    "description":"MonitorBox web interface, shared shell and operator presentation.",
    "version":"1.6.0",
    "build":42,
    "schema":1,
    "state_schema":1,
    "module_type":"ui",
    "entrypoints":{"webui":"monitorbox_ui_b42:install"},
    "requires_core":">=2.6.0 <3.0.0",
    "requires_runtime_api":">=1 <2",
    "dependencies":[],
    "publisher_id":"com.sickicarus",
    "permissions":[],
    "lifecycle_policy":"required",
  },
  "package":"com.sickicarus.monitorbox.ui-1.6.0-build42.zip",
}

def identity(row:dict)->tuple[str,str,int]:
    m=row.get("manifest",{})
    return str(m.get("module_id") or ""),str(m.get("version") or ""),int(m.get("build") or 0)

def stage(path:Path)->bool:
    document=json.loads(path.read_text(encoding="utf-8"))
    entries=document.get("modules")
    if not isinstance(entries,list):raise SystemExit("catalog has no modules")
    matches=[row for row in entries if identity(row)==RELEASE]
    if matches:
        if len(matches)!=1 or matches[0]!=ENTRY:raise SystemExit("UI42 catalog conflict")
        return False
    ancestor=[i for i,row in enumerate(entries) if identity(row)==PREDECESSOR]
    if len(ancestor)!=1:
        raise SystemExit("UI42 requires exactly one signed-beta UI41 predecessor in the cumulative raw catalog; do not publish a partial dev feed")
    entries.insert(ancestor[0]+1,ENTRY)
    path.write_text(json.dumps(document,separators=(",",":"))+"\n",encoding="utf-8")
    print("staged UI 1.6.0 build42 over signed UI41 predecessor")
    return True

if __name__=="__main__":
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
