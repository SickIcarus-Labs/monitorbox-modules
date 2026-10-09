#!/usr/bin/env python3
"""Deterministically assemble UNSIGNED MonitorBox Backup/Restore v3 2.0.0 build 7.

No signing, feed publication, release promotion, or write to packages/.
All packaged Python is taken ONLY from reviewed versioned source below;
mutable tools/ prototypes and prior v2 module packages are never executed.
The restore action is intentionally *absent* pending campaign #691.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources" / "backup-restore" / "2.0.0-build7"
PREFIX = "monitorbox_backup_restore_b7"
MODULE = "com.sickicarus.monitorbox.backup-restore"
TARGET = MODULE + "-2.0.0-build7.zip"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXPECTED_SUFFIXES = (
    "", "_application", "_native_archive", "_native_jobs",
    "_native_vault", "_native_workflow", "_native_operator",
    "_native_schedule", "_vault", "_policy", "_destinations",
)
EXPECTED = frozenset(PREFIX + suffix + ".py" for suffix in EXPECTED_SUFFIXES)


def build(output_dir: Path) -> Path:
    found = {path.name for path in SOURCE.glob("*.py")}
    if found != EXPECTED:
        raise ValueError(
            "unsigned Backup/Restore build 7 source closure changed: "
            f"missing={sorted(EXPECTED-found)} unexpected={sorted(found-EXPECTED)}"
        )
    members: dict[str, bytes] = {}
    for name in sorted(EXPECTED):
        payload = (SOURCE / name).read_bytes()
        decoded = payload.decode("utf-8")
        compile(decoded, name, "exec")
        members[name] = payload
    entry = members[PREFIX + ".py"].decode("utf-8")
    application = members[PREFIX + "_application.py"].decode("utf-8")
    assert 'MODULE_VERSION = "2.0.0"' in entry
    assert "MODULE_BUILD = 7" in entry
    assert 'REQUIRES_CORE = ">=3.0.0 <4.0.0"' in entry
    # Native restore must NEVER fall through to the old v2 appliance handoff.
    for banned in (
        "ApplianceRestoreHandoff",
        "appliance_restore_handoff",
        "restore/confirm",
        "restore/file/preview",
        "/restore/preview",
    ):
        if banned in entry or banned in application:
            raise ValueError("build 7 unexpectedly exposes legacy restore: " + banned)
    # Production module imports may not reach back into prototype source.
    for name, payload in members.items():
        if name == PREFIX + "_vault.py":
            # Archived vault's historical writer remains only as an internal
            # inherited helper; native adapter disables its public create().
            continue
        for invalid in (
            "from backup_restore_native_",
            "import backup_restore_native_",
            "monitorbox_backup_restore_b2_",
            "monitorbox_backup_restore_b4_",
        ):
            if invalid in payload.decode("utf-8"):
                raise ValueError(f"unpackaged module import in {name}: {invalid}")

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipout:
        for name, payload in sorted(members.items()):
            info=zipfile.ZipInfo(name,date_time=FIXED_ZIP_TIME)
            info.compress_type=zipfile.ZIP_DEFLATED
            info.create_system=3
            info.external_attr=0o100644 << 16
            zipout.writestr(info,payload,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    output_dir.mkdir(parents=True,exist_ok=True)
    dest=output_dir/TARGET
    dest.write_bytes(output.getvalue())
    print(f"unsigned B7 candidate: {dest} sha256={hashlib.sha256(output.getvalue()).hexdigest()} "
          "entrypoint=monitorbox_backup_restore_b7:install -- DO NOT SIGN OR PUBLISH")
    return dest


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",type=Path,default=ROOT / "packages")
    build(parser.parse_args().output_dir)
