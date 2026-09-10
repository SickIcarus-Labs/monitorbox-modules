#!/usr/bin/env python3
"""Replace physically rejected UI build 21 with v1.1.14 build 22.

Build 22 binds Phase-6A presentation to the actual Advanced Configuration tree
and v1-parity dashboard card renderer observed on Broad Leaf. Core remains
independent; canonical workspace and observation metadata stay authoritative.
Build 21 remains source/test history only: it failed physical acceptance and
never entered the trunk catalog, so this builder does not emit it as a release.
"""
from __future__ import annotations
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
import build_first_party_ui_build21 as rejected

UI_VERSION="1.1.14"
UI_BUILD=22
RELEASE22=stable.Release(build=UI_BUILD,certified_sha="phase6-physical-path-convergence",version=UI_VERSION)
SOURCE_FILES=frozenset(("phase6-physical-convergence.js","phase6-physical-convergence.css"))

def _replace_once(payload:bytes,old:bytes,new:bytes,seam:str)->bytes:
    if payload.count(old)!=1:
        raise SystemExit(f"UI build-22 {seam} seam changed: {old[:120]!r}")
    return payload.replace(old,new,1)

def _build22_assets(root:Path)->dict[str,bytes]:
    # Build 22 intentionally inherits the rejected build21 *source behavior* as
    # an implementation layer, then fixes its physical-path mistakes. It does
    # not make build21 a catalog/package predecessor.
    assets=rejected._build21_assets(root)
    source_root=root/"sources"/"ui"/"1.1.14-build22"
    actual={path.name for path in source_root.iterdir() if path.is_file()}
    if actual!=SOURCE_FILES:
        raise SystemExit(f"UI 1.1.14 build-22 delta shape changed: missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}")
    for name in SOURCE_FILES:
        assets[name]=(source_root/name).read_bytes()
    assets["dashboard.html"]=_replace_once(
        assets["dashboard.html"],
        b"</body>",
        b'  <link rel="stylesheet" href="/static/phase6-physical-convergence.css">\n'
        b'  <script src="/static/phase6-physical-convergence.js" defer></script>\n'
        b"</body>",
        "physical dashboard asset ordering",
    )
    return assets

def _standalone_application()->bytes:
    payload=rejected._standalone_application()
    replacements=(
        (b"Standalone managed MonitorBox UI 1.1.13 build 21.",b"Standalone managed MonitorBox UI 1.1.14 build 22."),
        (
            b'    "phase6-convergence.css": "text/css",\n}',
            b'    "phase6-convergence.css": "text/css",\n'
            b'    "phase6-physical-convergence.js": "text/javascript",\n'
            b'    "phase6-physical-convergence.css": "text/css",\n}',
        ),
        (
            b'_PHASE6_CONVERGENCE_STYLE = \'<link rel="stylesheet" href="/static/phase6-convergence.css">\'\n',
            b'_PHASE6_CONVERGENCE_STYLE = \'<link rel="stylesheet" href="/static/phase6-convergence.css">\'\n'
            b'_PHASE6_PHYSICAL_SCRIPT = \'<script src="/static/phase6-physical-convergence.js" defer></script>\'\n'
            b'_PHASE6_PHYSICAL_STYLE = \'<link rel="stylesheet" href="/static/phase6-physical-convergence.css">\'\n',
        ),
        (
            b'            scripts.extend((_ADVANCED_POLISH_SCRIPT, _ADVANCED_DIRTY_STATE_SCRIPT, _PHASE6_CONVERGENCE_STYLE, _PHASE6_CONVERGENCE_SCRIPT))\n',
            b'            scripts.extend((_ADVANCED_POLISH_SCRIPT, _ADVANCED_DIRTY_STATE_SCRIPT, _PHASE6_CONVERGENCE_STYLE, _PHASE6_CONVERGENCE_SCRIPT, _PHASE6_PHYSICAL_STYLE, _PHASE6_PHYSICAL_SCRIPT))\n',
        ),
    )
    for old,new in replacements:
        payload=_replace_once(payload,old,new,"standalone application")
    return payload

def _package_files(root:Path,release:stable.Release)->dict[str,bytes]:
    if release.build!=UI_BUILD:
        return rejected._package_files(root,release)
    package=release.import_package
    files={f"{package}/__init__.py":_standalone_application()}
    for name,payload in _build22_assets(root).items():
        files[f"{package}/assets/{name}"]=payload
    forbidden=b"monitorbox.v2.modules.ui"
    offenders=[path for path,payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit("standalone UI build 22 unexpectedly references retired Core UI authority: "+", ".join(sorted(offenders)))
    return files

def main()->None:
    # Build21 is deliberately absent: it failed Broad Leaf physical acceptance
    # and never became trunk catalog history.
    stable.RELEASES=stable.RELEASES+(
        build9.RELEASE8,build9.RELEASE9,build10.RELEASE10,build11.RELEASE11,
        build12.RELEASE12,build13.RELEASE13,build14.RELEASE14,build15.RELEASE15,
        build16.RELEASE16,build17.RELEASE17,build18.RELEASE18,build19.RELEASE19,
        build20.RELEASE20,RELEASE22,
    )
    stable._package_files=_package_files
    stable.main()

if __name__=="__main__": main()
