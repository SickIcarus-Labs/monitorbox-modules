#!/usr/bin/env python3
"""Replace partially accepted UI build 22 with v1.1.13 build 23.

Build 23 keeps the physically correct Advanced/v1-parity paths from build 22,
then closes Broad Leaf's remaining generic relationship gap using only unique
Connection-host <-> System-address identity and compacts health-neutral
maintenance wording. Core remains independent. Builds 21/22 remain source/test
history only and are not emitted as trunk catalog predecessors.
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
import build_first_party_ui_build22 as partial

UI_VERSION="1.1.13"
UI_BUILD=23
RELEASE23=stable.Release(build=UI_BUILD,certified_sha="phase6-broadleaf-relationship-and-copy-convergence",version=UI_VERSION)
SOURCE_FILES=frozenset(("phase6-convergence.js","phase6-physical-convergence.js"))

def _replace_once(payload:bytes,old:bytes,new:bytes,seam:str)->bytes:
    if payload.count(old)!=1:
        raise SystemExit(f"UI build-23 {seam} seam changed: {old[:120]!r}")
    return payload.replace(old,new,1)

def _build23_assets(root:Path)->dict[str,bytes]:
    # Keep build22's accepted physical CSS/HTML seams, but replace the two
    # Phase-6 JavaScript assets at the same public URLs with the build23 source.
    assets=partial._build22_assets(root)
    source_root=root/"sources"/"ui"/"1.1.13-build23"
    actual={path.name for path in source_root.iterdir() if path.is_file()}
    if actual!=SOURCE_FILES:
        raise SystemExit(f"UI 1.1.13 build-23 delta shape changed: missing={sorted(SOURCE_FILES-actual)}, extra={sorted(actual-SOURCE_FILES)}")
    for name in SOURCE_FILES:
        assets[name]=(source_root/name).read_bytes()
    return assets

def _standalone_application()->bytes:
    payload=partial._standalone_application()
    return _replace_once(
        payload,
        b"Standalone managed MonitorBox UI 1.1.13 build 22.",
        b"Standalone managed MonitorBox UI 1.1.13 build 23.",
        "standalone release identity",
    )

def _package_files(root:Path,release:stable.Release)->dict[str,bytes]:
    if release.build!=UI_BUILD:
        return partial._package_files(root,release)
    package=release.import_package
    files={f"{package}/__init__.py":_standalone_application()}
    for name,payload in _build23_assets(root).items():
        files[f"{package}/assets/{name}"]=payload
    forbidden=b"monitorbox.v2.modules.ui"
    offenders=[path for path,payload in files.items() if forbidden in payload]
    if offenders:
        raise SystemExit("standalone UI build 23 unexpectedly references retired Core UI authority: "+", ".join(sorted(offenders)))
    return files

def main()->None:
    # Builds 21 and 22 were dev-only physical candidates and never became trunk
    # catalog history. Publish build23 directly after accepted build20.
    stable.RELEASES=stable.RELEASES+(
        build9.RELEASE8,build9.RELEASE9,build10.RELEASE10,build11.RELEASE11,
        build12.RELEASE12,build13.RELEASE13,build14.RELEASE14,build15.RELEASE15,
        build16.RELEASE16,build17.RELEASE17,build18.RELEASE18,build19.RELEASE19,
        build20.RELEASE20,RELEASE23,
    )
    stable._package_files=_package_files
    stable.main()

if __name__=="__main__": main()
