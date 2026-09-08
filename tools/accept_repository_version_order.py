#!/usr/bin/env python3
"""Regression for semantic rather than lexical version ordering in signed indexes."""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).with_name("build_repository.py")


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(SOURCE))
    helper = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "semantic_version_key"),
        None,
    )
    if helper is None:
        raise AssertionError("build_repository.py has no semantic_version_key helper")

    module = ast.Module(body=[helper], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    key = namespace["semantic_version_key"]

    versions = ["1.1.9", "1.1.10", "1.1.2", "2.0.0", "1.10.0"]
    ordered = sorted(versions, key=key)  # type: ignore[arg-type]
    expected = ["1.1.2", "1.1.9", "1.1.10", "1.10.0", "2.0.0"]
    if ordered != expected:
        raise AssertionError(f"semantic version ordering regressed: {ordered!r}")

    marker = 'semantic_version_key(value["manifest"]["version"])'
    if marker not in text:
        raise AssertionError("signed module sort does not use semantic_version_key")

    print("signed repository semantic version ordering: PASS")


if __name__ == "__main__":
    main()
