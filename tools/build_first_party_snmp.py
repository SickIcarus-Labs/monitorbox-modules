#!/usr/bin/env python3
"""Build the current independently managed SNMP integration for MonitorBox 2.3 Core.

SNMP 1.0.0 build 1 and 1.0.1 build 2 remain immutable release history.
1.0.2 build 3 keeps provider-loss runtime truth and adds conservative QuTS hero
storage-pool semantics: documented scrubbing is health-neutral, while unknown
vendor pool states remain UNKNOWN rather than fabricated hard failures.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.snmp"
MODULE_VERSION = "1.0.2"
MODULE_BUILD = 3
IMPORT_PACKAGE = "monitorbox_snmp_b3"
FILENAME = f"{MODULE_ID}-{MODULE_VERSION}-build{MODULE_BUILD}.zip"
HISTORICAL_FILENAMES = frozenset(
    {
        f"{MODULE_ID}-1.0.0-build1.zip",
        f"{MODULE_ID}-1.0.1-build2.zip",
    }
)

BASE_SOURCE_BLOBS = {
    "__init__.py": "df242a51b7845c4e852bb15419360f8ac0abdf7e",
}

BUILD2_SOURCE_BLOBS = {
    "runtime.py": "8467c756dcf502b48a40a7bac81f6113a48b88b6",
}

BUILD3_SOURCE_BLOBS = {
    "runtime.py": "330c01702ec461d2aee10d3397910455823b592a",
}

_CORE_IMPORT_REWRITES = (
    ("from ...adapters", "from monitorbox.v2.adapters"),
    ("from ...config", "from monitorbox.v2.config"),
    ("from ...model", "from monitorbox.v2.model"),
    ("from ...plugin_api", "from monitorbox.v2.plugin_api"),
)


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _verified_directory(
    source_root: Path,
    expected_blobs: dict[str, str],
    *,
    label: str,
) -> dict[str, bytes]:
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    expected_names = set(expected_blobs)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise SystemExit(f"{label} source shape changed: missing={missing}, extra={extra}")

    result: dict[str, bytes] = {}
    for name, expected_blob in expected_blobs.items():
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"{label} source drift for {name}: expected Git blob {expected_blob}, got {actual_blob}"
            )
        result[name] = payload
    return result


def _source_files(root: Path) -> dict[str, bytes]:
    snmp_root = root / "sources" / "snmp"
    base = _verified_directory(
        snmp_root / "1.0.0-build1",
        BASE_SOURCE_BLOBS,
        label="immutable SNMP 1.0.0 build 1",
    )
    # Build 2 is immutable history even though build 3 supersedes its runtime.
    _verified_directory(
        snmp_root / "1.0.1-build2",
        BUILD2_SOURCE_BLOBS,
        label="immutable SNMP 1.0.1 build 2",
    )
    build3 = _verified_directory(
        snmp_root / "1.0.2-build3",
        BUILD3_SOURCE_BLOBS,
        label="SNMP 1.0.2 build 3 QuTS hero maintenance delta",
    )
    result = dict(base)
    result.update(build3)
    if set(result) != {"__init__.py", "runtime.py"}:
        raise SystemExit("SNMP 1.0.2 build 3 composed source shape changed")
    return result


def _rewrite_source(name: str, payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    for old, new in _CORE_IMPORT_REWRITES:
        text = text.replace(old, new)

    if name == "__init__.py":
        import_marker = "    ValidationResult,\n)\n\nMODULE_ID"
        import_replacement = (
            "    ValidationResult,\n)\n\n"
            "from .runtime import SnmpRuntimeExecutor\n\n"
            "MODULE_ID"
        )
        if text.count(import_marker) != 1:
            raise SystemExit("SNMP package root runtime import marker changed")
        text = text.replace(import_marker, import_replacement, 1)

        if text.count('MODULE_VERSION = "1.0.0"') != 1 or text.count("MODULE_BUILD = 1") != 1:
            raise SystemExit("SNMP build 1 release identity markers changed")
        text = text.replace('MODULE_VERSION = "1.0.0"', f'MODULE_VERSION = "{MODULE_VERSION}"', 1)
        text = text.replace("MODULE_BUILD = 1", f"MODULE_BUILD = {MODULE_BUILD}", 1)

        old_registration = '''_SNMP = SnmpIntegration()\nPLUGIN = IntegrationDefinition(\n    metadata=PluginMetadata(plugin_id="snmp", display_name="SNMP"),\n    connection_kinds=("snmp",),\n    discovery=_SNMP,\n    connection=_SNMP,\n    validation=_SNMP,\n    identity=_SNMP,\n    presentation=_SNMP,\n    runtime=_SNMP,\n)'''
        new_registration = '''_SNMP = SnmpIntegration()\n_SNMP_RUNTIME = SnmpRuntimeExecutor()\nPLUGIN = IntegrationDefinition(\n    metadata=PluginMetadata(plugin_id="snmp", display_name="SNMP"),\n    connection_kinds=("snmp",),\n    discovery=_SNMP,\n    connection=_SNMP,\n    validation=_SNMP,\n    identity=_SNMP,\n    presentation=_SNMP,\n    runtime=_SNMP,\n    runtime_executor=_SNMP_RUNTIME,\n    runtime_adapter_kinds=("snmp",),\n)'''
        if text.count(old_registration) != 1:
            raise SystemExit("SNMP package root IntegrationDefinition registration changed")
        text = text.replace(old_registration, new_registration, 1)

        bundled_entrypoint = 'entrypoints={"integration": "monitorbox.v2.integrations.snmp:PLUGIN"}'
        managed_entrypoint = f'entrypoints={{"integration": "{IMPORT_PACKAGE}:PLUGIN"}}'
        if text.count(bundled_entrypoint) != 1:
            raise SystemExit("SNMP package root bundled entrypoint contract changed")
        text = text.replace(bundled_entrypoint, managed_entrypoint, 1)

        old_core_requirement = 'requires_core=">=2.2.2 <3.0.0"'
        new_core_requirement = 'requires_core=">=2.3.0 <3.0.0"'
        if text.count(old_core_requirement) != 1:
            raise SystemExit("SNMP package root Core requirement contract changed")
        text = text.replace(old_core_requirement, new_core_requirement, 1)

    forbidden = (
        "from ...adapters",
        "from ...config",
        "from ...model",
        "from ...plugin_api",
        "monitorbox.v2.integrations.snmp:PLUGIN",
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit(f"SNMP managed namespace rewrite incomplete in {name}: {remaining}")
    return text.encode("utf-8")


def _package_files(root: Path) -> dict[str, bytes]:
    return {
        f"{IMPORT_PACKAGE}/{name}": _rewrite_source(name, payload)
        for name, payload in _source_files(root).items()
    }


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                files[path],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return output.getvalue()


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = _zip_bytes(_package_files(root))
    target = output_dir / FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"base_blob={BASE_SOURCE_BLOBS['__init__.py']} "
        f"runtime_blob={BUILD3_SOURCE_BLOBS['runtime.py']} "
        f"entrypoint={IMPORT_PACKAGE}:PLUGIN"
    )
    expected = set(HISTORICAL_FILENAMES) | {FILENAME}
    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in expected
    )
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
