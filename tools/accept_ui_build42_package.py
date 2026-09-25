#!/usr/bin/env python3
"""UI42 source/ZIP invariants: inherited UI41, snapshot-compatible content, tabs."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import build_first_party_ui_build41 as parent
import build_first_party_ui_build42 as candidate

ROOT = Path(__file__).resolve().parent.parent
OLD = parent.TARGET_IMPORT_PACKAGE + "/"
NEW = candidate.TARGET_IMPORT_PACKAGE + "/"


def main() -> None:
    source = candidate._sources(ROOT)
    assert set(source) == set(candidate.SOURCE_BLOBS)
    for name in ("card-layout-policy.js", "card-layout.js", "card-layout-editor.js",
                 "dashboard-editor-tabs.js"):
        subprocess.run(["node", "--check", str(ROOT/"sources/ui/1.6.0-build42"/name)],
                       check=True)

    inherited = parent._package_files(ROOT)
    files = candidate._package_files(ROOT)
    assert {key.removeprefix(OLD) for key in inherited} | {
        "assets/dashboard-editor-tabs.js", "assets/dashboard-editor-tabs.css"
    } == {key.removeprefix(NEW) for key in files}
    assert files[NEW+"assets/card-projection.js"] == inherited[OLD+"assets/card-projection.js"]
    assert b"#card-layout-edit" not in files[NEW+"assets/card-layout.js"]
    assert b"hidden_member_ids" in files[NEW+"assets/card-layout-policy.js"]
    assert b"homepage_origin" in files[NEW+"assets/card-layout-policy.js"]
    assert b"system_role" in files[NEW+"assets/card-layout-policy.js"]
    assert b"showDiscovered" in files[NEW+"assets/card-layout-editor.html"]
    assert b"contentMembers" in files[NEW+"assets/card-layout-editor.html"]
    assert b"dashboard-editor-tabs" in files[NEW+"assets/dashboard-editor-tabs.js"]
    assert b"/settings/cards" in files[NEW+"assets/configuration-peer-navigation.js"]
    assert b"Dashboard Cards" not in files[NEW+"assets/dashboard.html"]

    app = files[NEW+"__init__.py"].decode()
    ast.parse(app)
    assert '"/settings/cards", dashboard_cards_page' in app
    assert "app.middlewares.append(dashboard_editor_tabs_middleware)" in app
    assert 'request.path not in ("/settings/dashboard", "/settings/cards")' in app
    assert '"com.sickicarus.monitorbox.ui", _automatic_layout_snapshot' in app
    assert "MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION != 2" in app
    # UI preference schema v1 extends each saved card with optional versioned
    # content; every already-written UI41 revision retains its exact identity.
    assert b"const SCHEMA=1;" in files[NEW+"assets/card-layout-policy.js"]
    assert b"schema_version:1" in files[NEW+"assets/card-layout-editor.js"]
    assert b"presentation" in files[NEW+"assets/card-layout.js"]
    assert b"baseCoreCard(view,shown)" in files[NEW+"assets/card-layout.js"]
    assert b"hidden_member_ids" in files[NEW+"assets/card-layout.js"]
    assert b"parityNetworkChildren=" not in files[NEW+"assets/card-layout.js"]

    with tempfile.TemporaryDirectory() as tmp:
        first = candidate.build(ROOT, Path(tmp)/"one").read_bytes()
        second = candidate.build(ROOT, Path(tmp)/"two").read_bytes()
        assert first == second
        digest = hashlib.sha256(first).hexdigest()
        assert len(digest) == 64
    print(f"UI42 immutable-parent, scripts, opaque content and deterministic ZIP: PASS sha256={digest}")


if __name__ == "__main__":
    main()
