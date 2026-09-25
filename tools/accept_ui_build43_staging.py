#!/usr/bin/env python3
"""UI43 cumulative release staging must add one row, never change signed history."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

import stage_94_ui_build43 as candidate
from stage_91_ui_build42 import ENTRY as UI42

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_UI42_SHA256 = "06f66ff549efb6ab0d5e06d5ca87d3088039018565251ca8303fdcf763882039"


def main() -> None:
    baseline = json.loads((ROOT / "catalog.source.json").read_text())
    before = copy.deepcopy(baseline["modules"])
    assert len(before) == 69, "UI43 must preserve the 69-entry accepted beta source baseline"
    assert before[-1] == UI42, "UI42 predecessor must match accepted manifest"
    parent = ROOT / "packages" / UI42["package"]
    assert hashlib.sha256(parent.read_bytes()).hexdigest() == EXPECTED_UI42_SHA256
    with tempfile.TemporaryDirectory() as temporary:
        catalog = Path(temporary) / "catalog.source.json"
        catalog.write_text(json.dumps(baseline))
        assert candidate.stage(catalog) is True
        result = json.loads(catalog.read_text())
        assert result["modules"][:-1] == before, "Staging changed a historic release"
        assert result["modules"][-1] == candidate.ENTRY
        assert len(result["modules"]) == 70
        assert candidate.stage(catalog) is False, "Staging must be idempotent"
        assert json.loads(catalog.read_text()) == result
    print("UI43 immutable signed UI42 + exactly one additive staged dev row: PASS")


if __name__ == "__main__":
    main()
