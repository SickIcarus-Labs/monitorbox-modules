#!/usr/bin/env python3
"""Acceptance for immutable UI40 successor and pre-route Core capability guard."""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

import build_first_party_ui_build35 as accepted
import build_first_party_ui_build40 as candidate
import stage_p1_85_ui_build40 as staging

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    source = candidate._source(ROOT)
    assert b"site?.cards" in source
    assert b"card_layout" not in source
    assert b"dashboardConfiguration" not in source
    assert candidate.UI_GENERATION == "1.4.1-40"

    files = candidate._package_files(ROOT)
    parent = accepted._package_files(ROOT)
    old = accepted.TARGET_IMPORT_PACKAGE + "/"
    new = candidate.TARGET_IMPORT_PACKAGE + "/"
    assert {path.removeprefix(old) for path in parent} | {
        "assets/card-projection.js"
    } == {path.removeprefix(new) for path in files}
    assert files[new + "assets/card-projection.js"] == source

    app = files[new + "__init__.py"].decode("utf-8")
    ast.parse(app)
    assert "Standalone managed MonitorBox UI 1.4.1 build 40" in app
    assert "CARD_PROJECTION_CONTRACT_VERSION" in app
    assert "Core dashboard-card projection contract v1" in app
    assert app.count("def _require_card_projection_contract(") == 1

    # A rejected old Core must fail before ANY UI route/middleware mutation.
    syntax = ast.parse(app)
    installer = next(
        n for n in syntax.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "install"
    )
    first = installer.body[0]
    assert isinstance(first, ast.Expr)
    assert isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name)
    assert first.value.func.id == "_require_card_projection_contract"
    guard = next(
        n for n in syntax.body
        if isinstance(n, ast.FunctionDef)
        and n.name == "_require_card_projection_contract"
    )
    assert not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"add_get", "append", "add_route"}
        for n in ast.walk(guard)
    ), "Admission guard may not mutate the application"

    expected = (
        f'<script src="/static/card-projection.js?v={candidate.UI_GENERATION}" defer></script>'
    ).encode()
    inherited = parent[old + "assets/dashboard.html"].replace(
        candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
    ).replace(
        candidate.PARENT_IMPORT_PACKAGE.encode(), candidate.TARGET_IMPORT_PACKAGE.encode()
    )
    assert files[new + "assets/dashboard.html"] == inherited.replace(
        b"</body>", expected + b"</body>", 1
    )
    for path, data in parent.items():
        relative = path.removeprefix(old)
        if relative in {"__init__.py", "assets/dashboard.html"}:
            continue
        assert files[new + relative] == data.replace(
            candidate.PARENT_GENERATION.encode(), candidate.UI_GENERATION.encode()
        ).replace(
            candidate.PARENT_IMPORT_PACKAGE.encode(), candidate.TARGET_IMPORT_PACKAGE.encode()
        ), relative

    manifest = staging.ENTRY["manifest"]
    assert (manifest["version"], manifest["build"]) == ("1.4.1", 40)
    assert manifest["requires_core"] == ">=2.6.0 <3.0.0"
    intent = json.loads((ROOT / "release-intents/ui-1.4.1-build40.json").read_text())
    assert intent["supersedes_dev"] == {
        "version": "1.4.0",
        "build": 39,
        "sha256": "e47fbf58165c73a2d212f28c26cba2a33fa15c3b3740e569f9e60d930a1cd61e",
        "authority_commit": "7a5bf71732fe41a95664df861661541317eb89a8",
    }

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        first = candidate.build(ROOT, root / "first").read_bytes()
        second = candidate.build(ROOT, root / "second").read_bytes()
        assert first == second

        catalog_path = root / "catalog.source.json"
        catalog_path.write_bytes((ROOT / "catalog.source.json").read_bytes())
        assert staging.stage(catalog_path) is True
        staged = catalog_path.read_bytes()
        assert staging.stage(catalog_path) is False
        assert catalog_path.read_bytes() == staged
        installed = [
            row for row in json.loads(staged)["modules"]
            if row["manifest"]["module_id"] == manifest["module_id"]
            and row["manifest"]["build"] == 40
        ]
        assert installed == [staging.ENTRY]

    print("UI 1.4.1 build40 source/package/card contract acceptance: PASS")


if __name__ == "__main__":
    main()
