#!/usr/bin/env python3
"""UI43 immutable inheritance, wired assets, snapshot schema and ZIP qualification."""
from __future__ import annotations

import ast
import hashlib
import subprocess
import tempfile
from pathlib import Path

import build_first_party_ui_build42 as parent
import build_first_party_ui_build43 as candidate

ROOT = Path(__file__).resolve().parent.parent
OLD = parent.TARGET_IMPORT_PACKAGE + "/"
NEW = candidate.TARGET_IMPORT_PACKAGE + "/"


def main() -> None:
    source = candidate._sources(ROOT)
    assert set(source) == set(candidate.SOURCE_BLOBS)
    for name in candidate.SOURCE_BLOBS:
        if name.endswith(".js"):
            subprocess.run(["node", "--check", str(ROOT / "sources/ui/1.7.0-build43" / name)], check=True)

    inherited = parent._package_files(ROOT)
    files = candidate._package_files(ROOT)
    expected_new = {"assets/card-item-registry.js", "assets/card-composer-renderer.js",
                    "assets/card-composer.css"}
    assert {p.removeprefix(OLD) for p in inherited} | expected_new == {
        p.removeprefix(NEW) for p in files}
    assert files[NEW + "assets/card-projection.js"] == inherited[OLD + "assets/card-projection.js"]
    assert files[NEW + "assets/graph-layout.js"] == inherited[OLD + "assets/graph-layout.js"]
    html = files[NEW + "assets/dashboard.html"]
    assert html.index(b"card-item-registry.js") < html.index(b"card-layout-policy.js")
    assert html.index(b"card-layout.js") < html.index(b"card-composer-renderer.js")
    assert html.count(b"card-composer.css") == 1
    assert b"showDiscovered" not in files[NEW + "assets/card-layout-editor.html"]
    assert b"itemPicker" in files[NEW + "assets/card-layout-editor.html"]
    assert b"pickerChosen" in files[NEW + "assets/card-layout-editor.js"]
    assert b"const SCHEMA=3;" in files[NEW + "assets/card-layout-policy.js"]
    assert b"snapshot-paired" in files[NEW + "assets/card-layout.js"]
    app = files[NEW + "__init__.py"].decode()
    ast.parse(app)
    assert 'not in (1, 2, 3)' in app
    assert 'current["schema_version"] if current is not None else 3' in app
    assert "register_provider(app" in app
    with tempfile.TemporaryDirectory() as temp:
        a = candidate.build(ROOT, Path(temp) / "one").read_bytes()
        b = candidate.build(ROOT, Path(temp) / "two").read_bytes()
        assert a == b, "Non-deterministic UI43 ZIP"
        sha = hashlib.sha256(a).hexdigest()
    print(f"UI43 inherited accepted UI42, script syntax, v1/v2/v3 schema, deterministic ZIP: PASS {sha}")


if __name__ == "__main__":
    main()
