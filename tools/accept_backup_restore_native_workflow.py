"""Crash/restart native manual+scheduled Backup/Restore development workflow acceptance.

No production signer, real module, HTTP route, scheduled loop or deployment.
Valid ZIP bytes and independent synthetic test signer come from the existing
native vault acceptance fixture.
"""
from __future__ import annotations

import fcntl
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
        self.job_id = None
        self.phase = "working"
        self.prior_terminal = False
        self.started = 0
        self.downloads = 0
        self.interrupt_claim_once = False
        self.drop_first_ack = False
        self.force_failure = False
        self.invalid_signature = False

    def verify_signed_closure(self, path, inspection):
        if self.invalid_signature:
            raise ValueError("independent signer refused archive")
        verify_test_signed_closure(path, inspection)

    def begin_backup(self, *, request_id, include_previous):
        self.started += 1
        self.previous = include_previous
        if self.job_id is None:
            self.job_id = request_id
        elif self.job_id != request_id:
            # Go preserves idempotency for uncertain retries, but a terminal
            # FAILED/CLAIMED job may be followed by a new planned backup.
            # Reject any other nonce while the old ZIP is still pending.
            if not self.prior_terminal:
                raise AssertionError("second native nonce admitted over pending job")
            self.job_id = request_id
            self.prior_terminal = False
            self.phase = "working"
        if self.drop_first_ack:
            self.drop_first_ack = False
            raise ConnectionError("Core died after snapshot started")
        return self.job_id

    def backup_status(self, job_id):
        assert job_id == self.job_id
        if self.phase in {"claimed", "failed"}:
            self.prior_terminal = True
        return {
            "job_id": job_id, "phase": self.phase,
            "terminal": self.phase in {"ready", "claimed", "failed"},
        }

    def claim_into(self, job_id, sink):
        assert job_id == self.job_id
        if self.phase != "ready":
            raise ValueError("native ZIP is not claimable")
        self.downloads += 1
        raw = self.source.read_bytes()
        # Real Go stores CLAIMED before transferring private ZIP bytes.
        self.phase = "claimed"
        self.prior_terminal = True
        if self.interrupt_claim_once:
            self.interrupt_claim_once = False
            sink.write(raw[:7])
            raise ConnectionError("Core died during irreversible ZIP claim")
        sink.write(raw)
        return len(raw)


class NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = make_native_zip(self.root / "signed-full.zip")
        self.authority = NativeAuthority(self.source)
        self.platform = SimpleNamespace(root=self.root, native_full_archive=self.authority)
        self.workflow = NativeBackupWorkflow(self.platform)

    def test_b7_bootstrap_never_queries_signed_active_before_authority_commit(self):
        class DeferredActive:
            def __init__(self, backend):
                self.backend = backend
                self.authority_committed = False
                self.lookups = 0

            @property
            def generation_id(self):
                self.lookups += 1
                if not self.authority_committed:
                    raise RuntimeError("signed Active unavailable before Core BootReady")
                return self.backend.generation_id

            def begin_backup(self, **kwargs):
                return self.backend.begin_backup(**kwargs)

            def backup_status(self, request_id):
                return self.backend.backup_status(request_id)

            def claim_into(self, request_id, sink):
                return self.backend.claim_into(request_id, sink)

            def verify_signed_closure(self, path, inspection):
                return self.backend.verify_signed_closure(path, inspection)

        capability = DeferredActive(self.authority)
        platform = SimpleNamespace(root=self.root, native_full_archive=capability)
        # Real first launch: Controller/module startup precedes the separate
        # Supervisor signed Active commit. Must not call the live descriptor.
        running = NativeBackupWorkflow(platform)
        self.assertEqual(capability.lookups, 0)
        self.assertIsNone(running.inspect())
        capability.authority_committed = True
        accepted = running.request(kind="manual", include_previous=False)
        self.assertEqual(accepted.phase, "accepted")
        self.assertEqual(capability.lookups, 1)
        self.assertFalse(self.authority.previous)

    def test_overlapping_core_worker_lock_refuses_second_start_and_transfer(self):
        lock=self.workflow.vault.path / ".native-fullzip-operation.lock"
        fd=os.open(lock,os.O_RDWR|os.O_CREAT,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(NativeBackupWorkflowError,"already active"):
                self.workflow.request(kind="manual")
            with self.assertRaisesRegex(NativeBackupWorkflowError,"already active"):
                self.workflow.advance()
            self.assertIsNone(NativeBackupJobStore(self.root).inspect())
            self.assertEqual(self.authority.started,0)
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN)
            os.close(fd)
        accepted=self.workflow.request(kind="manual")
        self.assertEqual(accepted.phase,"accepted")
        self.assertEqual(self.authority.started,1)

    def test_symlinked_cross_process_lock_is_rejected_before_quiescing_core(self):
        target=self.root / "untrusted-lock"
        target.write_text("not an authority")
        lock=self.workflow.vault.path / ".native-fullzip-operation.lock"
        lock.symlink_to(target)
        with self.assertRaisesRegex(NativeBackupWorkflowError,"lock unavailable"):
            self.workflow.request(kind="manual")
        self.assertEqual(target.read_text(),"not an authority")
        self.assertEqual(self.authority.started,0)
        self.assertIsNone(NativeBackupJobStore(self.root).inspect())

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
        self.assertEqual(self.authority.phase, "claimed")
        self.assertEqual(len(self.workflow.vault.list()), 1)
        self.assertEqual(self.workflow.advance(), done)
        self.assertEqual(self.authority.downloads, 1)
        self.assertFalse(list(self.workflow.transfer_root.glob("*.zip")))

    def test_scheduled_uses_same_native_writer_and_never_legacy_create(self):
        self.authority.phase = "ready"
        accepted = self.workflow.request(kind="scheduled", include_previous=False)
        self.assertEqual(accepted.phase, "accepted")
        self.assertIsNone(accepted.backup_id)
        result = self.workflow.advance()
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
        accepted = self.workflow.request(kind="manual")
        self.assertEqual(accepted.phase, "accepted")
        with self.assertRaises(Exception):
            self.workflow.advance()
        status = self.workflow.inspect()
        self.assertEqual(status.phase, "transfer_verified")
        self.assertIsNone(status.backup_id)
        self.assertEqual(self.workflow.vault.list(), ())
        self.assertFalse(list(self.workflow.transfer_root.glob("*.zip")))

    def test_failed_supervisor_job_never_reports_saved_backup(self):
        self.authority.phase = "failed"
        accepted = self.workflow.request(kind="scheduled")
        self.assertEqual(accepted.phase, "accepted")
        result = self.workflow.advance()
        self.assertEqual(result.phase, "failed")
        self.assertEqual(result.failure_code, "archive_failed")
        self.assertEqual(self.workflow.vault.list(), ())
        self.assertEqual(self.authority.downloads, 0)

    def test_changed_signed_active_denies_resumption_without_publishing(self):
        accepted = self.workflow.request(kind="manual")
        self.authority.generation_id = "e" * 32
        self.authority.phase = "ready"
        with self.assertRaisesRegex(NativeBackupWorkflowError, "signed Active authority changed"):
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
        admitted = self.workflow.request(kind="manual")
        self.assertEqual(admitted.phase, "accepted")
        with self.assertRaises(SystemExit):
            self.workflow.advance()
        before = NativeBackupJobStore(self.root).inspect()
        self.assertEqual(before.phase, "transfer_verified")
        orphan = self.workflow.transfer_root / (admitted.request_id + ".zip")
        orphan.write_bytes(b"synthetic interrupted partial output")
        orphan.chmod(0o600)
        resumed = NativeBackupWorkflow(self.platform)
        after = resumed.advance()
        self.assertFalse(orphan.exists())
        self.assertEqual(after.phase, "committed")
        self.assertEqual(after.backup_id, before.planned_backup_id)
        self.assertEqual(len(resumed.vault.list()), 1)
        self.assertEqual(self.authority.downloads, 1)
        self.assertEqual(resumed.advance(), after)

    def test_terminal_committed_job_cleans_orphaned_private_claim_file(self):
        admitted = self.workflow.request(kind="manual")
        self.authority.phase = "ready"
        done = self.workflow.advance()
        self.assertEqual(done.phase, "committed")
        leftover = self.workflow.transfer_root / (admitted.request_id + ".zip")
        leftover.write_bytes(b"interrupted old private stage")
        leftover.chmod(0o600)
        resumed = NativeBackupWorkflow(self.platform)
        self.assertEqual(resumed.advance().backup_id, done.backup_id)
        self.assertFalse(leftover.exists())

    def test_core_restart_does_not_change_stable_signed_active_identity(self):
        pending = self.workflow.request(kind="manual", include_previous=False)
        self.authority.phase = "ready"
        fresh = NativeBackupWorkflow(self.platform)
        self.assertEqual(fresh.native.generation_id, pending.generation)
        saved = fresh.advance()
        self.assertEqual(saved.phase, "committed")
        self.assertEqual(saved.request_id, pending.request_id)
        self.assertEqual(self.authority.started, 1)

    def test_transfer_verified_cannot_reclaim_ready_job_without_vault_record(self):
        admitted = self.workflow.request(kind="manual")
        raw = self.source.read_bytes()
        self.workflow.jobs.mark_transfer_verified(
            request_id=admitted.request_id,
            bytes_count=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
        )
        self.authority.phase = "ready"
        with self.assertRaisesRegex(
            NativeBackupWorkflowError, "explicit vault reconciliation"
        ):
            NativeBackupWorkflow(self.platform).advance()
        self.assertEqual(self.authority.downloads, 0)
        self.assertEqual(self.workflow.vault.list(), ())

    def test_lost_begin_ack_never_invents_saved_backup_after_claim_consumed(self):
        self.authority.drop_first_ack = True
        with self.assertRaisesRegex(NativeBackupWorkflowError, "begin is unresolved"):
            self.workflow.request(kind="manual", include_previous=False)
        pending = NativeBackupJobStore(self.root).inspect()
        self.assertEqual(pending.phase, "requested")
        self.assertFalse(pending.include_previous)
        # The requesting Core exited after Supervisor had already admitted
        # this exact nonce. Another verified Core observes CLAIMED but no
        # saved module vault record, so it MUST NOT claim or save a ZIP.
        self.authority.phase = "claimed"
        recovered = NativeBackupWorkflow(self.platform).advance()
        self.assertEqual(recovered.phase, "failed")
        self.assertEqual(recovered.failure_code, "transfer_failed")
        self.assertEqual(recovered.request_id, pending.request_id)
        self.assertEqual(self.authority.downloads, 0)
        self.assertEqual(self.authority.started, 2)
        self.assertEqual(self.workflow.vault.list(), ())

    def test_lost_one_time_claim_never_retries_and_marks_delivery_failed(self):
        self.workflow.request(kind="manual")
        self.authority.phase = "ready"
        self.authority.interrupt_claim_once = True
        with self.assertRaisesRegex(NativeBackupWorkflowError, "not yet durably committed"):
            self.workflow.advance()
        self.assertEqual(self.authority.phase, "claimed")
        self.assertFalse(list(self.workflow.transfer_root.glob("*.zip")))
        fresh = NativeBackupWorkflow(self.platform)
        lost = fresh.advance()
        self.assertEqual(lost.phase, "failed")
        self.assertEqual(lost.failure_code, "transfer_failed")
        self.assertEqual(self.authority.downloads, 1)
        self.assertEqual(fresh.vault.list(), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
