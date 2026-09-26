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
    intent=json.loads((ROOT/"release-intents/ui-1.13.0-build49.json").read_text())
    assert "supersedes_dev" not in intent, "UI48 is already in accepted trunk"
    archived=(ROOT/"docs/release-intent-history/ui-1.12.0-build48.json").read_bytes()
    assert json.loads(archived)["build"]==48
    print("UI49 additive staging, accepted UI48 trunk ancestry and idempotence: PASS")

if __name__=="__main__":
    main()
