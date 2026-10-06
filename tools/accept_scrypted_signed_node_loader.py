#!/usr/bin/env python3
"""Acceptance for Scrypted 2.3.1 build 7 signed Node-loader repair."""
from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import build_first_party_scrypted_231 as release

EXPECTED_PACKAGE = "com.sickicarus.monitorbox.scrypted-2.3.1-build7.zip"
EXPECTED_IMPORT = "monitorbox_scrypted_v231_b7"


def _load_helper(path: Path):
    spec = importlib.util.spec_from_file_location("scrypted_node_runtime_acceptance", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load Scrypted Node runtime helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _executable(path: Path) -> None:
    path.write_bytes(b"synthetic executable\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    predecessor = root / "packages" / release.PREVIOUS_FILENAME
    if not predecessor.is_file():
        raise AssertionError(f"immutable Scrypted predecessor missing: {predecessor}")

    with tempfile.TemporaryDirectory(prefix="scrypted-231-accept-") as raw:
        temp = Path(raw)
        first = temp / "first"
        second = temp / "second"
        first.mkdir()
        second.mkdir()
        shutil.copy2(predecessor, first / predecessor.name)
        shutil.copy2(predecessor, second / predecessor.name)

        builder = root / "tools" / "build_first_party_scrypted_231.py"
        subprocess.run(
            [sys.executable, str(builder), "--output-dir", str(first)], check=True
        )
        subprocess.run(
            [sys.executable, str(builder), "--output-dir", str(second)], check=True
        )
        one = first / EXPECTED_PACKAGE
        two = second / EXPECTED_PACKAGE
        if not one.is_file() or not two.is_file():
            raise AssertionError("Scrypted loader-repair package was not built")
        if one.name != EXPECTED_PACKAGE or two.name != EXPECTED_PACKAGE:
            raise AssertionError("Scrypted loader-repair package identity changed")
        if one.read_bytes() != two.read_bytes():
            raise AssertionError("Scrypted loader-repair package is not reproducible")

        with zipfile.ZipFile(one) as archive:
            names = set(archive.namelist())
            runtime_name = f"{EXPECTED_IMPORT}/runtime.py"
            helper_name = f"{EXPECTED_IMPORT}/node_runtime.py"
            if {runtime_name, helper_name} - names:
                raise AssertionError("Scrypted loader-repair package omitted runtime authority")
            runtime = archive.read(runtime_name).decode("utf-8")
            helper = archive.read(helper_name).decode("utf-8")
        if "from .node_runtime import node_launch_prefix" not in runtime:
            raise AssertionError("Scrypted runtime did not import signed Node launch helper")
        if "node_argv = node_launch_prefix()" not in runtime:
            raise AssertionError("Scrypted runtime did not resolve signed Node argv")
        if "*node_argv," not in runtime:
            raise AssertionError("Scrypted runtime did not execute signed Node through loader argv")
        if 'create_subprocess_exec(\n            node,' in runtime:
            raise AssertionError("Scrypted runtime still directly executes Node ELF")
        if "MONITORBOX_MODULE_NODE_LOADER" not in helper or "MONITORBOX_MODULE_NODE_LIBRARY_PATH" not in helper:
            raise AssertionError("Scrypted helper omitted signed loader/library authority")

        helper_module = _load_helper(root / "sources" / "scrypted" / "2.3.1-build7" / "node_runtime.py")
        signed = temp / "signed"
        loader = signed / "loader" / "ld-linux-test.so"
        node = signed / "usr" / "local" / "bin" / "node"
        lib = signed / "lib"
        loader.parent.mkdir(parents=True)
        node.parent.mkdir(parents=True)
        lib.mkdir(parents=True)
        _executable(loader)
        _executable(node)

        keys = (
            "MONITORBOX_MODULE_NODE",
            "MONITORBOX_MODULE_NODE_LOADER",
            "MONITORBOX_MODULE_NODE_LIBRARY_PATH",
        )
        saved = {key: os.environ.get(key) for key in keys}
        try:
            os.environ[keys[0]] = str(node)
            os.environ[keys[1]] = str(loader)
            os.environ[keys[2]] = str(lib)
            if helper_module.node_launch_prefix() != (
                str(loader), "--library-path", str(lib), str(node)
            ):
                raise AssertionError("signed Node launch argv changed")

            os.environ.pop(keys[1])
            try:
                helper_module.node_launch_prefix()
            except RuntimeError as exc:
                if "incomplete scaffold-selected signed Node runtime" not in str(exc):
                    raise
            else:
                raise AssertionError("partial signed Node authority was accepted")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    print("Scrypted 2.3.1 build 7 signed Node-loader repair: PASS", flush=True)


if __name__ == "__main__":
    main()
