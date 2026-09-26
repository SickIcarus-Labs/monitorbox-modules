#!/usr/bin/env python3
"""UI50 exact-source, signed UI49 ancestry and stable migration guards."""
import ast,hashlib,subprocess,tempfile,json
from pathlib import Path
import build_first_party_ui as stable
import build_first_party_ui_build49 as predecessor
import build_first_party_ui_build50 as candidate
import stage_104_ui_build50 as stager
from stage_402_ui_build48 import ENTRY as UI48
from stage_91_ui_build42 import identity

ROOT=Path(__file__).resolve().parent.parent
SIGNED_UI49="d0f1b86d71545a34633eb94eab7f82e507e0912256ccab3ab2d7603bc8c53e79"

def main():
    src=candidate._sources(ROOT)
    assert len(src)==9
    for name in src:
        if name.endswith(".js"):
            subprocess.run(["node","--check",str(ROOT/"sources/ui/1.14.0-build50"/name)],check=True)
    before=predecessor._package_files(ROOT)
    assert hashlib.sha256(stable._zip_bytes(before)).hexdigest()==SIGNED_UI49, (
        "Signed UI49 predecessor drift: immutability violation")
    after=candidate._package_files(ROOT)
    old=predecessor.TARGET_IMPORT_PACKAGE+"/"
    new=candidate.TARGET_IMPORT_PACKAGE+"/"
    assert {x.removeprefix(old) for x in before}=={x.removeprefix(new) for x in after}
    for asset in ("card-projection.js","card-item-registry.js","card-composer.css","live-telemetry.js"):
        assert before[old+"assets/"+asset]==after[new+"assets/"+asset]
    assert b"setPreview" in after[new+"assets/card-layout.js"]
    assert b"rebuildBootstrap" in after[new+"assets/card-layout-editor.html"]
    assert b"mb-arrange-actual-homepage" in after[new+"assets/card-layout-editor.js"]
    assert b"mb-arrange-sample" not in after[new+"assets/card-layout-editor.js"]
    assert b"monitorbox:state" in after[new+"assets/dashboard.js"]
    assert b"siteEpoch === startedEpoch" in after[new+"assets/app-shell.js"]
    assert b"const SCHEMA=4;" in after[new+"assets/card-layout-policy.js"]
    ast.parse(after[new+"__init__.py"].decode())
    with tempfile.TemporaryDirectory() as tmp:
        for asset in ("dashboard.js","app-shell.js"):
            p=Path(tmp)/asset;p.write_bytes(after[new+"assets/"+asset])
            subprocess.run(["node","--check",str(p)],check=True)
        one=candidate.build(ROOT,Path(tmp)/"one").read_bytes()
        two=candidate.build(ROOT,Path(tmp)/"two").read_bytes()
        assert one==two
        print("UI50 signed UI49 ancestry, source, same-homepage preview, reset, retained #103, deterministic ZIP PASS "+hashlib.sha256(one).hexdigest())
    original=json.loads((ROOT/"catalog.source.json").read_text())
    assert not any(identity(row)==stager.RELEASE for row in original["modules"])
    assert len([row for row in original["modules"] if row==UI48])==1
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"catalog.json";path.write_text(json.dumps(original))
        assert stager.stage(path) is True
        newdoc=json.loads(path.read_text())
        added=[row for row in newdoc["modules"] if identity(row)==stager.RELEASE]
        assert added==[stager.ENTRY]
        assert stager.stage(path) is False
        assert json.loads(path.read_text())==newdoc
    active=ROOT/"release-intents/ui-1.14.0-build50.json"
    historical=ROOT/"docs/release-intent-history/ui-1.14.0-build50.json"
    intent=json.loads((active if active.exists() else historical).read_text())
    assert intent["supersedes_dev"]=={
        "version":"1.13.0","build":49,"sha256":SIGNED_UI49,
        "authority_commit":"88e0acd4ab6f632bcf1ee022f61266891e55ef43"}
    assert json.loads((ROOT/"docs/release-intent-history/ui-1.13.0-build49.json").read_text())["build"]==49
    print("UI50 one-release staging, exact signed dev supersession and history PASS")
if __name__=="__main__":main()
