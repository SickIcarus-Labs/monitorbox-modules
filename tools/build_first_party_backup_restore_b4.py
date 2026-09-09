#!/usr/bin/env python3
"""Build Backup / Restore 1.0.3 build 4 from the accepted build-3 source."""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
PREDECESSOR_DIR = ROOT / "sources" / "backup-restore" / "1.0.2-build3"
DELTA_DIR = ROOT / "sources" / "backup-restore" / "1.0.3-build4"
PREDECESSOR_PACKAGE = ROOT / "packages" / f"{MODULE_ID}-1.0.2-build3.zip"
PREDECESSOR_PACKAGE_SHA256 = "d7ac2d463a09d6945e102251ab14bd702e0a65c990ee5df9e0cf8a4b90aa1100"
TARGET_FILENAME = f"{MODULE_ID}-1.0.3-build4.zip"
TARGET_ENTRYPOINT = "monitorbox_backup_restore_b4:install"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

PREDECESSOR_BLOBS = {
    "monitorbox_backup_restore_b3.py": "5aae29328d46ab1f2ff4f9212508a48e5b351359",
    "monitorbox_backup_restore_b3_application.py": "9acda5c769520bc9819625fa659740ef81c5e094",
    "monitorbox_backup_restore_b3_destinations.py": "c015eaac8864eac57c986729aa00f1a88a59336c",
    "monitorbox_backup_restore_b3_management.py": "7c4866d890bf184a9342f6adbfef4055e3627da1",
    "monitorbox_backup_restore_b3_policy.py": "8ee5c90eec5978b87979b2f1f5020cff7c914805",
    "monitorbox_backup_restore_b3_scheduler.py": "02f537e953ebe762453dace664d3e2eee4dab8fe",
    "monitorbox_backup_restore_b3_vault.py": "46cdcfee909681d0904d8198162eb164286a9a1b",
}
DELTA_BLOBS = {
    "monitorbox_backup_restore_b4_vault.py": "b69cc21202a1551a05618288d80196bd9cfc8858",
}


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _verify_source_shape(root: Path, expected: dict[str, str], *, label: str) -> dict[str, bytes]:
    actual = {path.name for path in root.iterdir() if path.is_file()}
    if actual != set(expected):
        raise SystemExit(
            f"{label} source shape changed: expected={sorted(expected)}, actual={sorted(actual)}"
        )
    files: dict[str, bytes] = {}
    for name, expected_blob in sorted(expected.items()):
        payload = (root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"{label} source drift for {name}: expected Git blob {expected_blob}, got {actual_blob}"
            )
        files[name] = payload
    return files


def _verify_predecessor_package() -> None:
    if not PREDECESSOR_PACKAGE.is_file():
        raise SystemExit(f"accepted predecessor package is missing: {PREDECESSOR_PACKAGE}")
    actual = hashlib.sha256(PREDECESSOR_PACKAGE.read_bytes()).hexdigest()
    if actual != PREDECESSOR_PACKAGE_SHA256:
        raise SystemExit(
            "accepted Backup / Restore 1.0.2 build 3 package drift: "
            f"expected {PREDECESSOR_PACKAGE_SHA256}, got {actual}"
        )


def _rewrite_successor(name: str, payload: bytes) -> tuple[str, bytes]:
    if name.endswith("_vault.py"):
        raise AssertionError("build-3 vault must be replaced by the build-4 delta")
    text = payload.decode("utf-8")
    successor_name = name.replace("monitorbox_backup_restore_b3", "monitorbox_backup_restore_b4")
    text = text.replace("monitorbox_backup_restore_b3", "monitorbox_backup_restore_b4")
    if name == "monitorbox_backup_restore_b3.py":
        replacements = {
            'Managed Backup / Restore 1.0.2 build 3.': 'Managed Backup / Restore 1.0.3 build 4.',
            'Build 3 keeps backup policy': 'Build 4 keeps backup policy',
            'MODULE_VERSION = "1.0.2"': 'MODULE_VERSION = "1.0.3"',
            'MODULE_BUILD = 3': 'MODULE_BUILD = 4',
        }
        for before, after in replacements.items():
            if text.count(before) != 1:
                raise SystemExit(f"build-3 entrypoint drift: expected exactly one {before!r}")
            text = text.replace(before, after)
    return successor_name, text.encode("utf-8")


def _compose_sources() -> dict[str, bytes]:
    predecessor = _verify_source_shape(
        PREDECESSOR_DIR,
        PREDECESSOR_BLOBS,
        label="Backup / Restore 1.0.2 build 3",
    )
    delta = _verify_source_shape(
        DELTA_DIR,
        DELTA_BLOBS,
        label="Backup / Restore 1.0.3 build 4 delta",
    )
    files: dict[str, bytes] = {}
    for name, payload in predecessor.items():
        if name.endswith("_vault.py"):
            continue
        successor_name, successor_payload = _rewrite_successor(name, payload)
        files[successor_name] = successor_payload
    files.update(delta)

    expected = {
        name.replace("monitorbox_backup_restore_b3", "monitorbox_backup_restore_b4")
        for name in PREDECESSOR_BLOBS
    }
    if set(files) != expected:
        raise SystemExit(
            f"Backup / Restore build-4 composition changed: expected={sorted(expected)}, actual={sorted(files)}"
        )
    for name, payload in files.items():
        compile(payload.decode("utf-8"), name, "exec")
    return files


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


def build(root: Path = ROOT, output_dir: Path | None = None) -> Path:
    if root != ROOT:
        raise SystemExit("Backup / Restore build-4 builder must run from its repository root")
    _verify_predecessor_package()
    payload = _zip_bytes(_compose_sources())
    output_dir = output_dir or root / "packages"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / TARGET_FILENAME
    target.write_bytes(payload)
    print(
        f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
        f"entrypoint={TARGET_ENTRYPOINT} predecessor={PREDECESSOR_PACKAGE.name}"
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "packages")
    args = parser.parse_args()
    build(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
