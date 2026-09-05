#!/usr/bin/env python3
"""Extend first-party repository acceptance through Backup / Restore 1.0.1 build 2."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import accept_repository as stable
import accept_repository_configuration_bootstrap as previous

MODULE_ID = "com.sickicarus.monitorbox.backup-restore"
RELEASE_B1 = (MODULE_ID, "1.0.0", 1)
RELEASE_B2 = (MODULE_ID, "1.0.1", 2)
CURRENT_RELEASES = set(previous.CURRENT_RELEASES) | {RELEASE_B1, RELEASE_B2}
B1_SOURCE = "monitorbox_backup_restore_b1.py"
B2_SOURCES = {
    "monitorbox_backup_restore_b2.py",
    "monitorbox_backup_restore_b2_application.py",
    "monitorbox_backup_restore_b2_destinations.py",
    "monitorbox_backup_restore_b2_management.py",
    "monitorbox_backup_restore_b2_policy.py",
    "monitorbox_backup_restore_b2_scheduler.py",
    "monitorbox_backup_restore_b2_vault.py",
}


def _release(source: dict, identity: tuple[str, str, int]) -> dict:
    item = next(
        (
            candidate
            for candidate in source.get("modules", [])
            if stable._release_identity(candidate) == identity
        ),
        None,
    )
    if item is None:
        raise AssertionError(f"Backup / Restore release {identity[1:]} is missing")
    return item


def _manifest(version: str, build: int, entrypoint: str) -> dict:
    return {
        "module_id": MODULE_ID,
        "display_name": "Backup / Restore",
        "version": version,
        "build": build,
        "schema": 1,
        "state_schema": 1,
        "module_type": "recovery",
        "entrypoints": {"recovery": entrypoint},
        "requires_core": ">=2.3.0 <3.0.0",
        "requires_runtime_api": ">=1 <2",
        "dependencies": [],
        "publisher_id": "com.sickicarus",
        "permissions": [
            "recovery.snapshot",
            "recovery.inspect",
            "recovery.schedule",
            "recovery.destination",
            "saved-backup-vault",
        ],
        "lifecycle_policy": "optional",
    }


def _validate_build1(root: Path, source: dict) -> None:
    release = _release(source, RELEASE_B1)
    expected_manifest = _manifest("1.0.0", 1, "monitorbox_backup_restore_b1:install")
    if release.get("manifest") != expected_manifest:
        raise AssertionError("published Backup / Restore 1.0.0 build 1 manifest changed")

    package_path = root / "packages" / release["package"]
    if package_path.name != "com.sickicarus.monitorbox.backup-restore-1.0.0-build1.zip":
        raise AssertionError("Backup / Restore build 1 package was renamed")
    if not package_path.is_file():
        raise AssertionError("Backup / Restore build 1 package is missing")
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != {B1_SOURCE}:
            raise AssertionError(f"Backup / Restore build 1 package shape changed: {sorted(names)}")
        text = archive.read(B1_SOURCE).decode("utf-8")
        compile(text, B1_SOURCE, "exec")
    required = (
        "from monitorbox.v2.modules.backup_restore import (",
        '"com.sickicarus.monitorbox.backup-restore"',
        '"1.0.0"',
        "FACTORY_BUILD",
        "factory_install(app, platform=platform)",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise AssertionError(f"immutable Backup / Restore build 1 seed markers changed: {missing}")


def _validate_build2(root: Path, source: dict) -> None:
    release = _release(source, RELEASE_B2)
    expected_manifest = _manifest("1.0.1", 2, "monitorbox_backup_restore_b2:install")
    if release.get("manifest") != expected_manifest:
        raise AssertionError(f"Backup / Restore build 2 manifest mismatch: {release.get('manifest')!r}")

    package_path = root / "packages" / release["package"]
    expected_filename = "com.sickicarus.monitorbox.backup-restore-1.0.1-build2.zip"
    if package_path.name != expected_filename or not package_path.is_file():
        raise AssertionError("Backup / Restore build 2 package is missing or misnamed")

    texts: dict[str, str] = {}
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        if names != B2_SOURCES:
            raise AssertionError(
                "Backup / Restore build 2 must carry its complete managed runtime: "
                f"expected={sorted(B2_SOURCES)}, actual={sorted(names)}"
            )
        if any(name.startswith("monitorbox/") for name in names):
            raise AssertionError("managed Backup / Restore may not shadow Core's monitorbox namespace")
        for name in sorted(names):
            text = archive.read(name).decode("utf-8")
            compile(text, name, "exec")
            texts[name] = text

    combined = "\n".join(texts.values())
    entry = texts["monitorbox_backup_restore_b2.py"]
    application = texts["monitorbox_backup_restore_b2_application.py"]
    vault = texts["monitorbox_backup_restore_b2_vault.py"]

    required = (
        (entry, 'MODULE_VERSION = "1.0.1"'),
        (entry, "MODULE_BUILD = 2"),
        (entry, 'ADMIN_API_PREFIX = "/api/v2/config/backup-restore"'),
        (entry, "BackupRestoreApplication"),
        (entry, "BackupRestoreManagement"),
        (vault, "from monitorbox.v2.appliance_backup import ApplianceBackupError, ApplianceBackupManager"),
        (vault, 'ARCHIVE_SUFFIX = ".zip"'),
        (application, 'accept=".zip,application/zip"'),
        (application, 'response.content_type = "application/zip"'),
        (application, "Admin authenticated"),
    )
    missing = [marker for text, marker in required if marker not in text]
    if missing:
        raise AssertionError(f"Backup / Restore build 2 contract markers missing: {missing}")

    forbidden = (
        "monitorbox.v2.modules.backup_restore",
        "factory_install",
        ".mbbackup",
        '"/api/v2/backup-restore',
        "subprocess.",
        "docker",
        "ssh",
    )
    present = [marker for marker in forbidden if marker in combined]
    if present:
        raise AssertionError(
            "Backup / Restore build 2 violates independent managed-module boundary: "
            f"{present}"
        )


def _package_shape(root: Path, source: dict) -> None:
    identities = {stable._release_identity(item) for item in source.get("modules", [])}
    if identities != CURRENT_RELEASES or len(source.get("modules", [])) != len(CURRENT_RELEASES):
        raise AssertionError(
            f"expected current repository releases {sorted(CURRENT_RELEASES)}, got {sorted(identities)}"
        )

    _validate_build1(root, source)
    _validate_build2(root, source)

    prior = copy.deepcopy(source)
    prior["modules"] = [
        item
        for item in prior.get("modules", [])
        if stable._release_identity(item) not in {RELEASE_B1, RELEASE_B2}
    ]
    previous._package_shape(root, prior)


def main() -> None:
    stable.EXPECTED_RELEASES = CURRENT_RELEASES
    stable._package_shape = _package_shape
    stable.main()


if __name__ == "__main__":
    main()
