#!/usr/bin/env python3
"""Test-only immutable Backup/Restore 1.0.5 build6 over exact accepted build5.

This draft candidate is NOT a signed/channel release. The signed b5 ZIP is read
as immutable predecessor and verified against its exact committed Git blob.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = "com.sickicarus.monitorbox.backup-restore"
SOURCE_PREFIX = "monitorbox_backup_restore_b5"
TARGET_PREFIX = "monitorbox_backup_restore_b6"
PREDECESSOR = ROOT / "packages" / f"{MODULE}-1.0.4-build5.zip"
PREDECESSOR_GIT_BLOB = "95cc7287abaa3535e50015bbc74ee93f326114bd"
DELTA = ROOT / "sources" / "backup-restore" / "1.0.5-build6" / f"{TARGET_PREFIX}_application.py"
TARGET_FILENAME = f"{MODULE}-1.0.5-build6.zip"
TARGET_ENTRYPOINT = f"{TARGET_PREFIX}:install"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXPECTED = {
    f"{SOURCE_PREFIX}{suffix}.py" for suffix in
    ("", "_application", "_destinations", "_management", "_policy",
     "_scheduler", "_vault")
}


def _predecessor_members() -> dict[str, bytes]:
    raw = PREDECESSOR.read_bytes()
    git_hash = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
    if git_hash != PREDECESSOR_GIT_BLOB:
        raise SystemExit(
            f"immutable b5 predecessor digest mismatch: {git_hash} != {PREDECESSOR_GIT_BLOB}"
        )
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        if set(archive.namelist()) != EXPECTED:
            raise SystemExit("signed b5 predecessor package shape changed")
        return {name: archive.read(name) for name in sorted(EXPECTED)}


def _rewrite(name: str, payload: bytes) -> tuple[str, bytes]:
    target = name.replace(SOURCE_PREFIX, TARGET_PREFIX)
    if name.endswith("_application.py"):
        content = DELTA.read_bytes()
        compile(content.decode("utf-8"), target, "exec")
        return target, content
    text = payload.decode("utf-8").replace(SOURCE_PREFIX, TARGET_PREFIX)
    if name == SOURCE_PREFIX + ".py":
        identities = {
            'MODULE_VERSION = "1.0.4"': 'MODULE_VERSION = "1.0.5"',
            "MODULE_BUILD = 5": "MODULE_BUILD = 6",
            "Managed Backup / Restore 1.0.4 build 5.": "Managed Backup / Restore 1.0.5 build 6.",
        }
        for before, after in identities.items():
            if text.count(before) != 1:
                raise SystemExit(f"unexpected b5 entrypoint identity: {before!r}")
            text = text.replace(before, after)
        old = "    management = BackupRestoreManagement(platform)"
        if text.count(old) != 1:
            raise SystemExit("signed b5 entrypoint installation seam changed")
        guard = (
            "    # Exact snapshot-notice capability, not merely Core semver.\n"
            "    from monitorbox.v2.module_preferences import (\n"
            "        MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION,\n"
            "    )\n"
            "    if MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION != 2:\n"
            "        raise RuntimeError('Backup/Restore b6 requires Core snapshot participant v2')\n"
        )
        text = text.replace(old, guard + old, 1)
    compile(text, target, "exec")
    return target, text.encode("utf-8")


def build(output_dir: Path) -> Path:
    files = dict(_rewrite(name, data) for name, data in _predecessor_members().items())
    expected = {name.replace(SOURCE_PREFIX, TARGET_PREFIX) for name in EXPECTED}
    if set(files) != expected:
        raise SystemExit("Backup/Restore b6 output package shape changed")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[name], compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / TARGET_FILENAME
    target.write_bytes(output.getvalue())
    print(
        f"b6 candidate {target}: sha256={hashlib.sha256(output.getvalue()).hexdigest()} "
        f"entrypoint={TARGET_ENTRYPOINT} unsigned/test-only"
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "packages")
    build(parser.parse_args().output_dir)
