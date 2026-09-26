#!/usr/bin/env python3
"""UI49 one-addition staging and signed-dev UI48 ancestry tests."""
import copy
import json
import tempfile
from pathlib import Path

import stage_104_ui_build49 as candidate
from stage_402_ui_build48 import ENTRY as UI48
from stage_91_ui_build42 import MODULE,identity

ROOT=Path(__file__).resolve().parent.parent

def main():
    source=json.loads((ROOT/"catalog.source.json").read_text(encoding="utf-8"))
    assert not any(identity(row)==candidate.RELEASE for row in source["modules"])
    accepted=[i for i,row in enumerate(source["modules"]) if row==UI48]
    assert len(accepted)==1, "trunk must retain signed UI48 before acceptance"
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"catalog.json"
        path.write_text(json.dumps(source))
        assert candidate.stage(path) is True
        result=json.loads(path.read_text())
        assert result["modules"][accepted[0]+1]==candidate.ENTRY
        assert result["modules"][:accepted[0]+1]+result["modules"][accepted[0]+2:]==source["modules"]
        assert candidate.stage(path) is False
        assert json.loads(path.read_text())==result
    # UI49 may be the active PR candidate or an immutable archived signed-dev
    # predecessor when its failed physical acceptance is superseded by UI50.
    active=ROOT/"release-intents/ui-1.13.0-build49.json"
    archival=ROOT/"docs/release-intent-history/ui-1.13.0-build49.json"
    source=active if active.exists() else archival
    intent=json.loads(source.read_text())
    assert "supersedes_dev" not in intent, "UI48 is already in accepted trunk"
    if source==archival:
        ui50_active=ROOT/"release-intents/ui-1.14.0-build50.json"
        ui50_history=ROOT/"docs/release-intent-history/ui-1.14.0-build50.json"
        next_intent=json.loads((ui50_active if ui50_active.exists()
            else ui50_history).read_text())
        assert next_intent["supersedes_dev"]["version"]=="1.13.0"
        assert next_intent["supersedes_dev"]["build"]==49
        assert next_intent["supersedes_dev"]["sha256"]==(
            "d0f1b86d71545a34633eb94eab7f82e507e0912256ccab3ab2d7603bc8c53e79")
        if ui50_history.exists() and not ui50_active.exists():
            ui51=ROOT/"release-intents/ui-1.15.0-build51.json"
            if ui51.exists():
                current=json.loads(ui51.read_text())
                assert current["supersedes_dev"]["version"]=="1.14.0"
                assert current["supersedes_dev"]["build"]==50
                assert current["supersedes_dev"]["sha256"]==(
                    "d978bea3ab5170d515b131f9bb7a8a5ca311ac0c7746da0b9db0dd259d6c4b03")
    archived=(ROOT/"docs/release-intent-history/ui-1.12.0-build48.json").read_bytes()
    assert json.loads(archived)["build"]==48
    print("UI49 additive staging, accepted UI48 trunk ancestry and idempotence: PASS")

if __name__=="__main__":
    main()
