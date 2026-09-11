#!/usr/bin/env python3
"""Build P2 Phase-2 #209 unified-monitoring UI v1.1.18 build 31."""
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
import build_first_party_ui_build29 as build29
import build_first_party_ui_build30 as previous

UI_VERSION = "1.1.18"
UI_BUILD = 31
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
RELEASE31 = stable.Release(build=UI_BUILD, certified_sha="p2-phase2-unified-monitoring-state", version=UI_VERSION)
SOURCE_FILES = frozenset(("unified-monitoring.css",))
SOURCE_BLOBS = {"unified-monitoring.css": "3c97d55335279f25721f82b9e962c30ba5a67ef1"}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _replace_once(payload: bytes, old: bytes, new: bytes, seam: str) -> bytes:
    if payload.count(old) != 1:
        raise SystemExit(f"UI build-31 {seam} seam changed: {old[:180]!r}")
    return payload.replace(old, new, 1)


def _build31_assets(root: Path) -> dict[str, bytes]:
    assets = previous._build30_assets(root)
    source_root = root / "sources" / "ui" / "1.1.18-build31"
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != SOURCE_FILES:
        raise SystemExit(f"UI build-31 delta shape changed: {sorted(actual)}")
    css = (source_root / "unified-monitoring.css").read_bytes()
    if _git_blob_sha(css) != SOURCE_BLOBS["unified-monitoring.css"]:
        raise SystemExit("UI build-31 CSS source blob changed")

    discovery = assets["discovery-coverage.js"]
    legacy_static = (root / "sources" / "ui" / "1.1.16-build29" / "phase2-physical-fixes.js").read_bytes()
    discovery = _replace_once(discovery, b"\n\n" + legacy_static, b"", "retired provider-static shim")

    discovery = _replace_once(
        discovery,
        b'''  function coverageState(item){\n    if(item?.configured_object_id||item?.state==='already_monitored')return {status:'covered',kind:'canonical',sourceLabel:''};\n    return providerCoverage(item);\n  }\n''',
        b'''  function coverageState(item){\n    if(item?.configured_object_id||item?.state==='already_monitored')return {status:'covered',kind:'canonical',sourceLabel:''};\n    const coverage=providerCoverage(item);\n    if(!coverage)return null;\n    if(item?.monitoring_suppressed===true||item?.monitoring_state==='not_monitored')return null;\n    return coverage;\n  }\n''',
        "monitoring-state coverage",
    )
    discovery = _replace_once(
        discovery,
        b'''  function actionText(item,checkbox){\n    const coverage=coverageState(item);\n    if(item?.state==='needs_review')return 'Needs review';\n    if(item?.state==='auxiliary')return 'No action';\n    if(item?.configured_object_id||item?.state==='already_monitored')return checkbox.checked?'Keep monitoring':'Stop monitoring';\n    if(coverage)return 'Monitored';\n    return checkbox.checked?'Start monitoring':'Not staged';\n  }\n''',
        b'''  function actionText(item,checkbox){\n    if(item?.state==='needs_review')return 'Needs review';\n    if(item?.state==='auxiliary')return 'No action';\n    const provider=providerCoverage(item);\n    const baselineProviderMonitored=Boolean(provider&&item?.monitoring_suppressed!==true&&item?.monitoring_state!=='not_monitored');\n    if(item?.configured_object_id||item?.state==='already_monitored'||baselineProviderMonitored)return checkbox.checked?'Keep monitoring':'Stop monitoring';\n    return checkbox.checked?'Start monitoring':'Not now';\n  }\n''',
        "unified action semantics",
    )
    discovery = _replace_once(
        discovery,
        b'''    if(!row.dataset.discoveryCoverageDefaultApplied){\n      const coverage=coverageState(item);\n      if(coverage&&!item?.configured_object_id&&item?.state!=='already_monitored')checkbox.checked=false;\n      row.dataset.discoveryCoverageDefaultApplied='true';\n    }\n''',
        b'''    if(!row.dataset.discoveryCoverageDefaultApplied){\n      const provider=providerCoverage(item);\n      if(provider&&!item?.configured_object_id&&item?.state!=='already_monitored'){\n        checkbox.checked=item?.monitoring_suppressed!==true&&item?.monitoring_state!=='not_monitored';\n      }\n      row.dataset.discoveryCoverageDefaultApplied='true';\n    }\n''',
        "provider checkbox baseline",
    )

    old_static = b'''    const providerOnly=Boolean(coverageState(item)&&!item?.configured_object_id&&item?.state!=='already_monitored');\n    if(providerOnly){\n      row.classList.add('provider-covered-static');\n      checkbox.checked=false; checkbox.disabled=true; checkbox.tabIndex=-1;\n      checkbox.style.position='absolute'; checkbox.style.width='0'; checkbox.style.height='0'; checkbox.style.opacity='0'; checkbox.style.pointerEvents='none';\n      if(text)text.textContent='Monitored';\n      for(const control of [...row.querySelectorAll('input,select,button,textarea')]){\n        if(control===checkbox)continue;\n        const owner=control.closest('label');\n        if(owner&&owner!==wrapper)owner.remove(); else control.remove();\n      }\n    }else{\n      row.classList.remove('provider-covered-static');\n    }\n'''
    new_unified = b'''    const providerOnly=Boolean(providerCoverage(item)&&!item?.configured_object_id&&item?.state!=='already_monitored');\n    if(providerOnly){\n      row.classList.remove('provider-covered-static');\n      row.classList.add('provider-unified-monitoring');\n      checkbox.disabled=false; checkbox.hidden=false; checkbox.tabIndex=0;\n      checkbox.style.removeProperty('position'); checkbox.style.removeProperty('width'); checkbox.style.removeProperty('height');\n      checkbox.style.removeProperty('opacity'); checkbox.style.removeProperty('pointer-events');\n      for(const control of [...row.querySelectorAll('select,textarea,input[type="checkbox"]:not([data-id]),button')]){\n        const owner=control.closest('label');\n        if(owner&&owner!==wrapper)owner.remove(); else control.remove();\n      }\n      const labelInput=row.querySelector('input[data-label-for]');\n      if(labelInput)labelInput.remove();\n      for(const node of [...row.querySelectorAll('*')]){\n        if(node.children.length)continue;\n        const value=String(node.textContent||'').trim();\n        if(value.toUpperCase()==='MONITOR ABILITIES')node.remove();\n        else if(/^Already monitored via /i.test(value)&&!node.classList.contains('pill'))node.remove();\n      }\n    }else{\n      row.classList.remove('provider-covered-static','provider-unified-monitoring');\n    }\n'''
    discovery = _replace_once(discovery, old_static, new_unified, "provider row normalization")

    discovery = _replace_once(
        discovery,
        b'''    const coverage=coverageState(item);\n    if(item?.configured_object_id||item?.state==='already_monitored'){\n      if(!checkbox.checked)return true;\n    }else if(checkbox.checked){\n      return true;\n    }\n''',
        b'''    const provider=providerCoverage(item);\n    if(item?.configured_object_id||item?.state==='already_monitored'){\n      if(!checkbox.checked)return true;\n    }else if(provider){\n      const baseline=item?.monitoring_suppressed!==true&&item?.monitoring_state!=='not_monitored';\n      if(checkbox.checked!==baseline)return true;\n    }else if(checkbox.checked){\n      return true;\n    }\n''',
        "provider staged-change baseline",
    )
    assets["discovery-coverage.js"] = discovery
    assets["discovery-coverage.css"] = assets["discovery-coverage.css"].rstrip() + b"\n" + css

    # Build 6 composes provider-service-hierarchy.js into service-presentation.js;
    # patch the actual packaged asset rather than the historical source filename.
    service = assets["service-presentation.js"]
    service = _replace_once(
        service,
        b'''  const local=inventory.filter(workload=>{\n    const environmentKey=String(workload?.environment_key||'').trim();\n    return owners.has(environmentKey)&&workload?.ignored!==true&&workload?.discovery_actionable!==false;\n  });\n''',
        b'''  const monitoringSuppressions=new Set(Array.isArray(site?.monitoring_suppressions)?site.monitoring_suppressions:[]);\n  const local=inventory.filter(workload=>{\n    const environmentKey=String(workload?.environment_key||'').trim();\n    const identity=String(workload?.identity||'').trim();\n    const monitoringToken=identity?`portainer:${identity}`:'';\n    return owners.has(environmentKey)&&workload?.ignored!==true&&workload?.discovery_actionable!==false&&!monitoringSuppressions.has(monitoringToken);\n  });\n''',
        "provider presentation suppression",
    )
    assets["service-presentation.js"] = service

    for name in ("app-shell.js", "app-shell.css", "monitorbox.webmanifest"):
        assets[name] = assets[name].replace(b"1.1.17-30", b"1.1.18-31")
    return assets


def _standalone_application() -> bytes:
    payload = previous._standalone_application()
    payload = _replace_once(payload, b"Standalone managed MonitorBox UI 1.1.17 build 30.", b"Standalone managed MonitorBox UI 1.1.18 build 31.", "standalone identity")
    return payload.replace(b"1.1.17-30", b"1.1.18-31")


def _package_files(root: Path, release: stable.Release) -> dict[str, bytes]:
    if release.build != UI_BUILD:
        return previous._package_files(root, release)
    package = release.import_package
    files = {f"{package}/__init__.py": _standalone_application()}
    for name, payload in _build31_assets(root).items():
        files[f"{package}/assets/{name}"] = payload
    forbidden = b"monitorbox.v2.modules.ui"
    offenders = [path for path, payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit("standalone UI build 31 references retired Core UI authority: " + ", ".join(sorted(offenders)))
    return files


def main() -> None:
    stable.RELEASES = stable.RELEASES + (
        build9.RELEASE8, build9.RELEASE9, build10.RELEASE10, build11.RELEASE11,
        build12.RELEASE12, build13.RELEASE13, build14.RELEASE14, build15.RELEASE15,
        build16.RELEASE16, build17.RELEASE17, build18.RELEASE18, build19.RELEASE19,
        build20.RELEASE20, accepted.RELEASE23, build27.RELEASE27, build28.RELEASE28,
        build29.RELEASE29, previous.RELEASE30, RELEASE31,
    )
    stable._package_files = _package_files
    stable.main()


if __name__ == "__main__":
    main()
