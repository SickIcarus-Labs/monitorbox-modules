"""Crash/restart native manual+scheduled Backup/Restore development workflow acceptance.

No production signer, real module, HTTP route, scheduled loop or deployment.
Valid ZIP bytes and independent synthetic test signer come from the existing
native vault acceptance fixture.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from accept_backup_restore_native_vault import make_native_zip, verify_test_signed_closure
from backup_restore_native_jobs import NativeBackupJobStore
from backup_restore_native_workflow import NativeBackupWorkflow, NativeBackupWorkflowError


class NativeAuthority:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.generation_id = "c" * 32
        self.job_id = "d" * 32
        self.phase = "preparing"
        self.started = 0
        self.downloads = 0
        self.released = 0
        self.drop_first_ack = False
        self.force_failure = False
        self.invalid_signature = False

    def verify_signed_closure(self, path, inspection):
        if self.invalid_signature:
            raise ValueError("independent signer refused archive")
        verify_test_signed_closure(path, inspection)

    def begin_backup(self, *, include_previous=False):
        self.started += 1
        self.previous = include_previous
        if self.drop_first_ack:
            self.drop_first_ack = False
            raise ConnectionError("Core died after snapshot started")
        return self.job_id

    def backup_status(self, job_id):
        assert job_id == self.job_id
        raw = self.source.read_bytes()
        return {
            "job_id": job_id, "phase": self.phase,
            "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        }

    def fetch_backup(self, job_id, dest):
        assert job_id == self.job_id
        assert dest.name.endswith(".zip")
        assert dest.parent.name == ".native-transfers"
        self.downloads += 1
        with self.source.open("rb") as reader, dest.open("xb") as stream:
            shutil.copyfileobj(reader, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return {
            "size": dest.stat().st_size,
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        }

    def release_backup(self, job_id):
        assert job_id == self.job_id
        self.released += 1


class NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = make_native_zip(self.root / "signed-full.zip")
        self.authority = NativeAuthority(self.source)
        self.platform = SimpleNamespace(root=self.root, native_full_archive=self.authority)
        self.workflow = NativeBackupWorkflow(self.platform)

    def test_manual_start_is_accepted_until_signed_zip_in_vault(self):
        submitted = self.workflow.request(kind="manual", include_previous=True)
        self.assertEqual(submitted.phase, "accepted")
        self.assertEqual(submitted.kind, "manual")
        self.assertIsNone(submitted.backup_id)
        self.assertEqual(self.authority.downloads, 0)
        self.assertEqual(self.workflow.vault.list(), ())
        self.authority.phase = "ready"
        done = self.workflow.advance()
        self.assertEqual(done.phase, "committed")
        self.assertEqual(done.backup_id, submitted.planned_backup_id)
        self.assertEqual(done.bytes, self.source.stat().st_size)
        self.assertEqual(self.authority.released, 1)
        self.assertEqual(len(self.workflow.vault.list()), 1)
        self.assertEqual(self.workflow.advance(), done)
        self.assertEqual(self.authority.downloads, 1)
        self.assertFalse(list(self.workflow.transfer_root.glob("*.zip")))

    def test_scheduled_uses_same_native_writer_and_never_legacy_create(self):
        self.authority.phase = "ready"
        result = self.workflow.request(kind="scheduled", include_previous=False)
        self.assertEqual(result.phase, "committed")
        self.assertEqual(result.kind, "scheduled")
        self.assertFalse(self.authority.previous)
        saved = self.workflow.vault.get(result.backup_id, verify=True)
        self.assertEqual(saved.kind, "scheduled")
        self.assertEqual(len(self.workflow.vault.list()), 1)

    def test_process_restarts_before_supervisor_ack_and_recovers_intent(self):
        self.authority.drop_first_ack = True
        with self.assertRaisesRegex(NativeBackupWorkflowError, "begin is unresolved"):
            self.workflow.request(kind="manual", include_previous=True)
        pending = NativeBackupJobStore(self.root).inspect()
        self.assertEqual(pending.phase, "requested")
        self.assertIsNone(pending.job_id)
        fresh = NativeBackupWorkflow(self.platform)
        self.authority.phase = "ready"
        committed = fresh.advance()
        self.assertEqual(committed.phase, "committed")
        self.assertEqual(committed.request_id, pending.request_id)
        self.assertEqual(committed.backup_id, pending.planned_backup_id)
        self.assertEqual(self.authority.started, 2)
        self.assertEqual(len(fresh.vault.list()), 1)

    def test_process_restarts_after_job_accepted_and_resumes(self):
        accepted = self.workflow.request(kind="manual")
        fresh = NativeBackupWorkflow(self.platform)
        self.assertEqual(fresh.inspect(), accepted)
        self.authority.phase = "ready"
        result = fresh.advance()
        self.assertEqual(result.phase, "committed")
        self.assertEqual(self.authority.started, 1)
        self.assertEqual(len(fresh.vault.list()), 1)

    def test_native_signer_rejects_forged_package_before_vault_commit(self):
        self.authority.phase = "ready"
        self.authority.invalid_signature = True
        with self.assertRaises(Exception):
            self.workflow.request(kind="manual")
        status = self.workflow.inspect()
        self.assertEqual(status.phase, "transfer_verified")
        self.assertIsNone(status.backup_id)
        self.assertEqual(self.workflow.vault.list(), ())
        self.assertFalse(list(self.workflow.transfer_root.glob("*.zip")))

    def test_failed_supervisor_job_never_reports_saved_backup(self):
        self.authority.phase = "failed"
        result = self.workflow.request(kind="scheduled")
        self.assertEqual(result.phase, "failed")
        self.assertEqual(result.failure_code, "archive_failed")
        self.assertEqual(self.workflow.vault.list(), ())
        self.assertEqual(self.authority.downloads, 0)

    def test_changed_generation_denies_resumption_without_publishing(self):
        accepted = self.workflow.request(kind="manual")
        self.authority.generation_id = "e" * 32
        self.authority.phase = "ready"
        with self.assertRaisesRegex(NativeBackupWorkflowError, "generation changed"):
            NativeBackupWorkflow(self.platform).advance()
        self.assertEqual(NativeBackupJobStore(self.root).inspect(), accepted)
        self.assertEqual(self.workflow.vault.list(), ())

    def test_post_metadata_crash_reconciles_exact_vault_id(self):
        self.authority.phase = "ready"
        original = self.workflow.vault._checkpoint
        def crash(phase):
            if phase == "metadata_published":
                raise SystemExit("synthetic Core termination after atomic ZIP/metadata")
            return original(phase)
        self.workflow.vault._checkpoint = crash
        with self.assertRaises(SystemExit):
            self.workflow.request(kind="manual")
        before = NativeBackupJobStore(self.root).inspect()
        self.assertEqual(before.phase, "transfer_verified")
        resumed = NativeBackupWorkflow(self.platform)
        after = resumed.advance()
        self.assertEqual(after.phase, "committed")
        self.assertEqual(after.backup_id, before.planned_backup_id)
        self.assertEqual(len(resumed.vault.list()), 1)
        self.assertEqual(self.authority.downloads, 1)
        self.assertEqual(resumed.advance(), after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
