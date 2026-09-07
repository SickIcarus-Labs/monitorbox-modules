#!/usr/bin/env python3
"""Regression for PySNMP MIB loading from the managed SNMP build-6 ZIP."""

from __future__ import annotations

import importlib
import sys
import zipfile
from pathlib import Path

PACKAGE_NAME = "com.sickicarus.monitorbox.snmp-1.0.4-build6.zip"
REQUIRED_SHIMS = {
    "pysnmp/__init__.py",
    "pysnmp/hlapi/__init__.py",
    "pysnmp/hlapi/v3arch/__init__.py",
    "pysnmp/smi/mibs/__init__.py",
    "pysnmp/smi/mibs/instances/__init__.py",
}


def _purge_vendor_modules() -> None:
    for name in tuple(sys.modules):
        if (
            name == "pysnmp"
            or name.startswith("pysnmp.")
            or name == "pyasn1"
            or name.startswith("pyasn1.")
        ):
            sys.modules.pop(name, None)


def _assert_zip_backed(module, package: Path, label: str) -> None:
    module_file = getattr(module, "__file__", None)
    if not module_file or str(package.resolve()) not in str(module_file):
        raise AssertionError(f"{label} escaped the managed artifact: {module_file!r}")
    loader = getattr(module, "__loader__", None)
    if loader is None or not hasattr(loader, "_files"):
        raise AssertionError(
            f"{label} did not resolve through PySNMP-compatible zipimport: {loader!r}"
        )


def accept() -> None:
    root = Path(__file__).resolve().parent.parent
    package = root / "packages" / PACKAGE_NAME
    if not package.is_file():
        raise AssertionError(f"managed SNMP build 6 package is missing: {package}")

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        missing = sorted(REQUIRED_SHIMS - names)
        if missing:
            raise AssertionError(f"SNMP build 6 omitted MIB zipimport shims: {missing}")

    _purge_vendor_modules()
    sys.path.insert(0, str(package.resolve()))
    try:
        pysnmp = importlib.import_module("pysnmp")
        mibs = importlib.import_module("pysnmp.smi.mibs")
        instances = importlib.import_module("pysnmp.smi.mibs.instances")
        hlapi = importlib.import_module("pysnmp.hlapi.v3arch.asyncio")

        _assert_zip_backed(pysnmp, package, "PySNMP")
        _assert_zip_backed(mibs, package, "PySNMP core MIB package")
        _assert_zip_backed(instances, package, "PySNMP MIB instances package")

        # Broad Leaf failed at this exact operation. Constructing the engine
        # forces PySNMP to initialize its MIB instrumentation and load the
        # bundled SNMPv2/core MIB modules through its configured MIB sources.
        engine = hlapi.SnmpEngine()
        engine.get_mib_builder().load_modules("SNMPv2-MIB")
        engine.close_dispatcher()
    finally:
        if sys.path and sys.path[0] == str(package.resolve()):
            sys.path.pop(0)
        _purge_vendor_modules()

    print("managed SNMP 1.0.4 build 6 MIB zipimport acceptance: PASS", flush=True)


def main() -> None:
    accept()


if __name__ == "__main__":
    main()
