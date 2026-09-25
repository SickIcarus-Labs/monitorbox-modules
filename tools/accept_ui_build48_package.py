#!/usr/bin/env python3
"""UI48 carries immutable signed UI47 native-density presentation plus selected-viewer interest."""
from __future__ import annotations
import ast
import hashlib
import subprocess
import tempfile
from pathlib import Path

import build_first_party_ui_build47 as previous
import build_first_party_ui_build48 as candidate

ROOT=Path(__file__).resolve().parent.parent
OLD=previous.TARGET_IMPORT_PACKAGE+"/"
NEW=candidate.TARGET_IMPORT_PACKAGE+"/"

def main():
    source=candidate._sources(ROOT)
    assert len(source)==9
    for name in source:
        if name.endswith(".js"):
            subprocess.run(["node","--check",str(ROOT/"sources/ui/1.12.0-build48"/name)],check=True)
    parent=previous._package_files(ROOT)
    current=candidate._package_files(ROOT)
    old_names={p.removeprefix(OLD) for p in parent}
    new_names={p.removeprefix(NEW) for p in current}
    assert new_names == old_names, "Inherited Core-facing asset inventory changed"
    for key in ("assets/card-projection.js","assets/card-layout-policy.js",
                "assets/card-item-registry.js","assets/card-layout.css"):
        assert parent[OLD+key] == current[NEW+key],key
    assert current[NEW+"assets/card-composer.css"] == parent[OLD+"assets/card-composer.css"],(
        "Accepted compact native row spacing must be immutable"
    )
    renderer=current[NEW+"assets/card-composer-renderer.js"]
    assert b"visibleLiveDetails" in renderer
    assert b"setInterval(refreshLiveRows,1000)" in renderer
    live=current[NEW+"assets/live-telemetry.js"]
    assert b"visibleLiveDetails?.()" in live
    assert b"query.append('detail',detail)" in live
    editor=current[NEW+"assets/card-layout-editor.html"]
    assert editor.count(b"v=1.12.0-48")==5
    homepage=current[NEW+"assets/dashboard.html"]
    assert homepage.count(b"/static/live-telemetry.js?v=1.12.0-48")==1
    assert b"v=1.11.0-47" not in homepage
    assert b"const SCHEMA=3;" in current[NEW+"assets/card-layout-policy.js"]
    ast.parse(current[NEW+"__init__.py"].decode())
    assert "Standalone managed MonitorBox UI 1.12.0 build 48." in current[NEW+"__init__.py"].decode()
    with tempfile.TemporaryDirectory() as temp:
        a=candidate.build(ROOT,Path(temp)/"one").read_bytes()
        b=candidate.build(ROOT,Path(temp)/"two").read_bytes()
        assert a==b
        print("UI48 compact signed-UI47 inheritance, one-second selected interest,"
              " canonical snapshot and deterministic ZIP: PASS "+hashlib.sha256(a).hexdigest())

if __name__=="__main__":
    main()
