#!/usr/bin/env python3
"""UI 1.4.0 build39 source/package gate against certified UI 1.3.1 build35."""

from __future__ import annotations

import tempfile
from pathlib import Path

import build_first_party_ui_build35 as previous
import build_first_party_ui_build39 as candidate

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    source = candidate._source(ROOT)
    assert source.startswith(b"'use strict';")
    assert b"site?.cards" in source
    assert b"card_layout" not in source
    assert b"dashboardConfiguration" not in source

    parent = previous._package_files(ROOT)
    packaged = candidate._package_files(ROOT)
    before = previous.PARENT_IMPORT_PACKAGE if False else previous.TARGET_IMPORT_PACKAGE
    pfx = before + "/"
    cfx = candidate.TARGET_IMPORT_PACKAGE + "/"
    assert set(path.removeprefix(pfx) for path in parent) | {
        "assets/card-projection.js"
    } == set(path.removeprefix(cfx) for path in packaged)

    init = packaged[cfx + "__init__.py"]
    assert b"Standalone managed MonitorBox UI 1.4.0 build 39." in init
    assert candidate.UI_GENERATION.encode() in init
    assert candidate.PARENT_GENERATION.encode() not in init
    assert b'    "card-projection.js": "text/javascript",' in init
    assert b"configuration_peer_navigation_presentation" in init

    expected_script = (
        f'<script src="/static/card-projection.js?v={candidate.UI_GENERATION}" defer></script>'
    ).encode()
    dashboard = packaged[cfx + "assets/dashboard.html"]
    previous_dashboard = parent[pfx + "assets/dashboard.html"]
    expected_dashboard = previous_dashboard.replace(
        candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
    ).replace(
        candidate.PARENT_IMPORT_PACKAGE.encode(), candidate.TARGET_IMPORT_PACKAGE.encode()
    ).replace(b"</body>", expected_script + b"</body>", 1)
    assert dashboard == expected_dashboard, "unexpected dashboard surface mutation"
    assert dashboard.count(expected_script) == 1
    assert b"aggregate-evidence.js" not in dashboard
    assert packaged[cfx + "assets/card-projection.js"] == source

    # No unrelated accepted UI asset may drift. This protects all existing
    # modules, Configuration peer navigation, dashboard graphs, and shell.
    for rel, payload in (
        (path.removeprefix(pfx), value)
        for path, value in parent.items()
        if path.startswith(pfx + "assets/") and path != pfx + "assets/dashboard.html"
    ):
        expected = payload.replace(
            candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
        ).replace(
            candidate.PARENT_IMPORT_PACKAGE.encode(), candidate.TARGET_IMPORT_PACKAGE.encode()
        )
        assert packaged[cfx + rel] == expected, rel

    with tempfile.TemporaryDirectory() as raw:
        a = candidate.build(ROOT, Path(raw) / "first").read_bytes()
        b = candidate.build(ROOT, Path(raw) / "second").read_bytes()
        assert a == b, "UI build39 is not deterministic"

    print("UI build39 package/source acceptance: PASS (accepted build35 baseline)")


if __name__ == "__main__":
    main()
