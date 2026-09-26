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
    staged=[i for i,row in enumerate(source["modules"])
            if identity(row)==candidate.RELEASE]
    assert len(staged)==1 and source["modules"][staged[0]]==candidate.ENTRY
    assert source["modules"][staged[0]-1]==UI48
    assert not any(identity(row)[0]==MODULE and identity(row)[2] in (43,44,45,46,47)
                   for row in source["modules"])
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"catalog.json"
        original=copy.deepcopy(source)
        original["modules"].pop(staged[0])
        path.write_text(json.dumps(original))
        assert candidate.stage(path) is True
        assert json.loads(path.read_text())==source
        assert candidate.stage(path) is False
    intent=json.loads((ROOT/"release-intents/ui-1.13.0-build49.json").read_text())
    assert intent["supersedes_dev"]["sha256"]==(
        "f0530057348bfc45bd9f85d1c5ff812659601286326478669574bb07bbed508b")
    archived=(ROOT/"docs/release-intent-history/ui-1.12.0-build48.json").read_bytes()
    assert json.loads(archived)["build"]==48
    print("UI49 additive staging, exact accepted UI48 and dev supersession: PASS")

if __name__=="__main__":
    main()
