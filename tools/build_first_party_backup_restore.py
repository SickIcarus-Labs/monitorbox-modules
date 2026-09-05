#!/usr/bin/env python3
"""Build immutable Backup / Restore first-party releases for MonitorBox 2.3 Core."""

from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MODULE_ID = "com.sickicarus.monitorbox.backup-restore"


@dataclass(frozen=True)
class Release:
    version: str
    build: int
    source_dir: str
    entrypoint: str
    source_blobs: dict[str, str]

    @property
    def filename(self) -> str:
        return f"{MODULE_ID}-{self.version}-build{self.build}.zip"


RELEASES = (
    Release(
        version="1.0.0",
        build=1,
        source_dir="1.0.0-build1",
        entrypoint="monitorbox_backup_restore_b1:install",
        source_blobs={
            "monitorbox_backup_restore_b1.py": "aba0a115c580bb3c74de651c96762b5577a6c698",
        },
    ),
    Release(
        version="1.0.1",
        build=2,
        source_dir="1.0.1-build2",
        entrypoint="monitorbox_backup_restore_b2:install",
        source_blobs={
            "monitorbox_backup_restore_b2.py": "d1ef8679225f80335b11b152364d1d83b2d5d6de",
            "monitorbox_backup_restore_b2_application.py": "5e5028c7cf6d49ce070dc9fd439850b7c09adf18",
            "monitorbox_backup_restore_b2_destinations.py": "c015eaac8864eac57c986729aa00f1a88a59336c",
            "monitorbox_backup_restore_b2_management.py": "b701b19cdfaf09bcc9b6e5d3c3c348f2280a47e6",
            "monitorbox_backup_restore_b2_policy.py": "8ee5c90eec5978b87979b2f1f5020cff7c914805",
            "monitorbox_backup_restore_b2_scheduler.py": "67a91f00d895002b00f26be750c39dba2f44a2da",
            "monitorbox_backup_restore_b2_vault.py": "28293e5c9d62d99a8f7e3f62c69240cadf62b962",
        },
    ),
)


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def _sources(root: Path, release: Release) -> dict[str, bytes]:
    source_root = root / "sources" / "backup-restore" / release.source_dir
    actual_names = {path.name for path in source_root.iterdir() if path.is_file()}
    expected_names = set(release.source_blobs)
    if actual_names != expected_names:
        raise SystemExit(
            f"Backup / Restore {release.version} build {release.build} source shape changed: "
            f"expected={sorted(expected_names)}, actual={sorted(actual_names)}"
        )

    files: dict[str, bytes] = {}
    for name, expected_blob in sorted(release.source_blobs.items()):
        payload = (source_root / name).read_bytes()
        actual_blob = _git_blob_sha(payload)
        if actual_blob != expected_blob:
            raise SystemExit(
                f"Backup / Restore {release.version} build {release.build} source drift "
                f"for {name}: expected Git blob {expected_blob}, got {actual_blob}"
            )
        files[name] = payload
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


def build(root: Path, output_dir: Path) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_filenames = {release.filename for release in RELEASES}
    built: list[Path] = []

    for release in RELEASES:
        payload = _zip_bytes(_sources(root, release))
        target = output_dir / release.filename
        target.write_bytes(payload)
        print(
            f"built {target}: sha256={hashlib.sha256(payload).hexdigest()} "
            f"entrypoint={release.entrypoint}"
        )
        built.append(target)

    unexpected = sorted(
        path.name
        for path in output_dir.glob(f"{MODULE_ID}-*.zip")
        if path.name not in expected_filenames
    )
    if unexpected:
        raise SystemExit(
            "unexpected managed Backup / Restore packages already present: "
            f"{unexpected}"
        )
    return tuple(built)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=root / "packages")
    args = parser.parse_args()
    build(root, args.output_dir)


if __name__ == "__main__":
    main()
