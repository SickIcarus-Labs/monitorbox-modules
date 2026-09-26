#!/usr/bin/env python3
"""UI51 scoped regeneration, observed host defaults and one-grip native Arrange."""
from __future__ import annotations
import argparse,hashlib
from pathlib import Path
import build_first_party_ui as stable
import build_first_party_ui_build50 as previous
from build_first_party_ui_build43 import _replace_once

UI_VERSION="1.15.0"
UI_BUILD=51
UI_GENERATION=f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION=previous.UI_GENERATION
PARENT_IMPORT_PACKAGE=previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE="monitorbox_ui_b51"
RELEASE51=stable.Release(build=51,version=UI_VERSION,
    certified_sha="feature-104-curated-bootstrap-grip-103-dividend")
SOURCE_BLOBS={
    "card-composer-renderer.js":"b2258b63f439b1635cb53b3dd4ccbdbaec1fae40",
    "card-composer.css":"8ff904118690c65621cc785ad990b11d01a57dc4",
    "card-item-registry.js":"7209fac13f543ad390f28d8a61f484539dac10f3",
    "card-layout-editor.html":"e9333dae4e7464cc3a033b5dd0c8d75c3d8aff24",
    "card-layout-editor.js":"d9683c84c3fd6324f731b3d1346a7878b6befd29",
    "card-layout-policy.js":"86931cce26be3cda3076c2a0c6b64494c1836a27",
    "card-layout.css":"bc054bdae27d33b54e6bfc9e3d54516758d60e61",
    "card-layout.js":"07f83366891aa36675fad91a971aaab093c2f8d2",
    "live-telemetry.js":"24d723db90cf6dddc8aa4ea241a11ae465e64c4e",
}
def _git_blob_sha(payload:bytes)->str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode()+payload).hexdigest()

def _sources(root:Path)->dict[str,bytes]:
    folder=root/"sources"/"ui"/"1.15.0-build51"
    if {p.name for p in folder.iterdir() if p.is_file()}!=set(SOURCE_BLOBS):
        raise SystemExit("UI51 source inventory drift")
    result={}
    for name,expected in SOURCE_BLOBS.items():
        blob=(folder/name).read_bytes()
        if _git_blob_sha(blob)!=expected:
            raise SystemExit("UI51 unreviewed source fingerprint: "+name)
        result[name]=blob
    for name in ("card-layout-editor.js","card-layout.js","card-layout-policy.js"):
        for forbidden in (b"unifi",b"scrypted",b"portainer",b"meraki",b"eero"):
            if forbidden in result[name].lower():
                raise SystemExit("UI51 shared layout gained provider logic: "+name)
    return result

def _package_files(root:Path)->dict[str,bytes]:
    inherited=previous._package_files(root)
    prefix=PARENT_IMPORT_PACKAGE+"/"
    parent={}
    for path,blob in inherited.items():
        if not path.startswith(prefix):
            raise SystemExit("UI51 foreign predecessor package: "+path)
        parent[path[len(prefix):]]=blob
    parent["__init__.py"]=_replace_once(parent["__init__.py"],
        b"Standalone managed MonitorBox UI 1.14.0 build 50.",
        b"Standalone managed MonitorBox UI 1.15.0 build 51.",
        "UI51 managed module identity")
    for name,blob in list(parent.items()):
        parent[name]=blob.replace(PARENT_GENERATION.encode(),UI_GENERATION.encode()).replace(
            PARENT_IMPORT_PACKAGE.encode(),TARGET_IMPORT_PACKAGE.encode())
    for name,blob in _sources(root).items():
        parent["assets/"+name]=blob
    html=parent["assets/dashboard.html"]
    for asset in ("card-item-registry.js","card-layout-policy.js","card-layout.js",
                  "card-composer-renderer.js","card-composer.css","live-telemetry.js"):
        needle=("/static/"+asset+"?v="+UI_GENERATION).encode()
        if html.count(needle)!=1:raise SystemExit("UI51 homepage dependency missing: "+asset)
    editor=parent["assets/card-layout-editor.html"]
    if editor.count(b"v=1.15.0-51")!=5 or editor.count(b'id="regenerate"')!=1 or (
        b'id="reset"' in editor or b'id="rebuildBootstrap"' in editor):
        raise SystemExit("UI51 editor identity/single-regenerate contract changed")
    if parent["assets/card-projection.js"]!=inherited[prefix+"assets/card-projection.js"]:
        raise SystemExit("UI51 changed canonical projection")
    if b"monitorbox:state" not in parent["assets/dashboard.js"] or (
        b"siteEpoch === startedEpoch" not in parent["assets/app-shell.js"]):
        raise SystemExit("UI51 lost #103 header-convergence dividend")
    if any(PARENT_GENERATION.encode() in blob for blob in parent.values()):
        raise SystemExit("UI51 retained stale UI50 script identity")
    return {TARGET_IMPORT_PACKAGE+"/"+path:blob for path,blob in parent.items()}

def build(root:Path,output_dir:Path)->Path:
    output_dir.mkdir(parents=True,exist_ok=True)
    data=stable._zip_bytes(_package_files(root))
    target=output_dir/RELEASE51.filename
    target.write_bytes(data)
    print(f"UI51 dev candidate {target}: sha256={hashlib.sha256(data).hexdigest()}")
    return target

def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",type=Path,
        default=Path(__file__).resolve().parent.parent/"packages")
    args=parser.parse_args()
    build(Path(__file__).resolve().parent.parent,args.output_dir)
if __name__=="__main__":main()
