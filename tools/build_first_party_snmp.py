#!/usr/bin/env python3
"""Build self-contained managed SNMP 1.0.3 build 4 for pruned Core.

Historical builds remain immutable. Build 4 replaces the hidden Net-SNMP binary
runtime dependency with pinned pure-Python PySNMP/PyASN1 packaged inside the
signed module artifact. Core continues to provide only the generic Python module
runtime and cryptography dependency used by multiple platform facilities.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.snmp"
MODULE_VERSION = "1.0.3"
MODULE_BUILD = 4
IMPORT_PACKAGE = "monitorbox_snmp_b4"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset(
    {
        f"{MODULE_ID}-1.0.0-build1.zip",
        f"{MODULE_ID}-1.0.1-build2.zip",
        f"{MODULE_ID}-1.0.2-build3.zip",
    }
)

BASE_SOURCE_BLOBS = {"__init__.py": "df242a51b7845c4e852bb15419360f8ac0abdf7e"}
BUILD2_SOURCE_BLOBS = {"runtime.py": "8467c756dcf502b48a40a7bac81f6113a48b88b6"}
BUILD3_SOURCE_BLOBS = {"runtime.py": "ae46133d246d1c235165fd52e26e7d83ec71661d"}
BUILD4_SOURCE_BLOBS = {"runtime.py": "08a000cdd59797aeb1929de0e2e67f40959709db"}

VENDOR_WHEELS = {
    "pysnmp-7.1.29-py3-none-any.whl": "6d08124574c474853870f20d728b54335b42fb1e68068bbb486ec077b3d052cf",
    "pyasn1-0.6.4-py3-none-any.whl": "deda9277cfd454080ec40b207fb6df82206a3a2688735233cdcd8d3d565f088b",
}

_CORE_IMPORT_REWRITES = (
    ("from ...adapters", "from monitorbox.v2.adapters"),
    ("from ...config", "from monitorbox.v2.config"),
    ("from ...model", "from monitorbox.v2.model"),
    ("from ...plugin_api", "from monitorbox.v2.plugin_api"),
)


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _verified_directory(source_root: Path, expected: dict[str, str], *, label: str) -> dict[str, bytes]:
    actual = {path.name for path in source_root.iterdir() if path.is_file()}
    if actual != set(expected):
        raise SystemExit(f"{label} source shape changed: expected={sorted(expected)}, actual={sorted(actual)}")
    result: dict[str, bytes] = {}
    for name, blob in expected.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != blob:
            raise SystemExit(f"{label} source drift for {name}: expected {blob}, got {actual_blob}")
        result[name] = payload
    return result


def _source_files(root: Path) -> dict[str, bytes]:
    snmp_root = root / "sources" / "snmp"
    base = _verified_directory(snmp_root / "1.0.0-build1", BASE_SOURCE_BLOBS, label="immutable SNMP 1.0.0 build 1")
    _verified_directory(snmp_root / "1.0.1-build2", BUILD2_SOURCE_BLOBS, label="immutable SNMP 1.0.1 build 2")
    _verified_directory(snmp_root / "1.0.2-build3", BUILD3_SOURCE_BLOBS, label="immutable SNMP 1.0.2 build 3")
    build4 = _verified_directory(snmp_root / "1.0.3-build4", BUILD4_SOURCE_BLOBS, label="SNMP 1.0.3 build 4 runtime")
    result = dict(base)
    result.update(build4)
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    for old, new in _CORE_IMPORT_REWRITES:
        text = text.replace(old, new)
    if name == "__init__.py":
        marker = "    ValidationResult,\n)\n\nMODULE_ID"
        replacement = "    ValidationResult,\n)\n\nfrom .runtime import SnmpRuntimeExecutor\n\nMODULE_ID"
        if text.count(marker) != 1:
            raise SystemExit("SNMP runtime import marker changed")
        text = text.replace(marker, replacement, 1)
        text = text.replace('MODULE_VERSION = "1.0.0"', f'MODULE_VERSION = "{MODULE_VERSION}"', 1)
        text = text.replace("MODULE_BUILD = 1", f"MODULE_BUILD = {MODULE_BUILD}", 1)
        old = '''_SNMP = SnmpIntegration()\nPLUGIN = IntegrationDefinition(\n    metadata=PluginMetadata(plugin_id="snmp", display_name="SNMP"),\n    connection_kinds=("snmp",),\n    discovery=_SNMP,\n    connection=_SNMP,\n    validation=_SNMP,\n    identity=_SNMP,\n    presentation=_SNMP,\n    runtime=_SNMP,\n)'''
        new = '''_SNMP = SnmpIntegration()\n_SNMP_RUNTIME = SnmpRuntimeExecutor()\nPLUGIN = IntegrationDefinition(\n    metadata=PluginMetadata(plugin_id="snmp", display_name="SNMP"),\n    connection_kinds=("snmp",),\n    discovery=_SNMP,\n    connection=_SNMP,\n    validation=_SNMP,\n    identity=_SNMP,\n    presentation=_SNMP,\n    runtime=_SNMP,\n    runtime_executor=_SNMP_RUNTIME,\n    runtime_adapter_kinds=("snmp",),\n)'''
        if text.count(old) != 1:
            raise SystemExit("SNMP IntegrationDefinition registration changed")
        text = text.replace(old, new, 1)
        bundled = 'entrypoints={"integration": "monitorbox.v2.integrations.snmp:PLUGIN"}'
        if text.count(bundled) != 1:
            raise SystemExit("SNMP bundled entrypoint marker changed")
        text = text.replace(bundled, f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}', 1)
        text = text.replace('requires_core=">=2.2.2 <3.0.0"', 'requires_core=">=2.3.1 <3.0.0"', 1)
    forbidden = ("from ...adapters", "from ...config", "from ...model", "from ...plugin_api", "monitorbox.v2.integrations.snmp:PLUGIN")
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"SNMP managed namespace rewrite incomplete in {name}: {remaining}")
    return text.encode("utf-8")


def _vendor_files() -> dict[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="monitorbox-snmp-vendor-") as directory:
        target = Path(directory)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--no-deps",
                "--only-binary=:all:",
                "--dest",
                str(target),
                "pysnmp==7.1.29",
                "pyasn1==0.6.4",
            ],
            check=True,
        )
        found = {path.name: path for path in target.glob("*.whl")}
        if set(found) != set(VENDOR_WHEELS):
            raise SystemExit(f"unexpected SNMP vendor wheels: {sorted(found)}")
        result: dict[str, bytes] = {}
        for filename, expected_sha in sorted(VENDOR_WHEELS.items()):
            wheel = found[filename]
            payload = wheel.read_bytes()
            actual_sha = hashlib.sha256(payload).hexdigest()
            if actual_sha != expected_sha:
                raise SystemExit(f"vendor wheel hash mismatch for {filename}: expected {expected_sha}, got {actual_sha}")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                for member in sorted(archive.namelist()):
                    if member.endswith("/"):
                        continue
                    if member.startswith(("pysnmp/", "pyasn1/")):
                        if "/__pycache__/" not in member and not member.endswith((".pyc", ".pyo")):
                            result[member] = archive.read(member)
                    elif ".dist-info/licenses/" in member or member.lower().endswith(("/license", "/license.txt", "/copying")):
                        result[f"THIRD_PARTY_LICENSES/{filename}/{Path(member).name}"] = archive.read(member)
        if not any(path.startswith("pysnmp/") for path in result) or not any(path.startswith("pyasn1/") for path in result):
            raise SystemExit("SNMP vendor extraction did not contain both PySNMP and PyASN1")
        return result


def _package_files(root: Path) -> dict[str, bytes]:
    files = {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _source_files(root).items()
    }
    vendor = _vendor_files()
    overlap = set(files) & set(vendor)
    if overlap:
        raise SystemExit(f"SNMP vendor files collide with module files: {sorted(overlap)}")
    files.update(vendor)
    return files


def _zip_directories(files: dict[str, bytes]) -> tuple[str, ...]:
    directories: set[str] = set()
    for path in files:
        parent = Path(path).parent
        while parent != Path("."):
            directories.add(parent.as_posix().rstrip("/") + "/")
            parent = parent.parent
    return tuple(sorted(directories))


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        # PySNMP intentionally uses implicit namespace packages (for example
        # pysnmp/hlapi has no __init__.py). zipimport only discovers those
        # namespaces when their directory entries exist, so preserve the wheel's
        # directory topology explicitly in the signed module artifact.
        for path in _zip_directories(files):
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = (0o40755 << 16) | 0x10
            archive.writestr(info, b"")
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[path], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = _zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"runtime_blob={BUILD4_SOURCE_BLOBS['runtime.py']} transport=pysnmp-7.1.29 entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    expected = set(HISTORICAL_FILENAMES) | {FILENAME}
    unexpected = sorted(path.name for path in output_dir.glob(f"{MODULE_ID}-*.zip") if path.name not in expected)
    if unexpected:
        raise SystemExit(f"unexpected managed SNMP packages already present: {unexpected}")
    return target


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
