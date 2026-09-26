#!/usr/bin/env python3
"""UI50 clean-bootstrap reset and true-homepage Arrange preview over immutable UI49."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import build_first_party_ui as stable
import build_first_party_ui_build49 as previous
from build_first_party_ui_build43 import _replace_once

UI_VERSION="1.14.0"
UI_BUILD=50
UI_GENERATION=f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION=previous.UI_GENERATION
PARENT_IMPORT_PACKAGE=previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE="monitorbox_ui_b50"
RELEASE50=stable.Release(build=50,version=UI_VERSION,
    certified_sha="feature-104-true-preview-clean-bootstrap-103-dividend")
SOURCE_BLOBS={
    "card-composer-renderer.js":"b2258b63f439b1635cb53b3dd4ccbdbaec1fae40",
    "card-composer.css":"8ff904118690c65621cc785ad990b11d01a57dc4",
    "card-item-registry.js":"7209fac13f543ad390f28d8a61f484539dac10f3",
    "card-layout-editor.html":"726e5b97640ad57bb9f2c30ef815c082db72975e",
    "card-layout-editor.js":"ec6024df915901361934e1ace9f159554179890e",
    "card-layout-policy.js":"58d46f9b056217ec67fd7926c752f10fd4ee3a94",
    "card-layout.css":"d8abf30af8ed1bc56811ab8c145a86448d139aef",
    "card-layout.js":"4e538ad8bbd4de81c9f901dab1c4bc2920e25792",
    "live-telemetry.js":"24d723db90cf6dddc8aa4ea241a11ae465e64c4e",
}

def _git_blob_sha(payload:bytes)->str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode()+payload).hexdigest()

def _sources(root:Path)->dict[str,bytes]:
    folder=root/"sources"/"ui"/"1.14.0-build50"
    if {p.name for p in folder.iterdir() if p.is_file()}!=set(SOURCE_BLOBS):
        raise SystemExit("UI50 source inventory drift")
    found={}
    for name,expected in SOURCE_BLOBS.items():
        blob=(folder/name).read_bytes()
        if _git_blob_sha(blob)!=expected:
            raise SystemExit("UI50 unreviewed source fingerprint: "+name)
        found[name]=blob
    for name in ("card-layout-editor.js","card-layout.js","card-layout-policy.js"):
        for forbidden in (b"unifi",b"scrypted",b"portainer",b"meraki",b"eero"):
            if forbidden in found[name].lower():
                raise SystemExit("UI50 shared layout gained provider logic: "+name)
    return found

def _package_files(root:Path)->dict[str,bytes]:
    inherited=previous._package_files(root)
    prefix=PARENT_IMPORT_PACKAGE+"/"
    parent={}
    for path,blob in inherited.items():
        if not path.startswith(prefix):
            raise SystemExit("UI50 foreign predecessor package: "+path)
        parent[path[len(prefix):]]=blob
    parent["__init__.py"]=_replace_once(parent["__init__.py"],
        b"Standalone managed MonitorBox UI 1.13.0 build 49.",
        b"Standalone managed MonitorBox UI 1.14.0 build 50.",
        "UI50 managed module identity")
    for name,blob in list(parent.items()):
        parent[name]=blob.replace(PARENT_GENERATION.encode(),UI_GENERATION.encode()).replace(
            PARENT_IMPORT_PACKAGE.encode(),TARGET_IMPORT_PACKAGE.encode())
    for name,blob in _sources(root).items():
        parent["assets/"+name]=blob
    html=parent["assets/dashboard.html"]
    for asset in ("card-item-registry.js","card-layout-policy.js","card-layout.js",
                  "card-composer-renderer.js","card-composer.css","live-telemetry.js"):
        needle=("/static/"+asset+"?v="+UI_GENERATION).encode()
        if html.count(needle)!=1:raise SystemExit("UI50 homepage dependency missing: "+asset)
    editor=parent["assets/card-layout-editor.html"]
    if editor.count(b"v=1.14.0-50")!=5 or editor.count(b"rebuildBootstrap")!=1:
        raise SystemExit("UI50 editor asset/reset contract changed")
    if parent["assets/card-projection.js"]!=inherited[prefix+"assets/card-projection.js"]:
        raise SystemExit("UI50 changed canonical projection")
    if b"monitorbox:state" not in parent["assets/dashboard.js"] or (
        b"siteEpoch === startedEpoch" not in parent["assets/app-shell.js"]):
        raise SystemExit("UI50 lost #103 dividend")
    if any(PARENT_GENERATION.encode() in blob for blob in parent.values()):
        raise SystemExit("UI50 retained stale UI49 script identity")
    return {TARGET_IMPORT_PACKAGE+"/"+path:blob for path,blob in parent.items()}

def build(root:Path,output_dir:Path)->Path:
    output_dir.mkdir(parents=True,exist_ok=True)
    data=stable._zip_bytes(_package_files(root))
    target=output_dir/RELEASE50.filename
    target.write_bytes(data)
    print(f"UI50 dev candidate {target}: sha256={hashlib.sha256(data).hexdigest()}")
    return target

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",type=Path,
        default=Path(__file__).resolve().parent.parent/"packages")
    args=parser.parse_args()
    build(Path(__file__).resolve().parent.parent,args.output_dir)

if __name__=="__main__":main()
