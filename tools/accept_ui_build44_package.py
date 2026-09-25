#!/usr/bin/env python3
"""UI44 immutable UI43 inheritance, browser assets, syntax and deterministic ZIP."""
from __future__ import annotations

import ast
import hashlib
import subprocess
import tempfile
from pathlib import Path

import build_first_party_ui_build43 as inherited
import build_first_party_ui_build44 as candidate

ROOT = Path(__file__).resolve().parent.parent
OLD = inherited.TARGET_IMPORT_PACKAGE + "/"
NEW = candidate.TARGET_IMPORT_PACKAGE + "/"


def main() -> None:
    sources = candidate._sources(ROOT)
    assert set(sources) == set(candidate.SOURCE_BLOBS)
    for name in sources:
        if name.endswith(".js"):
            subprocess.run(
                ["node", "--check", str(ROOT / "sources/ui/1.8.0-build44" / name)],
                check=True,
            )
    parent = inherited._package_files(ROOT)
    package = candidate._package_files(ROOT)
    assert {path.removeprefix(OLD) for path in parent} == {
        path.removeprefix(NEW) for path in package
    }, "UI44 must not drop or insert inherited Core-facing routes/assets"
    assert parent[OLD + "assets/card-projection.js"] == package[NEW + "assets/card-projection.js"]
    assert b"const SCHEMA=3;" in package[NEW + "assets/card-layout-policy.js"]
    assert b"['metric','live']" in package[NEW + "assets/card-layout-editor.js"]
    assert b"setInterval(refreshLiveRows,1000)" in package[NEW + "assets/card-composer-renderer.js"]
    assert b"itemPicker" in package[NEW + "assets/card-layout-editor.html"]
    homepage = package[NEW + "assets/dashboard.html"]
    assert b"1.8.0-44" in homepage and b"1.7.0-43" not in homepage
    assert b"mb-card-native" in package[NEW + "assets/card-composer.css"]
    assert b"link_speed_mbps" in package[NEW + "assets/card-item-registry.js"]
    app = package[NEW + "__init__.py"].decode()
    ast.parse(app)
    assert "Standalone managed MonitorBox UI 1.8.0 build 44." in app
    assert "not in (1, 2, 3)" in app
    with tempfile.TemporaryDirectory() as tmp:
        a = candidate.build(ROOT, Path(tmp) / "first").read_bytes()
        b = candidate.build(ROOT, Path(tmp) / "second").read_bytes()
        assert a == b, "UI44 ZIP must be reproducible"
        print("UI44 immutable UI43 parent, Core routes, v3 snapshots, script syntax "
              "and deterministic package: PASS " + hashlib.sha256(a).hexdigest())


if __name__ == "__main__":
    main()
