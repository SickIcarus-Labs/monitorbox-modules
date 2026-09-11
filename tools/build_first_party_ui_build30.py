#!/usr/bin/env python3
"""Build P2 Phase-2 physical-correction UI v1.1.17 build 30.

Build 30 corrects the two build-29 Broad Leaf failures in the authoritative
Discoveries renderer itself rather than relying on a late synthetic-fixture shim.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_current as build9
import build_first_party_ui_build10 as build10
import build_first_party_ui_build11 as build11
import build_first_party_ui_build12 as build12
import build_first_party_ui_build13 as build13
import build_first_party_ui_build14 as build14
import build_first_party_ui_build15 as build15
import build_first_party_ui_build16 as build16
import build_first_party_ui_build17 as build17
import build_first_party_ui_build18 as build18
import build_first_party_ui_build19 as build19
import build_first_party_ui_build20 as build20
import build_first_party_ui_build23 as accepted
import build_first_party_ui_build27 as build27
import build_first_party_ui_build28 as build28
import build_first_party_ui_build29 as previous

UI_VERSION="1.1.17"
UI_BUILD=30
UI_GENERATION=f"{UI_VERSION}-{UI_BUILD}"
RELEASE30=stable.Release(build=UI_BUILD,certified_sha="p2-phase2-physical-corrections-2",version=UI_VERSION)
SOURCE_FILES=frozenset(("phase2-physical-fixes2.css",))
SOURCE_BLOBS={"phase2-physical-fixes2.css":"1d3a3eb8bd96255a81a8142f80c52e89f81e506a"}


def _git_blob_sha(payload:bytes)->str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii")+payload).hexdigest()


def _replace_once(payload:bytes,old:bytes,new:bytes,seam:str)->bytes:
    if payload.count(old)!=1:
        raise SystemExit(f"UI build-30 {seam} seam changed: {old[:120]!r}")
    return payload.replace(old,new,1)


def _build30_assets(root:Path)->dict[str,bytes]:
    assets=previous._build29_assets(root)
    source_root=root/"sources"/"ui"/"1.1.17-build30"
    actual={p.name for p in source_root.iterdir() if p.is_file()}
    if actual!=SOURCE_FILES:
        raise SystemExit(f"UI build-30 delta shape changed: {sorted(actual)}")
    css=(source_root/"phase2-physical-fixes2.css").read_bytes()
    if _git_blob_sha(css)!=SOURCE_BLOBS["phase2-physical-fixes2.css"]:
        raise SystemExit("UI build-30 CSS source blob changed")

    discovery=assets["discovery-coverage.js"]
    old_reason=b'''  function recommendationReason(item){\n    const direct=boundedReason(item?.recommendation_reason);\n    if(direct)return direct;\n    const descriptor=boundedReason(item?.review_descriptor?.recommendation_reason);\n    if(descriptor)return descriptor;\n    return 'Recommended by discovery policy';\n  }\n'''
    new_reason=b'''  function recommendationReason(item){\n    const relationshipReason=value=>{\n      if(!value||typeof value!=='object')return '';\n      const peer=boundedReason(value.peer_device); const port=boundedReason(value.peer_port);\n      if(!peer)return '';\n      const suffix=port?` · ${port}`:'';\n      const kind=String(value.kind||'').trim().toLowerCase();\n      if(kind==='uplink')return `Uplink to ${peer}${suffix}`;\n      if(kind==='inter_switch_link'||kind==='infrastructure')return `Inter-switch link → ${peer}${suffix}`;\n      return '';\n    };\n    const sources=[...(item?.evidence||[]).map(row=>row?.metadata),item?.review_descriptor?.metadata,item?.metadata,item?.review_descriptor,item];\n    for(const source of sources){\n      if(!source||typeof source!=='object')continue;\n      const relation=relationshipReason(source.recommendation_relationship);\n      if(relation)return relation;\n      for(const key of ['recommendation_reason','recommendation_reason_text','recommended_reason']){\n        const value=boundedReason(source[key]);\n        if(value&&!/^provider\\s*:/i.test(value))return value;\n      }\n    }\n    return 'Recommended by discovery policy';\n  }\n'''
    discovery=_replace_once(discovery,old_reason,new_reason,"recommendation reason authority")

    old_action=b'''  function actionText(item,checkbox){\n    const coverage=coverageState(item);\n    if(item?.state==='needs_review')return 'Needs review';\n    if(item?.state==='auxiliary')return 'No action';\n    if(item?.configured_object_id||item?.state==='already_monitored')return checkbox.checked?'Keep monitoring':'Stop monitoring';\n    if(coverage)return checkbox.checked?'Add configured monitor':'Keep existing coverage';\n    return checkbox.checked?'Start monitoring':'Not staged';\n  }\n'''
    new_action=b'''  function actionText(item,checkbox){\n    const coverage=coverageState(item);\n    if(item?.state==='needs_review')return 'Needs review';\n    if(item?.state==='auxiliary')return 'No action';\n    if(item?.configured_object_id||item?.state==='already_monitored')return checkbox.checked?'Keep monitoring':'Stop monitoring';\n    if(coverage)return 'Monitored';\n    return checkbox.checked?'Start monitoring':'Not staged';\n  }\n'''
    discovery=_replace_once(discovery,old_action,new_action,"provider action semantics")

    old_text=b'''    const text=wrapper.querySelector('.discovery-proposed-action-text');\n    if(text)text.textContent=actionText(item,checkbox);\n    if(!row.dataset.discoveryInitialValues){\n'''
    new_text=b'''    const text=wrapper.querySelector('.discovery-proposed-action-text');\n    if(text)text.textContent=actionText(item,checkbox);\n    const providerOnly=Boolean(coverageState(item)&&!item?.configured_object_id&&item?.state!=='already_monitored');\n    if(providerOnly){\n      row.classList.add('provider-covered-static');\n      checkbox.checked=false; checkbox.disabled=true; checkbox.tabIndex=-1;\n      checkbox.style.position='absolute'; checkbox.style.width='0'; checkbox.style.height='0'; checkbox.style.opacity='0'; checkbox.style.pointerEvents='none';\n      if(text)text.textContent='Monitored';\n      for(const control of [...row.querySelectorAll('input,select,button,textarea')]){\n        if(control===checkbox)continue;\n        const owner=control.closest('label');\n        if(owner&&owner!==wrapper)owner.remove(); else control.remove();\n      }\n    }else{\n      row.classList.remove('provider-covered-static');\n    }\n    if(!row.dataset.discoveryInitialValues){\n'''
    discovery=_replace_once(discovery,old_text,new_text,"provider static row")
    assets["discovery-coverage.js"]=discovery
    assets["discovery-coverage.css"]=assets["discovery-coverage.css"].rstrip()+b"\n"+css

    for name in ("app-shell.js","app-shell.css","monitorbox.webmanifest"):
        assets[name]=assets[name].replace(b"1.1.16-29",b"1.1.17-30")
    return assets


def _standalone_application()->bytes:
    payload=previous._standalone_application()
    payload=_replace_once(payload,b"Standalone managed MonitorBox UI 1.1.16 build 29.",b"Standalone managed MonitorBox UI 1.1.17 build 30.","standalone identity")
    return payload.replace(b"1.1.16-29",b"1.1.17-30")


def _package_files(root:Path,release:stable.Release)->dict[str,bytes]:
    if release.build!=UI_BUILD:return previous._package_files(root,release)
    package=release.import_package
    files={f"{package}/__init__.py":_standalone_application()}
    for name,payload in _build30_assets(root).items():files[f"{package}/assets/{name}"]=payload
    forbidden=b"monitorbox.v2.modules.ui"
    offenders=[path for path,payload in files.items() if forbidden in payload]
    if offenders:raise SystemExit("standalone UI build 30 references retired Core UI authority: "+", ".join(sorted(offenders)))
    return files


def main()->None:
    stable.RELEASES=stable.RELEASES+(
      build9.RELEASE8,build9.RELEASE9,build10.RELEASE10,build11.RELEASE11,build12.RELEASE12,
      build13.RELEASE13,build14.RELEASE14,build15.RELEASE15,build16.RELEASE16,build17.RELEASE17,
      build18.RELEASE18,build19.RELEASE19,build20.RELEASE20,accepted.RELEASE23,build27.RELEASE27,
      build28.RELEASE28,previous.RELEASE29,RELEASE30,
    )
    stable._package_files=_package_files
    stable.main()

if __name__=="__main__":main()
