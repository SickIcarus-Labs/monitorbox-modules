#!/usr/bin/env python3
"""UI51 exact-source, signed UI50 ancestry, single release and retained #103."""
import ast,hashlib,subprocess,tempfile,json
from pathlib import Path
import build_first_party_ui as stable
import build_first_party_ui_build50 as previous
import build_first_party_ui_build51 as candidate
import stage_104_ui_build51 as stager
from stage_402_ui_build48 import ENTRY as UI48
from stage_91_ui_build42 import identity

ROOT=Path(__file__).resolve().parent.parent
SIGNED_UI50="d978bea3ab5170d515b131f9bb7a8a5ca311ac0c7746da0b9db0dd259d6c4b03"
def main():
    sources=candidate._sources(ROOT)
    assert len(sources)==9
    for name in sources:
        if name.endswith(".js"):
            subprocess.run(["node","--check",
              str(ROOT/"sources/ui/1.15.0-build51"/name)],check=True)
    inherited=previous._package_files(ROOT)
    assert hashlib.sha256(stable._zip_bytes(inherited)).hexdigest()==SIGNED_UI50,(
        "Signed UI50 predecessor drift")
    updated=candidate._package_files(ROOT)
    old=previous.TARGET_IMPORT_PACKAGE+"/"
    new=candidate.TARGET_IMPORT_PACKAGE+"/"
    assert {x.removeprefix(old) for x in inherited}=={
        x.removeprefix(new) for x in updated}
    for name in ("card-projection.js","card-item-registry.js",
                 "card-composer-renderer.js","card-composer.css","live-telemetry.js"):
        assert inherited[old+"assets/"+name]==updated[new+"assets/"+name]
    assert b"autoHostItems" in updated[new+"assets/card-layout-policy.js"]
    assert b"siteRows" in updated[new+"assets/card-layout.js"]
    assert b"regenerate" in updated[new+"assets/card-layout-editor.html"]
    assert b"mb-arrange-menu-button" not in updated[new+"assets/card-layout-editor.js"]
    assert b"monitorbox:state" in updated[new+"assets/dashboard.js"]
    assert b"siteEpoch === startedEpoch" in updated[new+"assets/app-shell.js"]
    assert b"const SCHEMA=4;" in updated[new+"assets/card-layout-policy.js"]
    ast.parse(updated[new+"__init__.py"].decode())
    with tempfile.TemporaryDirectory() as temp:
        for name in ("dashboard.js","app-shell.js"):
            path=Path(temp)/name
            path.write_bytes(updated[new+"assets/"+name])
            subprocess.run(["node","--check",str(path)],check=True)
        first=candidate.build(ROOT,Path(temp)/"one").read_bytes()
        second=candidate.build(ROOT,Path(temp)/"two").read_bytes()
        assert first==second
        print("UI51 signed-UI50 ancestry, source, deterministic ZIP, retained #103 PASS "
              +hashlib.sha256(first).hexdigest())
    original=json.loads((ROOT/"catalog.source.json").read_text())
    assert not any(identity(row)==stager.RELEASE for row in original["modules"])
    assert len([row for row in original["modules"] if row==UI48])==1
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/"catalog.json"
        path.write_text(json.dumps(original))
        assert stager.stage(path) is True
        newdoc=json.loads(path.read_text())
        assert [r for r in newdoc["modules"] if identity(r)==stager.RELEASE]==[
            stager.ENTRY]
        assert stager.stage(path) is False
        assert json.loads(path.read_text())==newdoc
    intent=json.loads((ROOT/"release-intents/ui-1.15.0-build51.json").read_text())
    assert intent["supersedes_dev"]=={
        "version":"1.14.0","build":50,"sha256":SIGNED_UI50,
        "authority_commit":"001cc6bacceeb17e76d1f428b5cbc68b1709895d"}
    assert json.loads((ROOT/"docs/release-intent-history/ui-1.14.0-build50.json").read_text())["build"]==50
    print("UI51 one-release staging and exact signed-dev supersession PASS")
if __name__=="__main__":main()
