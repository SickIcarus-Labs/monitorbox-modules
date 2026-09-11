#!/usr/bin/env python3
"""Idempotently stage the P2 Phase-2 UI v1.1.15 build-28 candidate."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

PREDECESSOR=("com.sickicarus.monitorbox.ui","1.1.14",27)
RELEASE=("com.sickicarus.monitorbox.ui","1.1.15",28)
ENTRY={
  "manifest":{
    "module_id":"com.sickicarus.monitorbox.ui",
    "display_name":"MonitorBox UI",
    "description":"MonitorBox web interface, shared application shell, and operator presentation.",
    "version":"1.1.15",
    "build":28,
    "schema":1,
    "state_schema":1,
    "module_type":"ui",
    "entrypoints":{"webui":"monitorbox_ui_b28:install"},
    "requires_core":">=2.3.1 <3.0.0",
    "requires_runtime_api":">=1 <2",
    "dependencies":[],
    "publisher_id":"com.sickicarus",
    "permissions":[],
    "lifecycle_policy":"required"
  },
  "package":"com.sickicarus.monitorbox.ui-1.1.15-build28.zip"
}

def identity(item:dict[str,Any])->tuple[str,str,int]:
    manifest=item.get("manifest",{})
    return (str(manifest.get("module_id") or ""),str(manifest.get("version") or ""),int(manifest.get("build") or 0))

def stage(path:Path)->bool:
    source=json.loads(path.read_text(encoding="utf-8")); modules=source.get("modules")
    if not isinstance(modules,list): raise SystemExit("catalog.source.json has no modules list")
    existing=[item for item in modules if identity(item)==RELEASE]
    if existing:
        if len(existing)!=1 or existing[0]!=ENTRY: raise SystemExit(f"catalog release conflicts with P2 Phase-2 build28 contract: {RELEASE}")
        print("P2 Phase-2 UI build28 candidate already staged"); return False
    indexes=[index for index,item in enumerate(modules) if identity(item)==PREDECESSOR]
    if len(indexes)!=1: raise SystemExit(f"expected exactly one UI predecessor {PREDECESSOR}, found {len(indexes)}")
    modules.insert(indexes[0]+1,ENTRY)
    path.write_text(json.dumps(source,separators=(",",":"))+"\n",encoding="utf-8")
    print("staged P2 Phase-2 UI 1.1.15 build 28 after accepted build 27")
    return True

def main()->None:
    stage(Path(__file__).resolve().parent.parent/"catalog.source.json")
if __name__=="__main__": main()
