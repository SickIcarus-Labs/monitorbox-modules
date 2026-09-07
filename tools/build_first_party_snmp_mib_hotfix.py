#!/usr/bin/env python3
"""Build SNMP 1.0.4 build 6 packaging-only PySNMP ZIP-MIB hotfix.

Build 5 proved that the vendored PySNMP/PyASN1 code imports directly from the
managed module ZIP. Broad Leaf then exposed a PySNMP 7.1.29 compatibility bug
inside its MIB loader:

* ``ZipMibSource`` recognizes ZIP loaders only by the private ``_files``
  attribute, which Python 3.13's ``zipimporter`` no longer exposes (it provides
  ``_get_files()`` instead). PySNMP consequently misclassifies an in-ZIP MIB
  package as a filesystem directory and probes ``...zip/pysnmp/smi/mibs`` with
  ``os.listdir``/``os.stat``.
* Once ZIP detection works, debug-mode PySNMP calls ``runpy.run_path`` on an
  in-ZIP MIB path. That API requires a real filesystem path, so ZIP-backed MIBs
  must execute the code object already read by ``ZipMibSource`` instead.

Build 6 is semantically identical to 1.0.4 build 5. It reuses the pinned,
hash-verified PySNMP 7.1.29 wheel and applies only these two deterministic
ZIP-runtime compatibility adaptations to the vendored ``pysnmp/smi/builder.py``.
Published build 5 remains immutable.
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
PYSNMP_BUILDER = "pysnmp/smi/builder.py"


def _patch_pysnmp_builder(payload: bytes) -> bytes:
    text = payload.decode("utf-8")

    # Python <=3.12 exposed zipimporter's archive directory mapping as _files.
    # Python 3.13 removed that attribute but retained _get_files(). Cache either
    # representation once so the rest of PySNMP's ZIP source can stay unchanged.
    old_condition = (
        '            if hasattr(p, "__loader__") and hasattr(p.__loader__, "_files"):\n'
    )
    new_condition = (
        '            if hasattr(p, "__loader__") and (\n'
        '                hasattr(p.__loader__, "_files")\n'
        '                or hasattr(p.__loader__, "_get_files")\n'
        '            ):\n'
    )
    if text.count(old_condition) != 1:
        raise SystemExit("PySNMP ZipMibSource loader-detection marker changed")

    old_file_refs = text.count("self.__loader._files")
    if old_file_refs != 4:
        raise SystemExit(
            f"PySNMP ZipMibSource _files shape changed: expected 4 references, got {old_file_refs}"
        )
    text = text.replace("self.__loader._files", "self.__loader_files")
    text = text.replace(old_condition, new_condition, 1)

    old_loader_assignment = (
        "                self.__loader = p.__loader__\n"
        '                self._srcName = self._srcName.replace(".", os.sep)\n'
    )
    new_loader_assignment = (
        "                self.__loader = p.__loader__\n"
        "                if hasattr(self.__loader, \"_files\"):\n"
        "                    self.__loader_files = self.__loader._files\n"
        "                else:\n"
        "                    self.__loader_files = self.__loader._get_files()\n"
        '                self._srcName = self._srcName.replace(".", os.sep)\n'
    )
    if text.count(old_loader_assignment) != 1:
        raise SystemExit("PySNMP ZipMibSource loader assignment marker changed")
    text = text.replace(old_loader_assignment, new_loader_assignment, 1)

    # ``read()`` already returned a compiled code object for both source kinds.
    # Preserve runpy/breakpoint behavior for real directories, but never ask
    # runpy to open a virtual path that lives inside the managed ZIP.
    old_execution = '''            try:\n                if __debug__:\n                    runpy.run_path(\n                        modPath, g\n                    )  # IMPORTANT: enable break points in loaded MIBs\n                else:\n                    exec(codeObj, g)\n'''
    new_execution = '''            try:\n                if __debug__ and isinstance(mibSource, DirMibSource):\n                    runpy.run_path(\n                        modPath, g\n                    )  # IMPORTANT: enable break points for filesystem MIBs\n                else:\n                    exec(codeObj, g)\n'''
    if text.count(old_execution) != 1:
        raise SystemExit("PySNMP MIB execution marker changed")
    text = text.replace(old_execution, new_execution, 1)

    required = (
        'or hasattr(p.__loader__, "_get_files")',
        "self.__loader_files = self.__loader._get_files()",
        "if __debug__ and isinstance(mibSource, DirMibSource):",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise SystemExit(f"PySNMP build-6 ZIP compatibility patch incomplete: {missing}")
    return text.encode("utf-8")


def _configure_build6() -> None:
    """Project build-6 identity and vendor patch into the verified build pipeline."""
    base.MODULE_VERSION = MODULE_VERSION
    base.MODULE_BUILD = MODULE_BUILD
    base.IMPORT_PACKAGE = IMPORT_PACKAGE
    base.FILENAME = FILENAME
    base.HISTORICAL_FILENAMES = frozenset(
        set(base.HISTORICAL_FILENAMES) | {PREVIOUS_FILENAME}
    )

    original_vendor_files = base._vendor_files

    def vendor_files_build6() -> dict[str, bytes]:
        files = original_vendor_files()
        if PYSNMP_BUILDER not in files:
            raise SystemExit(f"vendored PySNMP omitted {PYSNMP_BUILDER}")
        files[PYSNMP_BUILDER] = _patch_pysnmp_builder(files[PYSNMP_BUILDER])
        return files

    base._vendor_files = vendor_files_build6


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
