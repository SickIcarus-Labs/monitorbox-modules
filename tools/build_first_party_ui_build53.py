#!/usr/bin/env python3
"""UI53 Power semantic capabilities layered on immutable signed official-dev UI52."""
from __future__ import annotations
import argparse,hashlib
from pathlib import Path
import build_first_party_ui as stable
import build_first_party_ui_build52 as previous
from build_first_party_ui_build43 import _replace_once

UI_VERSION="1.17.0"
UI_BUILD=53
UI_GENERATION=f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION=previous.UI_GENERATION
PARENT_IMPORT_PACKAGE=previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE="monitorbox_ui_b53"
RELEASE53=stable.Release(build=53,version=UI_VERSION,
    certified_sha="feature-104-ui53-semantic-power-curation")
SIGNED_UI52="373ace36c9986512394764e9167dc709d40f211ffe7d2ef454fe586a5bc849fb"
SOURCE_BLOBS={
  "bootstrap.py":"d8355ce261f229f24dd681721b1762ce5a846856",
  "card-composer-renderer.js":"bc1b169d63edc4575219da7b0ace1e486eb89145",
  "card-composer.css":"712b527d092c4fe8f1c4a0518d8c17ead248bda0",
  "card-generation.js":"b1023852dc6f9b80db5572b951cd8f649abe6ee8",
  "card-item-registry.js":"6959119fff752a237b6df04390934756030db016",
  "card-layout-editor.html":"0d31f0c6c012e12cf411399106f7081e0bd576c1",
  "card-layout-editor.js":"9296f28acd500c60c2be03988a7a989db59f47c3",
  "card-layout-policy.js":"3d6eed7ac5a82aabcac23078b40828e209a0f174",
  "card-layout.css":"4a49903656463b9ca9d872e2d85a68178d3a8de1",
  "card-layout.js":"f293ba09d65aed74160d59d04a0cdcc21302cc9c",
  "live-telemetry.js":"24d723db90cf6dddc8aa4ea241a11ae465e64c4e",
}
def blob_sha(payload:bytes)->str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode()+payload).hexdigest()

def _sources(root:Path)->dict[str,bytes]:
    folder=root/"sources/ui/1.17.0-build53"
    if {p.name for p in folder.iterdir() if p.is_file()}!=set(SOURCE_BLOBS):
        raise SystemExit("UI53 unexpected source inventory")
    data={}
    for name,expected in SOURCE_BLOBS.items():
        payload=(folder/name).read_bytes()
        if blob_sha(payload)!=expected:
            raise SystemExit("UI53 unreviewed source fingerprint: "+name)
        data[name]=payload
    return data

def _package_files(root:Path)->dict[str,bytes]:
    inherited=previous._package_files(root)
    if hashlib.sha256(stable._zip_bytes(inherited)).hexdigest()!=SIGNED_UI52:
        raise SystemExit("UI53 signed predecessor UI52 package drift")
    prefix=PARENT_IMPORT_PACKAGE+"/"
    if any(not path.startswith(prefix) for path in inherited):
        raise SystemExit("UI53 inherited unexpected parent file")
    parent={name[len(prefix):]:value for name,value in inherited.items()}
    parent["__init__.py"]=_replace_once(
        parent["__init__.py"],
        b"Standalone managed MonitorBox UI 1.16.0 build 52.",
        b"Standalone managed MonitorBox UI 1.17.0 build 53.",
        "UI53 installed module identity")
    for name,value in list(parent.items()):
        parent[name]=value.replace(PARENT_GENERATION.encode(),UI_GENERATION.encode()).replace(
            PARENT_IMPORT_PACKAGE.encode(),TARGET_IMPORT_PACKAGE.encode())
    sources=_sources(root)
    bootstrap=sources.pop("bootstrap.py")
    parent["bootstrap.py"]=bootstrap
    for name,value in sources.items():
        parent["assets/"+name]=value
    html=parent["assets/dashboard.html"]
    editor=parent["assets/card-layout-editor.html"]
    for name in ("card-item-registry.js","card-generation.js","card-layout-policy.js",
                 "card-layout.js","card-composer-renderer.js","live-telemetry.js"):
        if html.count(("/static/"+name+"?v="+UI_GENERATION).encode())!=1:
            raise SystemExit("UI53 homepage script/version drift: "+name)
    if editor.count(b"v=1.17.0-53")!=6 or (
        editor.count(b'id="pickerAdvanced"')!=1 or
        editor.count(b'id="regenerate"')!=1):
        raise SystemExit("UI53 editor Advanced/Reset contract drift")
    if b"metric(m,'battery.charge')" in parent["assets/card-composer-renderer.js"] or (
        b"registry.powerCapabilities(m)" not in parent["assets/card-composer-renderer.js"]):
        raise SystemExit("UI53 native Power still uses provider-specific metric mapping")
    if parent["assets/card-projection.js"]!=inherited[
            prefix+"assets/card-projection.js"]:
        raise SystemExit("UI53 changed canonical Core projection")
    if any(PARENT_GENERATION.encode() in body for body in parent.values()):
        raise SystemExit("UI53 stale parent generation")
    return {TARGET_IMPORT_PACKAGE+"/"+path:body for path,body in parent.items()}

def build(root:Path,output_dir:Path)->Path:
    output_dir.mkdir(parents=True,exist_ok=True)
    content=stable._zip_bytes(_package_files(root))
    artifact=output_dir/RELEASE53.filename
    artifact.write_bytes(content)
    print(f"UI53 deterministic candidate {artifact}: sha256={hashlib.sha256(content).hexdigest()}")
    return artifact

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",type=Path,
        default=Path(__file__).resolve().parent.parent/"packages")
    args=parser.parse_args()
    build(Path(__file__).resolve().parent.parent,args.output_dir)
