#!/usr/bin/env python3
"""UI52 WIP test candidate: standalone v5 card renderer over immutable signed UI51.

The UI51 historical Python preference writer is inherited ONLY pending the
separate first-ready canonical-bootstrap qualification. This builder must not
be staged for signed publication until that boundary is replaced and tested.
"""
from __future__ import annotations
import argparse,hashlib
from pathlib import Path
import build_first_party_ui as stable
import build_first_party_ui_build51 as previous
from build_first_party_ui_build43 import _replace_once

UI_VERSION="1.16.0"
UI_BUILD=52
UI_GENERATION=f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION=previous.UI_GENERATION
PARENT_IMPORT_PACKAGE=previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE="monitorbox_ui_b52"
RELEASE52=stable.Release(build=52,version=UI_VERSION,
    certified_sha="WIP-104-standalone-cards-no-dev-publication")
SOURCE_BLOBS={
  "card-generation.js":"b1023852dc6f9b80db5572b951cd8f649abe6ee8",
  "card-composer-renderer.js":"6e39380ffcecf562549b83767aacb0d840794223",
  "card-composer.css":"712b527d092c4fe8f1c4a0518d8c17ead248bda0",
  "card-item-registry.js":"d9aa84ce01591b9856f66e2e17e4d2da89edd879",
  "card-layout-editor.html":"024e53bfe4943f2bdc7db8b58aafe05189c97f11",
  "card-layout-editor.js":"aa26659d88c4d6b088b6bad192484c1a67b3425e",
  "card-layout-policy.js":"3d6eed7ac5a82aabcac23078b40828e209a0f174",
  "card-layout.css":"8d8f71c29d3cfe179e93e73a0d34d0d244fd7a34",
  "card-layout.js":"f293ba09d65aed74160d59d04a0cdcc21302cc9c",
  "live-telemetry.js":"24d723db90cf6dddc8aa4ea241a11ae465e64c4e",
  "bootstrap.py":"d8355ce261f229f24dd681721b1762ce5a846856",
}
def git_sha(data:bytes)->str:
  return hashlib.sha1(f"blob {len(data)}\0".encode()+data).hexdigest()

def _sources(root:Path)->dict[str,bytes]:
  folder=root/"sources/ui/1.16.0-build52"
  if {p.name for p in folder.iterdir() if p.is_file()}!=set(SOURCE_BLOBS):
    raise SystemExit("UI52 unexpected source inventory")
  result={}
  for name,expected in SOURCE_BLOBS.items():
    content=(folder/name).read_bytes()
    if git_sha(content)!=expected:
      raise SystemExit("UI52 unreviewed source fingerprint: "+name)
    result[name]=content
  return result

def _package_files(root:Path)->dict[str,bytes]:
  inherited=previous._package_files(root)
  prefix=PARENT_IMPORT_PACKAGE+"/"
  if any(not k.startswith(prefix) for k in inherited):
    raise SystemExit("UI52 unrecognized parent package")
  parent={k[len(prefix):]:v for k,v in inherited.items()}
  parent["__init__.py"]=_replace_once(parent["__init__.py"],
      b"Standalone managed MonitorBox UI 1.15.0 build 51.",
      b"Standalone managed MonitorBox UI 1.16.0 build 52.",
      "UI52 module identity")
  for name,value in list(parent.items()):
    parent[name]=value.replace(PARENT_GENERATION.encode(),UI_GENERATION.encode()).replace(
      PARENT_IMPORT_PACKAGE.encode(),TARGET_IMPORT_PACKAGE.encode())
  # New JS engine is a real managed /static resource, not merely a ZIP asset.
  # The synthetic browser fixture serves every ZIP file directly and therefore
  # cannot catch omissions from the actual managed UI ASSETS allowlist.
  parent["__init__.py"]=_replace_once(
      parent["__init__.py"],b"ASSETS = {"+bytes([10]),
      b'ASSETS = {'+bytes([10])+
      b'    "card-generation.js": "text/javascript",'+bytes([10]),
      "UI52 managed generator route")
  sources=_sources(root)
  bootstrap=sources.pop("bootstrap.py")
  # Eliminate UI41's shadow schema-v1 writer from the *new* UI52 module.
  # The module-owned v5 writer receives Core's same revisioned pre-serve
  # preference lifecycle and is differential-tested against the JS generator.
  start=parent["__init__.py"].find(b"def _automatic_layout_snapshot(app, document, current):")
  end=parent["__init__.py"].find(b"def _require_opaque_preference_contract():",start)
  if start<0 or end<=start:
    raise SystemExit("UI52 initial preference writer seam changed")
  parent["__init__.py"]=(parent["__init__.py"][:start]+
    b"from .bootstrap import (automatic_layout_snapshot as _automatic_layout_snapshot,\n"
    b"    first_ready_pending as _first_ready_pending,\n"
    b"    finalize_first_ready as _finalize_first_ready)\n\n"+
    parent["__init__.py"][end:])
  # UI52 must fail closed on pre-#410 Core. Both initial serialization and
  # one-time first-ready completion belong to the same module participant.
  parent["__init__.py"]=_replace_once(
      parent["__init__.py"],
      b'    register_provider(app, "com.sickicarus.monitorbox.ui", _automatic_layout_snapshot)'+bytes([10]),
      b'    register_provider(app, "com.sickicarus.monitorbox.ui", _automatic_layout_snapshot)'+bytes([10])+
      b'    from monitorbox.v2.module_preferences import register_preference_first_ready'+bytes([10])+
      b'    register_preference_first_ready(app, "com.sickicarus.monitorbox.ui",'+bytes([10])+
      b'        _first_ready_pending, _finalize_first_ready)'+bytes([10]),
      "UI52 Core first-ready contract")
  parent["bootstrap.py"]=bootstrap
  for name,value in sources.items():
    parent["assets/"+name]=value
  html=parent["assets/dashboard.html"]
  needle=b'<script src="/static/card-layout-policy.js?v='+UI_GENERATION.encode()+b'" defer></script>'
  inserted=(b'<script src="/static/card-generation.js?v='+UI_GENERATION.encode()+
            b'" defer></script>')+needle
  html=_replace_once(html,needle,inserted,"shared clean generator before policy")
  parent["assets/dashboard.html"]=html
  for name in ("card-item-registry.js","card-generation.js","card-layout-policy.js",
               "card-layout.js","card-composer-renderer.js","live-telemetry.js"):
    if html.count(("/static/"+name+"?v="+UI_GENERATION).encode())!=1:
      raise SystemExit("UI52 homepage script drift: "+name)
  if html.index(b"/static/card-item-registry.js")>html.index(b"/static/card-generation.js") or (
      html.index(b"/static/card-generation.js")>html.index(b"/static/card-layout-policy.js")):
    raise SystemExit("UI52 homepage generator dependency order broken")
  editor=parent["assets/card-layout-editor.html"]
  if editor.count(b"v=1.16.0-52")!=6 or editor.count(b'id="regenerate"')!=1:
    raise SystemExit("UI52 editor versions or single-reset control broken")
  if parent["assets/card-projection.js"]!=inherited[prefix+"assets/card-projection.js"]:
    raise SystemExit("UI52 attempted to rewrite canonical/Core card projection")
  if b"monitorbox:state" not in parent["assets/dashboard.js"] or (
      b"siteEpoch === startedEpoch" not in parent["assets/app-shell.js"]):
    raise SystemExit("UI52 lost #103 dividend")
  if any(PARENT_GENERATION.encode() in value for value in parent.values()):
    raise SystemExit("UI52 stale inherited script version")
  return {TARGET_IMPORT_PACKAGE+"/"+path:value for path,value in parent.items()}

def build(root:Path,output_dir:Path)->Path:
  output_dir.mkdir(parents=True,exist_ok=True)
  data=stable._zip_bytes(_package_files(root))
  path=output_dir/RELEASE52.filename
  path.write_bytes(data)
  print(f"UI52 WIP test-only package {path}: sha256={hashlib.sha256(data).hexdigest()}")
  return path

if __name__=="__main__":
  parser=argparse.ArgumentParser()
  parser.add_argument("--output-dir",type=Path,
    default=Path(__file__).resolve().parent.parent/"packages")
  args=parser.parse_args()
  build(Path(__file__).resolve().parent.parent,args.output_dir)
