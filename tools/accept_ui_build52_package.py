#!/usr/bin/env python3
"""WIP UI52 exact-source package gate. No signed release is produced."""
from pathlib import Path
import ast,hashlib,subprocess,tempfile
import build_first_party_ui as stable
import build_first_party_ui_build51 as previous
import build_first_party_ui_build52 as candidate

ROOT=Path(__file__).resolve().parent.parent
SIGNED51="5de2e866b5d39186036bed1979a296542673a77a2cad2ac5aa01a0b0a2622379"
def main():
  sources=candidate._sources(ROOT)
  assert len(sources)==10
  for name in sources:
    if name.endswith(".js"):
      subprocess.run(["node","--check",
        str(ROOT/"sources/ui/1.16.0-build52"/name)],check=True)
  old=previous._package_files(ROOT)
  assert hashlib.sha256(stable._zip_bytes(old)).hexdigest()==SIGNED51,(
    "Signed official-dev UI51 predecessor drift")
  new=candidate._package_files(ROOT)
  prefix=candidate.TARGET_IMPORT_PACKAGE+"/"
  assets={name.removeprefix(prefix):blob for name,blob in new.items()}
  assert b"const SCHEMA=5;" in assets["assets/card-layout-policy.js"]
  assert b"function nativeContents" in assets["assets/card-composer-renderer.js"]
  assert b"measuredHeight(site,object" in assets["assets/card-composer-renderer.js"]
  assert b"card-generation.js" in assets["assets/dashboard.html"]
  assert b"card-generation.js" in assets["assets/card-layout-editor.html"]
  assert b"monitorbox:state" in assets["assets/dashboard.js"]
  assert b"siteEpoch === startedEpoch" in assets["assets/app-shell.js"]
  assert assets["assets/card-projection.js"]==old[
    previous.TARGET_IMPORT_PACKAGE+"/assets/card-projection.js"]
  ast.parse(assets["__init__.py"].decode())
  with tempfile.TemporaryDirectory(prefix="ui52-wip-") as raw:
    a=candidate.build(ROOT,Path(raw)/"a").read_bytes()
    b=candidate.build(ROOT,Path(raw)/"b").read_bytes()
    assert a==b
    print("UI52 WIP package deterministic; signed UI51 unchanged, v5 standalone rendering and #103 retained. SHA256 "+hashlib.sha256(a).hexdigest())
  # Mandatory outstanding first-boot test: the inherited Python initializer
  # must be replaced before publishing the package to official-dev. This gate
  # intentionally does not claim new-install readiness from browser tests.
  print("PENDING RELEASE BLOCKER: UI52 first-ready Python initialization / wizard parity")
if __name__=="__main__":main()
