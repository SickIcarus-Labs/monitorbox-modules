#!/usr/bin/env python3
"""UI49 exact-source and immutable UI48 inheritance regression gate."""
from __future__ import annotations

import ast
import hashlib
import subprocess
import tempfile
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build48 as accepted
import build_first_party_ui_build49 as candidate

ROOT = Path(__file__).resolve().parent.parent
OLD = accepted.TARGET_IMPORT_PACKAGE + "/"
NEW = candidate.TARGET_IMPORT_PACKAGE + "/"
SIGNED_UI48 = "f0530057348bfc45bd9f85d1c5ff812659601286326478669574bb07bbed508b"


def main() -> None:
    source = candidate._sources(ROOT)
    assert len(source) == 9
    for name in source:
        if name.endswith(".js"):
            subprocess.run(
                ["node", "--check", str(ROOT / "sources/ui/1.13.0-build49" / name)],
                check=True,
            )
    previous = accepted._package_files(ROOT)
    parent_bytes = stable._zip_bytes(previous)
    assert hashlib.sha256(parent_bytes).hexdigest() == SIGNED_UI48, (
        "Previously accepted signed UI48 source changed"
    )
    current = candidate._package_files(ROOT)
    assert {path.removeprefix(OLD) for path in previous} == {
        path.removeprefix(NEW) for path in current
    }, "UI49 unexpectedly changed the packaged managed asset inventory"
    for preserved in ("card-projection.js", "card-item-registry.js",
                      "card-composer.css", "live-telemetry.js"):
        assert current[NEW+"assets/"+preserved] == previous[OLD+"assets/"+preserved], (
            "Accepted monitoring/renderer source unexpectedly changed: " + preserved
        )
    assert b"const SCHEMA=4;" in current[NEW+"assets/card-layout-policy.js"]
    assert b"monitorbox:state" in current[NEW+"assets/dashboard.js"]
    assert b"siteEpoch === startedEpoch" in current[NEW+"assets/app-shell.js"]
    assert b"visibleLiveDetails" in current[NEW+"assets/card-composer-renderer.js"]
    assert b"arrangePanel" in current[NEW+"assets/card-layout-editor.html"]
    assert b"/static/live-telemetry.js?v=1.13.0-49" in current[NEW+"assets/dashboard.html"]
    ast.parse(current[NEW+"__init__.py"].decode())
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("dashboard.js", "app-shell.js"):
            generated = Path(tmp) / name
            generated.write_bytes(current[NEW+"assets/"+name])
            subprocess.run(["node", "--check", str(generated)], check=True)
        one = candidate.build(ROOT, Path(tmp)/"one").read_bytes()
        two = candidate.build(ROOT, Path(tmp)/"two").read_bytes()
        assert one == two
        print("UI49 signed UI48 ancestry, schema, shell race guards,"
              " immutable 1Hz renderer and deterministic package: PASS "
              + hashlib.sha256(one).hexdigest())


if __name__ == "__main__":
    main()
