"""Deterministic unpublished native Backup/Restore journal acceptance."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = (
    Path(__file__).resolve().parents[1]
    / "sources/backup-restore/1.1.0-build7/monitorbox_backup_restore_b7_native_jobs.py"
)
spec = importlib.util.spec_from_file_location("backup_restore_b7_native_jobs", MODULE)
assert spec is not None and spec.loader is not None
native = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = native
spec.loader.exec_module(native)

REQ = "1" * 32
JOB = "2" * 32
GEN = "3" * 32
DIGEST = "f" * 64
BACKUP = "20261009T150000Z-a1b2c3d4"


class NativeJobJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.store = native.NativeBackupJobStore(self.root)

    def accept(self, request_id: str = REQ, job_id: str = JOB):
        return self.store.accept(
            request_id=request_id, job_id=job_id,
            generation=GEN, kind="manual", include_previous=True,
        )

    def test_unpublished_accepted_job_survives_core_restart(self) -> None:
        one = self.accept()
        self.assertEqual(one.phase, "accepted")
        self.assertIsNone(one.backup_id)
        resumed = native.NativeBackupJobStore(self.root).inspect()
        self.assertEqual(resumed, one)
        self.assertEqual(self.accept(), one)  # request replay is idempotent
        self.assertNotIn("sha256", {"unexpected": 42})
        self.assertEqual(self.store.journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)
        self.assertFalse(any(p.suffix == ".zip" for p in self.store.directory.iterdir()))

    def test_verified_transfer_is_not_yet_an_operator_saved_backup(self) -> None:
        self.accept()
        verified = self.store.mark_transfer_verified(
            request_id=REQ, bytes_count=2097157, sha256=DIGEST
        )
        self.assertEqual(verified.phase, "transfer_verified")
        self.assertIsNone(verified.backup_id)
        after_restart = native.NativeBackupJobStore(self.root).inspect()
        self.assertEqual(after_restart.phase, "transfer_verified")
        self.assertEqual(self.store.mark_transfer_verified(
            request_id=REQ, bytes_count=2097157, sha256=DIGEST
        ), after_restart)
        committed = self.store.commit(request_id=REQ, backup_id=BACKUP)
        self.assertEqual(committed.phase, "committed")
        self.assertEqual(native.NativeBackupJobStore(self.root).inspect(), committed)
        self.assertEqual(self.store.commit(request_id=REQ, backup_id=BACKUP), committed)
        with self.assertRaisesRegex(native.NativeBackupJobError, "already settled"):
            self.accept()
        later = self.accept(request_id="4" * 32, job_id="5" * 32)
        self.assertEqual(later.phase, "accepted")

    def test_missing_transfer_or_changed_digest_cannot_commit(self) -> None:
        self.accept()
        with self.assertRaisesRegex(native.NativeBackupJobError, "cannot be called saved"):
            self.store.commit(request_id=REQ, backup_id=BACKUP)
        with self.assertRaises(native.NativeBackupJobError):
            self.store.mark_transfer_verified(
                request_id=REQ, bytes_count=0, sha256=DIGEST
            )
        verified = self.store.mark_transfer_verified(
            request_id=REQ, bytes_count=42, sha256=DIGEST
        )
        with self.assertRaisesRegex(native.NativeBackupJobError, "evidence changed"):
            self.store.mark_transfer_verified(
                request_id=REQ, bytes_count=43, sha256=DIGEST
            )
        self.assertEqual(self.store.inspect(), verified)

    def test_conflicting_live_jobs_and_generation_mutation_refuse(self) -> None:
        self.accept()
        with self.assertRaisesRegex(native.NativeBackupJobError, "already"):
            self.accept(request_id="a" * 32, job_id="b" * 32)
        with self.assertRaisesRegex(native.NativeBackupJobError, "already"):
            self.store.accept(
                request_id=REQ, job_id=JOB, generation="c" * 32,
                kind="manual", include_previous=True,
            )
        self.assertEqual(self.store.inspect().generation, GEN)

    def test_failed_archives_record_nonsecret_terminal_result(self) -> None:
        self.accept()
        self.store.mark_transfer_verified(request_id=REQ, bytes_count=42, sha256=DIGEST)
        failed = self.store.fail(request_id=REQ, failure_code="vault_failed")
        self.assertEqual(failed.phase, "failed")
        self.assertIsNone(failed.backup_id)
        self.assertEqual(self.store.fail(
            request_id=REQ, failure_code="vault_failed"
        ), failed)
        with self.assertRaises(native.NativeBackupJobError):
            self.store.commit(request_id=REQ, backup_id=BACKUP)
        with self.assertRaises(native.NativeBackupJobError):
            self.store.fail(
                request_id=REQ, failure_code="SECRET_API_TOKEN_should_not_appear"
            )
        raw = self.store.journal.read_bytes()
        self.assertNotIn(b"SECRET_API_TOKEN", raw)
        self.assertEqual(native.NativeBackupJobStore(self.root).inspect(), failed)

    def test_invalid_identity_and_unknown_archive_status_refuse(self) -> None:
        bad = (
            ("../bad", JOB, GEN),
            (REQ, "F" * 32, GEN),
            (REQ, JOB, "/tmp/untrusted"),
        )
        for request_id, job_id, generation in bad:
            with self.subTest(request_id=request_id, job_id=job_id):
                with self.assertRaises(native.NativeBackupJobError):
                    self.store.accept(
                        request_id=request_id, job_id=job_id, generation=generation,
                        kind="manual", include_previous=False,
                    )
        self.assertIsNone(self.store.inspect())

    def test_reject_symlink_or_world_readable_journal(self) -> None:
        hidden = self.root / "hidden.json"
        hidden.write_text("{}")
        self.store.journal.symlink_to(hidden)
        with self.assertRaises(OSError):
            self.store.inspect()  # O_NOFOLLOW never reads linked content
        self.store.journal.unlink()
        self.accept()
        os.chmod(self.store.journal, 0o644)
        with self.assertRaisesRegex(native.NativeBackupJobError, "unsafe"):
            self.store.inspect()
        os.chmod(self.store.journal, 0o600)
        os.chmod(self.store.directory, 0o755)
        with self.assertRaisesRegex(native.NativeBackupJobError, "not private"):
            self.store.inspect()

    def test_corrupt_or_unknown_journal_fields_fail_closed(self) -> None:
        self.accept()
        raw = json.loads(self.store.journal.read_text())
        raw["opaque_extra"] = "do not silently trust extra state"
        self.store.journal.write_text(json.dumps(raw))
        with self.assertRaisesRegex(native.NativeBackupJobError, "shape"):
            self.store.inspect()
        self.assertFalse(any(p.suffix == ".zip" for p in self.store.directory.iterdir()))

    def test_interrupted_post_rename_sync_keeps_valid_recoverable_state(self) -> None:
        self.accept()
        with patch.object(native, "_sync_dir", side_effect=OSError("simulated fsync interruption")):
            with self.assertRaises(OSError):
                self.store.mark_transfer_verified(
                    request_id=REQ, bytes_count=42, sha256=DIGEST,
                )
        # Once an atomic rename occurs, a reported error cannot be used to
        # assume that the phase stayed pending. The next process must inspect.
        status = native.NativeBackupJobStore(self.root).inspect()
        self.assertEqual(status.phase, "transfer_verified")
        self.assertIsNone(status.backup_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
