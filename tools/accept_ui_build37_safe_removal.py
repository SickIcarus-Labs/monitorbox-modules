#!/usr/bin/env python3
"""Acceptance for UI build37 safe Core removal preflight."""
from __future__ import annotations

import tempfile
from pathlib import Path

import build_first_party_ui_build36 as parent
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
    modules = assets["modules.js"].decode("utf-8")

    assert "/remove/review" in modules
    assert "Safe module-removal review is unavailable on this Core" in modules
    assert "Update Core before removing modules." in modules
    assert "safe_simple_remove" in modules
    assert "/remove/apply" in modules
    assert 'input.type = "password"' in modules
    assert "Affected Resources:" in modules
    assert "Affected Checks:" in modules

    review_call = modules.index("moduleRemovalReviewRequest(moduleId)")
    apply_call = modules.index("/remove/apply", review_call)
    simple_gate = modules.index("safe_simple_remove", review_call)
    assert review_call < apply_call
    assert review_call < simple_gate

    parent_files = parent._package_files(ROOT)
    parent_prefix = parent.TARGET_IMPORT_PACKAGE + "/"
    for name in ("aggregate-evidence.js", "v1-beta-polish.js"):
        expected = parent_files[parent_prefix + "assets/" + name].replace(
            candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
        ).replace(
            candidate.PARENT_IMPORT_PACKAGE.encode(),
            candidate.TARGET_IMPORT_PACKAGE.encode(),
        )
        assert assets[name] == expected, name

    assert "unifi-component" not in assets["v1-beta-polish.js"].decode("utf-8").lower()

    with tempfile.TemporaryDirectory() as raw:
        first = candidate.build(ROOT, Path(raw) / "one").read_bytes()
        second = candidate.build(ROOT, Path(raw) / "two").read_bytes()
        assert first == second

    print("UI build37 safe removal preflight acceptance passed")


if __name__ == "__main__":
    main()
