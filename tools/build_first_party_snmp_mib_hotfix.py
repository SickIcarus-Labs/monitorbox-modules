#!/usr/bin/env python3
"""Build SNMP 1.0.4 build 6 packaging-only MIB zipimport hotfix.

Build 5 proved that the vendored PySNMP/PyASN1 code can be imported directly
from the managed module ZIP. Broad Leaf then exposed the next resource boundary:
PySNMP's own MIB loader imports ``pysnmp.smi.mibs`` and
``pysnmp.smi.mibs.instances`` and only uses its ZIP-aware loader when those
names resolve to concrete zipimport packages. The upstream wheel leaves both as
implicit namespace packages, which makes PySNMP fall back to filesystem access
against a virtual ``...zip/pysnmp/smi/mibs`` path.

Build 6 is semantically identical to 1.0.4 build 5. It reuses the verified build
pipeline and adds explicit compatibility shims for those two upstream namespace
levels. Published build 5 remains immutable.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import build_first_party_snmp as base

MODULE_ID = base.MODULE_ID
MODULE_VERSION = "1.0.4"
MODULE_BUILD = 6
IMPORT_PACKAGE = "monitorbox_snmp_b6"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
PREVIOUS_FILENAME = f"{MODULE_ID}-1.0.4-build5.zip"
MIB_NAMESPACE_SHIMS = (
    "pysnmp/smi/mibs/__init__.py",
    "pysnmp/smi/mibs/instances/__init__.py",
)


def _configure_build6() -> None:
    """Project build-6 identity into the verified build-5 packaging machinery."""
    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base.HISTORICAL_FILENAMES = frozenset(
        set(base.HISTORICAL_FILENAMES) | {PREVIOUS_FILENAME}
    )
    base.ZIPIMPORT_NAMESPACE_SHIMS = tuple(
        dict.fromkeys((*base.ZIPIMPORT_NAMESPACE_SHIMS, *MIB_NAMESPACE_SHIMS))
    )


def build(root: Path, output_dir: Path) -> Path:
    previous = output_dir / PREVIOUS_FILENAME
    if not previous.is_file():
        raise SystemExit(
            f"immutable predecessor is missing: {previous}; build 6 must not recreate build 5"
        )
    _configure_build6()
    target = base.build(root, output_dir)
    if target.name != FILENAME:
        raise SystemExit(f"unexpected SNMP build-6 target: {target}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
