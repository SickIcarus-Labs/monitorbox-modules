"""Development-only, synthetic signed native ZIP and crash-vault acceptance.

The deterministic HMAC *test fixture* models an independent local trust root.
It is not production package verification; only native Supervisor can provide
the real signed-closure validation service in the shipping application.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import stat
import sys
import tempfile
import types
from types import SimpleNamespace
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "sources/backup-restore/1.0.3-build4"))

# The unpublished adapter deliberately reuses the historical vault journal,
# without taking a dependency on or changing released Core software in CI.
platform = types.ModuleType("monitorbox")
v2 = types.ModuleType("monitorbox.v2")
backup = types.ModuleType("monitorbox.v2.appliance_backup")


class ApplianceBackupError(Exception):
    pass


class ApplianceBackupManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def inspect(self, path: Path) -> None:
        raise AssertionError("v2 legacy inspector MUST NOT inspect native ZIP")


backup.ApplianceBackupError = ApplianceBackupError
backup.ApplianceBackupManager = ApplianceBackupManager
sys.modules["monitorbox"] = platform
sys.modules["monitorbox.v2"] = v2
sys.modules["monitorbox.v2.appliance_backup"] = backup

from backup_restore_native_archive import (  # noqa: E402
    NativeArchiveError, inspect_native_archive,
)
from backup_restore_native_vault import (  # noqa: E402
    NativeBackupVault, BackupVaultError, open_native_backup_vault,
)
from backup_restore_native_jobs import NativeBackupJobStore, NativeBackupJobError  # noqa: E402

TRUST_ROOT = b"synthetic-test-trust-not-a-real-package-signer"
ACTIVE_ID = "a" * 32
PREVIOUS_ID = "b" * 32
PACKAGE = b"synthetic signed UI module bytes; no actual executable package"


def make_native_zip(
    destination: Path, *, prior: bool = True,
    break_digest: bool = False, break_signature: bool = False,
    extra_member: bool = False, legacy_format: bool = False,
) -> Path:
    package_sha = hashlib.sha256(PACKAGE).hexdigest()
    signature = hmac.new(TRUST_ROOT, PACKAGE, hashlib.sha256).hexdigest()
    if break_signature:
        signature = "0" * 64
    receipt = json.dumps({
        "package_sha256": package_sha,
        "signature": signature,
    }, sort_keys=True).encode("utf-8")
    config = b'{"schema":1,"purpose":"test-only"}'
    inventory: dict[str, bytes] = {
        "authority/active/receipt.json": receipt,
        "authority/active/config.json": config,
        "authority/active/state/state.db": b"current-up-to-date-state",
        "packages/signed/test-ui.zip": PACKAGE,
    }
    manifest: dict[str, object] = {
        "format": "monitorbox-successor-full-v1" if not legacy_format else "monitorbox-appliance-backup",
        "schema": 1,
        "active": {
            "ref": {"id": ACTIVE_ID, "manifest_sha256": "a" * 64},
            "receipt": "authority/active/receipt.json",
            "config": "authority/active/config.json",
            "state_root": "authority/active/state",
        },
        "packages": [{
            "path": "signed/test-ui.zip",
            "sha256": package_sha,
            "size": len(PACKAGE),
        }],
        "files": {},
    }
    if prior:
        inventory.update({
            "authority/previous/receipt.json": receipt,
            "authority/previous/config.json": config,
            "authority/previous/state/state.db": b"old-last-known-good",
        })
        manifest["previous"] = {
            "ref": {"id": PREVIOUS_ID, "manifest_sha256": "b" * 64},
            "receipt": "authority/previous/receipt.json",
            "config": "authority/previous/config.json",
            "state_root": "authority/previous/state",
        }
    if extra_member:
        inventory["unreferenced/session-secret"] = b"unauthorized extra entry"

    files = manifest["files"]
    assert isinstance(files, dict)
    for name, payload in inventory.items():
        files[name] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload) if not (break_digest and name.endswith("state.db")) else len(payload) + 1,
            "mode": 0o600,
        }
    raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as zipfile_out:
        for name, payload in [("manifest.json", raw), *sorted(inventory.items())]:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zipfile_out.writestr(info, payload)
    os.chmod(destination, 0o600)
    return destination


def verify_test_signed_closure(path: Path, inspection) -> None:
    """Simulates independent signed authority; never trust archive manifest."""
    if inspection.active_id != ACTIVE_ID:
        raise ValueError("not a trusted Active generation")
    with zipfile.ZipFile(path) as archive:
        package = archive.read("packages/signed/test-ui.zip")
        receipt = json.loads(archive.read("authority/active/receipt.json"))
        local_digest = hashlib.sha256(package).hexdigest()
        signed = hmac.new(TRUST_ROOT, package, hashlib.sha256).hexdigest()
        if not (
            hmac.compare_digest(receipt["package_sha256"], local_digest)
            and hmac.compare_digest(receipt["signature"], signed)
        ):
            raise ValueError("independent trust-root signature mismatch")


class NativeVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.vault = NativeBackupVault(
            self.root, verify_signed_closure=verify_test_signed_closure
        )

    def source(self, **options) -> Path:
        file = self.root / ("archive-" + os.urandom(4).hex() + ".zip")
        return make_native_zip(file, **options)

    def publish(self, path: Path, vault=None, planned_backup_id=None):
        vault = vault or self.vault
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return vault.create_from_verified_transfer(
            path, transport_bytes=path.stat().st_size,
            transport_sha256=digest, label="Test Backup", kind="manual",
            planned_backup_id=planned_backup_id,
        )

    def test_native_signed_backup_and_previous_are_atomically_saved(self) -> None:
        source = self.source(prior=True)
        inspection = inspect_native_archive(source)
        self.assertTrue(inspection.includes_previous)
        self.assertGreater(inspection.file_count, 4)
        record = self.publish(source)
        saved = self.vault.get(record.backup_id, verify=True)
        self.assertEqual(saved.sha256, inspection.sha256)
        self.assertEqual(saved.bytes, inspection.zip_bytes)
        self.assertEqual(saved.kind, "manual")
        report = self.vault.inspect(record.backup_id)
        self.assertEqual(report["format"], "monitorbox-successor-full-v1")
        self.assertEqual(report["file_count"], inspection.file_count)
        self.assertEqual(self.vault.archive_path(record.backup_id).read_bytes(), source.read_bytes())
        self.assertEqual(len(self.vault.list()), 1)
        self.assertEqual(
            NativeBackupVault(self.root, verify_signed_closure=verify_test_signed_closure).list(),
            self.vault.list()
        )

    def test_job_cannot_claim_committed_until_native_vault_reverifies_signed_zip(self) -> None:
        source = self.source()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        job_store = NativeBackupJobStore(self.root)
        request = "1" * 32
        job_store.reserve(
            request_id=request, generation="2" * 32,
            kind="manual", include_previous=True,
        )
        job_store.accept(request_id=request, job_id="3" * 32)
        job_store.mark_transfer_verified(
            request_id=request, bytes_count=source.stat().st_size, sha256=digest,
        )
        with self.assertRaisesRegex(NativeBackupJobError, "unavailable or unverifiable"):
            job_store.commit(
                request_id=request, backup_id=job_store.inspect().planned_backup_id,
                vault=self.vault,
            )
        self.assertEqual(job_store.inspect().phase, "transfer_verified")
        planned = job_store.inspect().planned_backup_id
        record = self.publish(source, planned_backup_id=planned)
        self.assertEqual(record.backup_id, planned)
        saved = job_store.commit(
            request_id=request, backup_id=record.backup_id,
            vault=self.vault,
        )
        self.assertEqual(saved.backup_id, record.backup_id)
        self.assertEqual(saved.phase, "committed")
        self.assertEqual(NativeBackupJobStore(self.root).inspect(), saved)
        self.assertEqual(
            job_store.commit(request_id=request, backup_id=record.backup_id, vault=self.vault),
            saved,
        )

    def test_crash_after_reserved_vault_commit_recovers_same_job_identity(self) -> None:
        source = self.source()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        journal = NativeBackupJobStore(self.root)
        request_id = "5" * 32
        reserved = journal.reserve(
            request_id=request_id, generation="6" * 32,
            kind="manual", include_previous=False,
        )
        journal.accept(request_id=request_id, job_id="7" * 32)
        journal.mark_transfer_verified(
            request_id=request_id, bytes_count=source.stat().st_size,
            sha256=digest,
        )
        original = self.vault._checkpoint

        def fault(phase):
            if phase == "metadata_published":
                raise SystemExit("Core crashed after actual ZIP+metadata publication")
            return original(phase)

        self.vault._checkpoint = fault
        with self.assertRaises(SystemExit):
            self.publish(source, planned_backup_id=reserved.planned_backup_id)
        # The prior Core could not commit the job journal after the crash.
        self.assertEqual(journal.inspect().phase, "transfer_verified")
        restarted_vault = NativeBackupVault(
            self.root, verify_signed_closure=verify_test_signed_closure,
        )
        recovered = restarted_vault.get(reserved.planned_backup_id, verify=True)
        self.assertEqual(recovered.sha256, digest)
        same = self.publish(
            source, vault=restarted_vault, planned_backup_id=reserved.planned_backup_id,
        )
        self.assertEqual(same, recovered)
        terminal = NativeBackupJobStore(self.root).commit(
            request_id=request_id, backup_id=reserved.planned_backup_id,
            vault=restarted_vault,
        )
        self.assertEqual(terminal.phase, "committed")
        self.assertEqual(terminal.backup_id, reserved.planned_backup_id)
        self.assertEqual(len(restarted_vault.list()), 1)

    def test_pre_reserved_vault_identity_refuses_different_archive_bytes(self) -> None:
        first = self.source()
        reserved_id = "20261009T150000Z-01234567"
        record = self.publish(first, planned_backup_id=reserved_id)
        self.assertEqual(record.backup_id, reserved_id)
        second = self.source(prior=False)
        with self.assertRaisesRegex(BackupVaultError, "different bytes"):
            self.publish(second, planned_backup_id=reserved_id)
        self.assertEqual(len(self.vault.list()), 1)

    def test_signed_module_host_facade_authenticates_real_native_vault_inspection(self) -> None:
        source = self.source()
        calls = []
        def verify(path, inspection):
            calls.append((path, inspection.sha256))
            verify_test_signed_closure(path, inspection)
            return None
        platform = SimpleNamespace(
            root=self.root,
            native_full_archive=SimpleNamespace(verify_signed_closure=verify),
        )
        host_vault = open_native_backup_vault(platform)
        saved = self.publish(source, vault=host_vault)
        self.assertEqual(host_vault.get(saved.backup_id, verify=True), saved)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(path.is_relative_to(host_vault.path) for path, _ in calls))
        self.assertEqual(self.vault.list(), host_vault.list())

    def test_signed_module_host_facade_absent_refuses_before_reconciliation(self) -> None:
        for platform in (
            SimpleNamespace(root=self.root),
            SimpleNamespace(root=self.root, native_full_archive=None),
            SimpleNamespace(root=self.root, native_full_archive=SimpleNamespace()),
        ):
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(BackupVaultError, "independent Supervisor signature"):
                    open_native_backup_vault(platform)
        self.assertEqual(self.vault.list(), ())

    def test_signed_module_host_facade_must_not_return_fabricated_metadata(self) -> None:
        source = self.source()
        false_capability = SimpleNamespace(
            verify_signed_closure=lambda path, inspection: {
                "verified": True, "sha256": inspection.sha256
            }
        )
        host_vault = open_native_backup_vault(
            SimpleNamespace(root=self.root, native_full_archive=false_capability)
        )
        with self.assertRaisesRegex(BackupVaultError, "must return no"):
            self.publish(source, vault=host_vault)
        self.assertEqual(host_vault.list(), ())

    def test_signed_module_host_facade_rejection_cannot_save_native_zip(self) -> None:
        source = self.source()
        def reject(_path, _inspection):
            raise RuntimeError("synthetic rejected cryptographic signature")
        host_vault = open_native_backup_vault(SimpleNamespace(
            root=self.root,
            native_full_archive=SimpleNamespace(verify_signed_closure=reject),
        ))
        with self.assertRaisesRegex(BackupVaultError, "signed package authority"):
            self.publish(source, vault=host_vault)
        self.assertEqual(host_vault.list(), ())

    def test_no_independent_signer_no_vault_admission(self) -> None:
        with self.assertRaisesRegex(BackupVaultError, "independent signed closure"):
            NativeBackupVault(self.root)
        self.assertEqual(self.vault.list(), ())

    def test_tampered_signed_package_fails_before_saved_backup_publication(self) -> None:
        bad = self.source(break_signature=True)
        self.assertEqual(inspect_native_archive(bad).format, "monitorbox-successor-full-v1")
        with self.assertRaisesRegex(BackupVaultError, "signed package authority"):
            self.publish(bad)
        self.assertEqual(self.vault.list(), ())
        self.assertFalse(list(self.vault.path.glob("*.zip")))

    def test_bad_manifest_member_size_rejected_before_publishing(self) -> None:
        bad = self.source(break_digest=True)
        with self.assertRaisesRegex(BackupVaultError, "structural verification"):
            self.publish(bad)
        self.assertEqual(self.vault.list(), ())

    def test_extra_or_legacy_zip_cannot_be_relabelled_as_signed_native(self) -> None:
        for options in ({"extra_member": True}, {"legacy_format": True}):
            with self.subTest(options=options):
                bad = self.source(**options)
                with self.assertRaisesRegex(BackupVaultError, "structural verification"):
                    self.publish(bad)
        self.assertEqual(self.vault.list(), ())

    def test_partial_or_mismatched_transport_never_creates_metadata(self) -> None:
        src = self.source()
        with self.assertRaisesRegex(BackupVaultError, "transport evidence"):
            self.vault.create_from_verified_transfer(
                src, transport_bytes=src.stat().st_size + 1,
                transport_sha256="0" * 64,
            )
        self.assertEqual(self.vault.list(), ())
        with self.assertRaisesRegex(BackupVaultError, "changed during private vault copy"):
            self.vault.create_from_verified_transfer(
                src, transport_bytes=src.stat().st_size,
                transport_sha256="0" * 64,
            )
        self.assertEqual(self.vault.list(), ())

    def test_native_backup_rejects_old_writer_even_with_valid_synthetic_archives(self) -> None:
        with self.assertRaisesRegex(BackupVaultError, "signed Supervisor"):
            self.vault.create(label="legacy-writer-must-never-run")
        self.assertEqual(self.vault.list(), ())

    def test_reconciliation_recovers_prepared_but_unpublished_signed_native(self) -> None:
        src = self.source()
        original = self.vault._checkpoint

        def fault(phase):
            if phase == "ready_written":
                raise SystemExit("synthetic crash after durable ready journal")
            return original(phase)

        self.vault._checkpoint = fault
        with self.assertRaises(SystemExit):
            self.publish(src)
        resumed = NativeBackupVault(self.root, verify_signed_closure=verify_test_signed_closure)
        records = resumed.list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].sha256, hashlib.sha256(src.read_bytes()).hexdigest())
        self.assertFalse(list(resumed.transactions.iterdir()))

    def test_reconciliation_after_partial_final_publication_is_signed(self) -> None:
        src = self.source()
        original = self.vault._checkpoint

        def fault(phase):
            if phase == "archive_published":
                raise SystemExit("synthetic crash after ZIP rename but before metadata")
            return original(phase)

        self.vault._checkpoint = fault
        with self.assertRaises(SystemExit):
            self.publish(src)
        restarted = NativeBackupVault(self.root, verify_signed_closure=verify_test_signed_closure)
        saved = restarted.list()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].sha256, hashlib.sha256(src.read_bytes()).hexdigest())
        self.assertFalse(list(restarted.transactions.iterdir()))

    def test_reconciliation_rejects_tampered_prepared_native_backup(self) -> None:
        src = self.source()
        def fault(phase):
            if phase == "ready_written":
                raise SystemExit("simulated crash")
        self.vault._checkpoint = fault
        with self.assertRaises(SystemExit):
            self.publish(src)
        staged = list(self.vault.transactions.glob("*/archive.zip"))
        self.assertEqual(len(staged), 1)
        os.chmod(staged[0], 0o600)
        with staged[0].open("ab") as w:
            w.write(b"tamper-after-ready")
        recovered = NativeBackupVault(self.root, verify_signed_closure=verify_test_signed_closure)
        self.assertEqual(recovered.list(), ())
        self.assertFalse(list(recovered.path.glob("*.zip")))
        self.assertTrue(list(recovered.quarantine.iterdir()))

    def test_native_vault_rejects_untrusted_root_before_permission_mutation(self) -> None:
        alias = self.root.parent / ("vault-link-" + os.urandom(4).hex())
        alias.symlink_to(self.root, target_is_directory=True)
        try:
            with self.assertRaisesRegex(BackupVaultError, "real absolute"):
                NativeBackupVault(alias, verify_signed_closure=verify_test_signed_closure)
        finally:
            alias.unlink(missing_ok=True)

        other = self.root / "public-vault-root"
        other.mkdir(mode=0o755)
        with self.assertRaisesRegex(BackupVaultError, "must be private"):
            NativeBackupVault(other, verify_signed_closure=verify_test_signed_closure)
        self.assertEqual(other.stat().st_mode & 0o777, 0o755)
        # Pre-existing saved-backups symlink is especially dangerous because
        # historical BackupVault.ensure chmods its storage directories.
        victim = self.root / "victim"
        victim.mkdir(mode=0o755)
        evil_root = self.root / "separate"
        evil_root.mkdir(mode=0o700)
        (evil_root / "saved-backups").symlink_to(victim, target_is_directory=True)
        with self.assertRaisesRegex(BackupVaultError, "directory is unsafe"):
            NativeBackupVault(evil_root, verify_signed_closure=verify_test_signed_closure)
        self.assertEqual(victim.stat().st_mode & 0o777, 0o755)

    def test_symlink_or_public_transfer_source_denied(self) -> None:
        src = self.source()
        link = self.root / "source-link.zip"
        link.symlink_to(src)
        with self.assertRaisesRegex(BackupVaultError, "canonical"):
            self.publish(link)
        os.chmod(src, 0o644)
        with self.assertRaisesRegex(BackupVaultError, "private"):
            self.publish(src)
        self.assertEqual(self.vault.list(), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
