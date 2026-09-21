#!/usr/bin/env python3
"""Build Backup / Restore 1.0.4 build 5 from immutable build 4 plus #354 UI delta."""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
PREDECESSOR = ROOT / "packages" / f"{MODULE_ID}-1.0.3-build4.zip"
PREDECESSOR_SHA256 = "082aebf0a138f47ec318d39bf5f787eb1ecde150ce63b413fc36b4b22ec3fac7"
DELTA = (
    ROOT
    / "sources"
    / "backup-restore"
    / "1.0.4-build5"
    / "monitorbox_backup_restore_b5_application.py"
)
TARGET_FILENAME = f"{MODULE_ID}-1.0.4-build5.zip"
TARGET_ENTRYPOINT = "monitorbox_backup_restore_b5:install"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

EXPECTED_PREDECESSOR = {
    "monitorbox_backup_restore_b4.py",
    "monitorbox_backup_restore_b4_application.py",
    "monitorbox_backup_restore_b4_destinations.py",
    "monitorbox_backup_restore_b4_management.py",
    "monitorbox_backup_restore_b4_policy.py",
    "monitorbox_backup_restore_b4_scheduler.py",
    "monitorbox_backup_restore_b4_vault.py",
}


def _predecessor_members() -> dict[str, bytes]:
    if not PREDECESSOR.is_file():
        raise SystemExit(f"accepted predecessor package is missing: {PREDECESSOR}")
    actual_sha = hashlib.sha256(PREDECESSOR.read_bytes()).hexdigest()
    if actual_sha != PREDECESSOR_SHA256:
        raise SystemExit(
            "accepted Backup / Restore build 4 package drift: "
            f"expected {PREDECESSOR_SHA256}, got {actual_sha}"
        )
    with zipfile.ZipFile(PREDECESSOR, "r") as archive:
        names = set(archive.namelist())
        if names != EXPECTED_PREDECESSOR:
            raise SystemExit(
                "accepted build 4 package shape changed: "
                f"expected={sorted(EXPECTED_PREDECESSOR)}, actual={sorted(names)}"
            )
        return {name: archive.read(name) for name in sorted(names)}


def _rewrite(name: str, payload: bytes) -> tuple[str, bytes]:
    target_name = name.replace("monitorbox_backup_restore_b4", "monitorbox_backup_restore_b5")
    if name.endswith("_application.py"):
        delta = DELTA.read_bytes()
        compile(delta.decode("utf-8"), target_name, "exec")
        return target_name, delta

    text = payload.decode("utf-8").replace(
        "monitorbox_backup_restore_b4",
        "monitorbox_backup_restore_b5",
    )
    if name == "monitorbox_backup_restore_b4.py":
        replacements = {
            "Managed Backup / Restore 1.0.3 build 4.": "Managed Backup / Restore 1.0.4 build 5.",
            "Build 4 keeps backup policy": "Build 5 keeps backup policy",
            'MODULE_VERSION = "1.0.3"': 'MODULE_VERSION = "1.0.4"',
            "MODULE_BUILD = 4": "MODULE_BUILD = 5",
        }
        for before, after in replacements.items():
            if text.count(before) != 1:
                raise SystemExit(f"build 4 entrypoint drift: expected exactly one {before!r}")
            text = text.replace(before, after)
    compile(text, target_name, "exec")
    return target_name, text.encode("utf-8")


def build(output_dir: Path) -> Path:
    if not DELTA.is_file():
        raise SystemExit(f"build 5 application delta is missing: {DELTA}")
    files = dict(_rewrite(name, payload) for name, payload in _predecessor_members().items())
    expected = {
        name.replace("monitorbox_backup_restore_b4", "monitorbox_backup_restore_b5")
        for name in EXPECTED_PREDECESSOR
    }
    if set(files) != expected:
        raise SystemExit(
            f"build 5 package shape changed: expected={sorted(expected)}, actual={sorted(files)}"
        )

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                files[name],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / TARGET_FILENAME
    target.write_bytes(output.getvalue())
    print(
        f"built {target}: sha256={hashlib.sha256(target.read_bytes()).hexdigest()} "
        f"entrypoint={TARGET_ENTRYPOINT} predecessor={PREDECESSOR.name}"
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "packages")
    args = parser.parse_args()
    build(args.output_dir)


if __name__ == "__main__":
    main()
