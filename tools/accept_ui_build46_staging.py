#!/usr/bin/env python3
"""UI46 additive staged release and exact UI42 immutable signed predecessor."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

import stage_94_ui_build46 as stage
from stage_91_ui_build42 import ENTRY as UI42_ENTRY, MODULE, identity

ROOT=Path(__file__).resolve().parent.parent
UI42_SHA256="06f66ff549efb6ab0d5e06d5ca87d3088039018565251ca8303fdcf763882039"


def main()->None:
    source=json.loads((ROOT/"catalog.source.json").read_text())
    original=copy.deepcopy(source["modules"])
    predecessor=[i for i,row in enumerate(original) if row==UI42_ENTRY]
    assert len(predecessor)==1
    assert not any(identity(row)[0]==MODULE and identity(row)[2]>42
                   for row in original)
    parent=ROOT/"packages"/UI42_ENTRY["package"]
    assert hashlib.sha256(parent.read_bytes()).hexdigest()==UI42_SHA256
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"catalog.source.json"
        path.write_text(json.dumps(source),encoding="utf-8")
        assert stage.stage(path) is True
        result=json.loads(path.read_text())["modules"]
        ix=predecessor[0]+1
        assert result[ix]==stage.ENTRY
        assert result[:ix]+result[ix+1:]==original
        assert len(result)==len(original)+1
        assert all(row["manifest"]["build"]!=45
                   for row in result
                   if row["manifest"]["module_id"]==MODULE)
        assert stage.stage(path) is False
        assert json.loads(path.read_text())["modules"]==result
    print("UI46: exact accepted UI42 digest, unchanged cumulative source, "
          "one staged UI46 dev supersession and idempotent staging: PASS")


if __name__=="__main__":
    main()
