#!/usr/bin/env python3
"""UI46 immutable UI45 inheritance, browser assets, syntax and deterministic ZIP."""
from __future__ import annotations

import ast
import hashlib
import subprocess
import tempfile
from pathlib import Path

import build_first_party_ui_build45 as inherited
import build_first_party_ui_build46 as candidate

ROOT = Path(__file__).resolve().parent.parent
OLD = inherited.TARGET_IMPORT_PACKAGE + "/"
NEW = candidate.TARGET_IMPORT_PACKAGE + "/"


def main() -> None:
    sources = candidate._sources(ROOT)
    assert set(sources) == set(candidate.SOURCE_BLOBS)
    for name in sources:
        if name.endswith(".js"):
            subprocess.run(
                ["node", "--check", str(ROOT / "sources/ui/1.10.0-build46" / name)],
                check=True,
            )
    parent = inherited._package_files(ROOT)
    package = candidate._package_files(ROOT)
    assert {path.removeprefix(OLD) for path in parent} == {
        path.removeprefix(NEW) for path in package
    }, "UI46 must not drop or insert inherited Core-facing routes/assets"
    assert parent[OLD + "assets/card-projection.js"] == package[NEW + "assets/card-projection.js"]
    assert b"const SCHEMA=3;" in package[NEW + "assets/card-layout-policy.js"]
    assert b"['metric','live']" in package[NEW + "assets/card-layout-editor.js"]
    assert b"setInterval(refreshLiveRows,1000)" in package[NEW + "assets/card-composer-renderer.js"]
    assert b"itemPicker" in package[NEW + "assets/card-layout-editor.html"]
    homepage = package[NEW + "assets/dashboard.html"]
    assert b"1.10.0-46" in homepage and b"1.9.0-45" not in homepage
    assert b"mb-card-native" in package[NEW + "assets/card-composer.css"]
    assert b"speedKey=" in package[NEW + "assets/card-item-registry.js"]
    assert b"@derived.cpu_used_percent" in package[NEW + "assets/card-item-registry.js"]
    assert b"mb-card-columns" in package[NEW + "assets/card-composer-renderer.js"]
    assert b"mb-card-shell" in package[NEW + "assets/card-composer-renderer.js"]
    assert b"button.mb-card-shell:focus-visible" in package[NEW + "assets/card-composer.css"]
    app = package[NEW + "__init__.py"].decode()
    ast.parse(app)
    assert "Standalone managed MonitorBox UI 1.10.0 build 46." in app
    assert "not in (1, 2, 3)" in app
    with tempfile.TemporaryDirectory() as tmp:
        a = candidate.build(ROOT, Path(tmp) / "first").read_bytes()
        b = candidate.build(ROOT, Path(tmp) / "second").read_bytes()
        assert a == b, "UI46 ZIP must be reproducible"
        print("UI46 immutable UI45 parent, Core routes, v3 snapshots, script syntax "
              "and deterministic package: PASS " + hashlib.sha256(a).hexdigest())


if __name__ == "__main__":
    main()
