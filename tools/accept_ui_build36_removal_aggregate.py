#!/usr/bin/env python3
"""Package/source acceptance for UI build36 (#353 primary, #220 dividend)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import build_first_party_ui_build35 as parent
import build_first_party_ui_build36 as candidate

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    files = candidate._package_files(ROOT)
    prefix = candidate.TARGET_IMPORT_PACKAGE + "/"
    assets = {
        path.removeprefix(prefix + "assets/"): payload
        for path, payload in files.items()
        if path.startswith(prefix + "assets/")
    }
    init = files[prefix + "__init__.py"]
    modules = assets["modules.js"].decode("utf-8")
    aggregate = assets["aggregate-evidence.js"].decode("utf-8")
    dashboard = assets["dashboard.html"].decode("utf-8")

    assert candidate.UI_GENERATION.encode() in init
    assert candidate.PARENT_GENERATION.encode() not in init
    assert "/remove/apply" in modules
    assert "review_required" in modules
    assert 'input.type = "password"' in modules
    assert "Current administrator password" in modules
    assert "Affected Resources:" in modules
    assert "provider/check authorit" in modules

    assert "directEvidence" in aggregate
    assert "evidenceSummary" in aggregate
    assert "pruneEmptyDirectories" in aggregate
    assert "MonitorBoxAggregateEvidence" in aggregate
    assert "aggregate-evidence.js" in dashboard
    lower = aggregate.lower()
    for forbidden in ("unifi", "scrypted", "portainer", "nut", "object.id==='network'", "object.id==='cameras'", "object.id==='power'"):
        assert forbidden not in lower, forbidden

    parent_files = parent._package_files(ROOT)
    parent_prefix = parent.TARGET_IMPORT_PACKAGE + "/"
    for name in (
        "settings-shell.js",
        "settings-shell.css",
        "configuration-peer-navigation.js",
        "configuration-peer-navigation.css",
        "contextual-configuration.js",
        "contextual-configuration.css",
        "app-shell.js",
        "app-shell.css",
        "global-debug.js",
        "global-debug.css",
    ):
        expected = parent_files[parent_prefix + "assets/" + name].replace(
            candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
        ).replace(
            candidate.PARENT_IMPORT_PACKAGE.encode(),
            candidate.TARGET_IMPORT_PACKAGE.encode(),
        )
        assert assets[name] == expected, name

    with tempfile.TemporaryDirectory() as raw:
        first = candidate.build(ROOT, Path(raw) / "one").read_bytes()
        second = candidate.build(ROOT, Path(raw) / "two").read_bytes()
        assert first == second

    print("UI build36 #353/#220 package acceptance passed")


if __name__ == "__main__":
    main()
