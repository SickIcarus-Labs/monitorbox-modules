#!/usr/bin/env python3
"""Package/source acceptance for the final UI build37 (#353 + #220 slice)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import build_first_party_ui_build35 as parent
import build_first_party_ui_build37 as candidate

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
    network_compat = assets["v1-beta-polish.js"].decode("utf-8")

    assert candidate.UI_GENERATION.encode() in init
    assert candidate.PARENT_GENERATION.encode() not in init

    # #353: compatibility is checked non-mutating before either destructive path.
    assert "/remove/review" in modules
    assert "Safe module-removal review is unavailable on this Core" in modules
    assert "Update Core before removing modules." in modules
    assert "safe_simple_remove" in modules
    assert "/remove/apply" in modules
    assert 'input.type = "password"' in modules
    assert "Current administrator password" in modules
    assert "Affected Resources:" in modules
    assert "Affected Checks:" in modules
    review_call = modules.index("moduleRemovalReviewRequest(moduleId)")
    apply_call = modules.index("/remove/apply", review_call)
    simple_gate = modules.index("safe_simple_remove", review_call)
    assert review_call < apply_call
    assert review_call < simple_gate

    # #220 requested provider-loss presentation slice.
    assert "directEvidence" in aggregate
    assert "evidenceSummary" in aggregate
    assert "pruneEmptyDirectories" in aggregate
    assert "MonitorBoxAggregateEvidence" in aggregate
    assert "unifi-component" not in network_compat.lower()
    assert "object?.kind==='network_device'" in network_compat
    aggregate_lower = aggregate.lower()
    for forbidden in (
        "unifi",
        "scrypted",
        "portainer",
        "nut",
        "object.id==='network'",
        'object.id==="network"',
        "object.id==='cameras'",
        "object.id==='power'",
    ):
        assert forbidden not in aggregate_lower, forbidden

    # Existing shell/navigation remains the accepted build35 implementation.
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

    print("UI build37 #353/#220 package acceptance passed")


if __name__ == "__main__":
    main()
