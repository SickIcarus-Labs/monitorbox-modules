#!/usr/bin/env python3
"""UI53 candidate fingerprint, signed predecessor, managed package and immutable UI52 gate."""
from __future__ import annotations
import ast,copy,hashlib,json,subprocess,tempfile
from pathlib import Path
import build_first_party_ui as stable
import build_first_party_ui_build52 as predecessor
import build_first_party_ui_build53 as candidate
import stage_104_ui_build53 as staging

ROOT=Path(__file__).resolve().parent.parent
def main():
    source=candidate._sources(ROOT)
    assert len(source)==11
    for name in source:
        if name.endswith(".js"):
            subprocess.run(["node","--check",
                str(ROOT/"sources/ui/1.17.0-build53"/name)],check=True)
    parent=predecessor._package_files(ROOT)
    assert hashlib.sha256(stable._zip_bytes(parent)).hexdigest()==candidate.SIGNED_UI52
    new=candidate._package_files(ROOT)
    assets={name.removeprefix(candidate.TARGET_IMPORT_PACKAGE+"/"):body
        for name,body in new.items()}
    assert b'powerCapabilities(m)' in assets["assets/card-composer-renderer.js"]
    assert b"powerMatch(component,metric" in assets["assets/card-item-registry.js"]
    assert b"id=\"pickerAdvanced\"" in assets["assets/card-layout-editor.html"]
    assert b"Native Power" not in assets["assets/card-item-registry.js"],(
      "Power semantics must remain a generic registry capability")
    assert b"bootstrap_pending" in assets["bootstrap.py"]
    assert b"register_preference_first_ready" in assets["__init__.py"]
    assert b"monitorbox:state" in assets["assets/dashboard.js"]
    assert b"siteEpoch === startedEpoch" in assets["assets/app-shell.js"]
    assert assets["assets/card-projection.js"]==parent[
        predecessor.TARGET_IMPORT_PACKAGE+"/assets/card-projection.js"]
    ast.parse(assets["__init__.py"].decode())
    ast.parse(assets["bootstrap.py"].decode())
    assert staging.ENTRY["manifest"]["requires_core"]==">=2.7.0 <3.0.0"
    with tempfile.TemporaryDirectory(prefix="ui53-") as d:
        disposable=Path(d)/"catalog.json"
        disposable.write_text(json.dumps({"modules":[copy.deepcopy(staging.UI48_ENTRY)]}))
        assert staging.stage(disposable) is True
        assert staging.stage(disposable) is False
        assert json.loads(disposable.read_text())["modules"][1]==staging.ENTRY
        a=candidate.build(ROOT,Path(d)/"a").read_bytes()
        b=candidate.build(ROOT,Path(d)/"b").read_bytes()
        assert a==b
        assert a!=stable._zip_bytes(parent),(
          "Signed UI52 was reused or mutated rather than building UI53")
        print("UI53 exact-source package deterministic, signed UI52 unchanged. "
          "sha256="+hashlib.sha256(a).hexdigest())
if __name__=="__main__":main()
