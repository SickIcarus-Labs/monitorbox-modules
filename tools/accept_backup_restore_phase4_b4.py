#!/usr/bin/env python3
"""Acceptance for Backup / Restore 1.0.3 build 4 crash-atomic vault publication."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
VAULT_SOURCE = (
    ROOT
    / "sources"
    / "backup-restore"
    / "1.0.3-build4"
    / "monitorbox_backup_restore_b4_vault.py"
)


class FakeApplianceBackupError(ValueError):
    pass


class FakeApplianceBackupManager:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.fail_after_write = False

    @staticmethod
    def _manifest() -> dict[str, object]:
        return {
            "format": "monitorbox-appliance-backup",
            "version": 1,
            "core": {"version": "2.3.1", "build": 598},
            "installation_id": "phase4-test",
            "canonical_revision": "test-revision",
            "installation_fingerprint": "test-fingerprint",
        }

    def create(self, destination: Path) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(self._manifest(), sort_keys=True))
            archive.writestr("config/canonical.json", '{"schema":1}\n')
        if self.fail_after_write:
            raise OSError("injected appliance backup write failure")

    def inspect(self, source: Path):
        try:
            with zipfile.ZipFile(source, "r") as archive:
                bad = archive.testzip()
                if bad is not None:
                    raise FakeApplianceBackupError(f"corrupt member: {bad}")
                manifest = json.loads(archive.read("manifest.json"))
                total = sum(info.file_size for info in archive.infolist())
                count = len(archive.infolist())
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            raise FakeApplianceBackupError(f"invalid appliance backup: {exc}") from exc
        if manifest.get("format") != "monitorbox-appliance-backup":
            raise FakeApplianceBackupError("invalid appliance backup format")
        return SimpleNamespace(manifest=manifest, file_count=count, total_bytes=total)


def _install_core_stub() -> None:
    monitorbox = types.ModuleType("monitorbox")
    v2 = types.ModuleType("monitorbox.v2")
    appliance = types.ModuleType("monitorbox.v2.appliance_backup")
    appliance.ApplianceBackupError = FakeApplianceBackupError
    appliance.ApplianceBackupManager = FakeApplianceBackupManager
    monitorbox.v2 = v2
    v2.appliance_backup = appliance
    sys.modules["monitorbox"] = monitorbox
    sys.modules["monitorbox.v2"] = v2
    sys.modules["monitorbox.v2.appliance_backup"] = appliance


def _load_vault_module():
    _install_core_stub()
    spec = importlib.util.spec_from_file_location("monitorbox_backup_restore_b4_vault", VAULT_SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load build-4 vault source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SimulatedCrash(BaseException):
    pass


def _final_archives(root: Path) -> list[Path]:
    vault = root / "saved-backups"
    return sorted(path for path in vault.glob("*.zip") if path.is_file())


def _final_metadata(root: Path) -> list[Path]:
    vault = root / "saved-backups"
    return sorted(path for path in vault.glob("*.json") if path.is_file())


def _assert_no_partial_final_pairs(root: Path) -> None:
    archives = {path.stem for path in _final_archives(root)}
    metadata = {path.stem for path in _final_metadata(root)}
    assert archives == metadata, f"partial final vault pair: archives={archives}, metadata={metadata}"


def _assert_transactions_empty(root: Path) -> None:
    transactions = root / "saved-backups" / ".transactions"
    assert transactions.is_dir()
    assert list(transactions.iterdir()) == [], f"transactions not reconciled: {list(transactions.iterdir())}"


def _run_crash_matrix(module) -> None:
    rollback_phases = {
        "transaction_created",
        "archive_written",
        "archive_fsynced",
        "metadata_written",
    }
    commit_phases = {
        "ready_written",
        "archive_published",
        "metadata_published",
        "transaction_cleaned",
    }

    for phase in sorted(rollback_phases | commit_phases):
        with tempfile.TemporaryDirectory(prefix=f"monitorbox-b4-{phase}-") as raw:
            root = Path(raw)

            class CrashVault(module.BackupVault):
                def __init__(self, vault_root: Path) -> None:
                    self._crash_phase = phase
                    self._crashed = False
                    super().__init__(vault_root)

                def _checkpoint(self, current: str) -> None:
                    if current == self._crash_phase and not self._crashed:
                        self._crashed = True
                        raise SimulatedCrash(current)

            crashed = CrashVault(root)
            try:
                crashed.create(label=f"Crash at {phase}")
            except SimulatedCrash as exc:
                assert str(exc) == phase
            else:
                raise AssertionError(f"crash checkpoint {phase} was not reached")

            if phase == "archive_published":
                assert len(_final_archives(root)) == 1
                assert len(_final_metadata(root)) == 0
            if phase == "metadata_published":
                assert len(_final_archives(root)) == 1
                assert len(_final_metadata(root)) == 1

            restarted = module.BackupVault(root)
            records = restarted.list()
            _assert_transactions_empty(root)
            _assert_no_partial_final_pairs(root)

            if phase in rollback_phases:
                assert records == (), f"pre-ready crash {phase} became visible"
                assert _final_archives(root) == []
                assert _final_metadata(root) == []
            else:
                assert len(records) == 1, f"post-ready crash {phase} did not recover"
                record = records[0]
                assert restarted.get(record.backup_id, verify=True) == record
                inspection = restarted.inspect(record.backup_id)
                assert inspection["format"] == "monitorbox-appliance-backup"
                assert inspection["core_version"] == "2.3.1"


def _run_ordinary_failure_rollback(module) -> None:
    with tempfile.TemporaryDirectory(prefix="monitorbox-b4-failure-") as raw:
        root = Path(raw)
        vault = module.BackupVault(root)
        vault.manager.fail_after_write = True
        try:
            vault.create(label="must roll back")
        except module.BackupVaultError as exc:
            assert "injected appliance backup write failure" in str(exc)
        else:
            raise AssertionError("ordinary backup failure unexpectedly succeeded")
        assert vault.list() == ()
        _assert_transactions_empty(root)
        _assert_no_partial_final_pairs(root)
        assert _final_archives(root) == []
        assert _final_metadata(root) == []


def _run_corrupt_ready_quarantine(module) -> None:
    with tempfile.TemporaryDirectory(prefix="monitorbox-b4-corrupt-ready-") as raw:
        root = Path(raw)
        phase = "ready_written"

        class CrashVault(module.BackupVault):
            def __init__(self, vault_root: Path) -> None:
                self._done = False
                super().__init__(vault_root)

            def _checkpoint(self, current: str) -> None:
                if current == phase and not self._done:
                    self._done = True
                    raise SimulatedCrash(current)

        try:
            CrashVault(root).create(label="corrupt journal")
        except SimulatedCrash:
            pass
        transaction = next((root / "saved-backups" / ".transactions").iterdir())
        ready_path = transaction / "ready.json"
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        ready["metadata_sha256"] = "0" * 64
        ready_path.write_text(json.dumps(ready), encoding="utf-8")

        restarted = module.BackupVault(root)
        assert restarted.list() == ()
        _assert_transactions_empty(root)
        _assert_no_partial_final_pairs(root)
        quarantine = root / "saved-backups" / ".quarantine"
        assert list(quarantine.iterdir()), "corrupt prepared transaction was not quarantined"


def _run_legacy_orphan_quarantine(module) -> None:
    with tempfile.TemporaryDirectory(prefix="monitorbox-b4-orphan-") as raw:
        root = Path(raw)
        vault_path = root / "saved-backups"
        vault_path.mkdir(parents=True)
        backup_id = "20260909T010203Z-deadbeef"
        orphan = vault_path / f"{backup_id}.zip"
        FakeApplianceBackupManager(root).create(orphan)
        restarted = module.BackupVault(root)
        assert restarted.list() == ()
        assert not orphan.exists()
        assert any(
            path.name.endswith(f"-{backup_id}.zip")
            for path in (vault_path / ".quarantine").iterdir()
        ), "orphan final archive was not quarantined"


def _run_tamper_and_copy(module) -> None:
    with tempfile.TemporaryDirectory(prefix="monitorbox-b4-tamper-") as raw:
        root = Path(raw)
        vault = module.BackupVault(root)
        first = vault.create(label="Original")
        copied = vault.copy(first.backup_id, label="Copy")
        assert copied.kind == "copy"
        assert len(vault.list()) == 2
        assert vault.get(first.backup_id, verify=True) == first
        assert vault.get(copied.backup_id, verify=True) == copied
        _assert_no_partial_final_pairs(root)

        archive = vault.archive_path(first.backup_id, verify=True)
        with archive.open("ab") as handle:
            handle.write(b"tamper")
        try:
            vault.get(first.backup_id, verify=True)
        except module.BackupVaultError as exc:
            assert "integrity verification" in str(exc)
        else:
            raise AssertionError("tampered committed backup passed integrity verification")


def main() -> None:
    module = _load_vault_module()
    _run_crash_matrix(module)
    _run_ordinary_failure_rollback(module)
    _run_corrupt_ready_quarantine(module)
    _run_legacy_orphan_quarantine(module)
    _run_tamper_and_copy(module)
    print(
        "Backup / Restore Phase-4 build-4 acceptance: PASS "
        "(crash matrix + deterministic recovery/rollback + quarantine + tamper + copy)"
    )


if __name__ == "__main__":
    main()
