"""Unreleased signed native scheduled backup policy/destination/retention tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
sys.path.insert(0,str(ROOT/"sources/backup-restore/1.0.1-build2"))
sys.path.insert(0,str(ROOT/"sources/backup-restore/1.0.3-build4"))

from accept_backup_restore_native_vault import make_native_zip  # noqa:E402
from accept_backup_restore_native_workflow import NativeAuthority  # noqa:E402
from backup_restore_native_workflow import NativeBackupWorkflow  # noqa:E402
from backup_restore_native_schedule import NativeScheduledBackup  # noqa:E402
from monitorbox_backup_restore_b2_policy import BackupPolicy, BackupPolicyStore  # noqa:E402
from monitorbox_backup_restore_b2_destinations import BackupDestinationError  # noqa:E402


class NativeScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.archive=make_native_zip(self.root/"source.zip")
        self.authority=NativeAuthority(self.archive)
        self.workflow=NativeBackupWorkflow(SimpleNamespace(
            root=self.root,native_full_archive=self.authority,
        ))
        self.store=BackupPolicyStore(self.root)
        self.scheduler=NativeScheduledBackup(self.workflow,self.store)

    def policy(self, **changes):
        config={
            "enabled":True,
            "interval_hours":24,
            "retention_count":7,
            "retention_bytes":1024*1024*1024,
        }
        config.update(changes)
        return self.store.save(BackupPolicy(**config))

    def complete(self):
        previous=tuple(self.workflow.vault.list())
        self.authority.phase="ready"
        admitted=self.scheduler.run_due(force=True)
        self.assertFalse(admitted["created"])
        self.assertTrue(admitted["accepted"])
        self.assertEqual(admitted["phase"],"accepted")
        # Prior signed scheduled backups may already exist; admission must
        # not publish a *new* ZIP or prune until its own vault commit.
        self.assertEqual(tuple(self.workflow.vault.list()),previous)
        done=self.workflow.advance()
        self.assertEqual(done.phase,"committed")
        return done

    def test_disabled_schedule_does_not_create_backup(self):
        self.assertEqual(self.scheduler.run_due(),{
            "created":False,"reason":"schedule_disabled"
        })
        self.assertEqual(self.authority.started,0)
        self.assertEqual(self.workflow.vault.list(),())

    def test_due_interval_uses_signed_local_vault_record_not_pending_timestamp(self):
        self.policy(interval_hours=24)
        self.assertTrue(self.scheduler.is_due())
        first=self.complete()
        self.assertFalse(self.scheduler.is_due())
        now=datetime.now(timezone.utc)+timedelta(hours=25)
        self.assertTrue(self.scheduler.is_due(now=now))
        self.assertFalse(self.scheduler.run_due(now=now)["created"])
        self.assertEqual(self.workflow.inspect().phase,"accepted")
        self.assertEqual(self.authority.started,2)

    def test_failed_automatic_job_backs_off_until_policy_interval(self):
        self.policy(interval_hours=24)
        self.authority.phase="failed"
        accepted=self.scheduler.run_due()
        self.assertTrue(accepted["accepted"])
        failed=self.workflow.advance()
        self.assertEqual(failed.phase,"failed")
        self.assertEqual(self.authority.started,1)
        for _ in range(3):
            self.assertEqual(self.scheduler.run_due()["reason"],"failed_retry_backoff")
        self.assertEqual(self.authority.started,1)
        later=datetime.now(timezone.utc)+timedelta(hours=25)
        self.authority.phase="preparing"
        retried=self.scheduler.run_due(now=later)
        self.assertTrue(retried["accepted"])
        self.assertEqual(self.authority.started,2)

    def test_pending_job_blocks_duplicate_periodic_or_forced_snapshot(self):
        self.policy()
        first=self.scheduler.run_due()
        self.assertTrue(first["accepted"])
        repeat=self.scheduler.run_due(force=True)
        self.assertEqual(repeat["reason"],"native_job_pending")
        self.assertEqual(repeat["request_id"],first["request_id"])
        self.assertEqual(self.authority.started,1)
        self.assertEqual(self.workflow.vault.list(),())

    def test_destination_copy_only_after_verified_local_commit_and_exact_id(self):
        dest=tempfile.TemporaryDirectory()
        self.addCleanup(dest.cleanup)
        self.policy(destination_type="filesystem",destination_path=dest.name)
        job=self.scheduler.run_due()
        self.assertTrue(job["accepted"])
        self.assertEqual(list(Path(dest.name).iterdir()),[])
        self.authority.phase="ready"
        done=self.workflow.advance()
        result=self.scheduler.finalize_committed()
        self.assertTrue(result["finalized"])
        target=Path(dest.name)/(done.backup_id+".zip")
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(),self.archive.read_bytes())
        self.assertEqual(result["destination"],str(target))
        second=self.scheduler.finalize_committed()
        self.assertTrue(second["finalized"])
        self.assertEqual(len(list(Path(dest.name).iterdir())),1)

    def test_corrupted_existing_destination_never_prunes_signed_vault(self):
        dest=tempfile.TemporaryDirectory()
        self.addCleanup(dest.cleanup)
        self.policy(destination_type="filesystem",destination_path=dest.name)
        done=self.complete()
        target=Path(dest.name)/(done.backup_id+".zip")
        target.write_bytes(b"corrupted NAS zip, must not be trusted")
        with self.assertRaisesRegex(BackupDestinationError,"different backup bytes"):
            self.scheduler.finalize_committed()
        self.assertEqual(len(self.workflow.vault.list()),1)
        self.assertEqual(self.workflow.vault.list()[0].backup_id,done.backup_id)

    def test_scheduled_retention_does_not_delete_manual_archive(self):
        self.policy(retention_count=1,retention_bytes=64*1024*1024)
        older=self.workflow.vault.create_from_verified_transfer(
            self.archive,transport_bytes=self.archive.stat().st_size,
            transport_sha256=__import__("hashlib").sha256(self.archive.read_bytes()).hexdigest(),
            kind="scheduled",
        )
        manual=self.workflow.vault.create_from_verified_transfer(
            self.archive,transport_bytes=self.archive.stat().st_size,
            transport_sha256=__import__("hashlib").sha256(self.archive.read_bytes()).hexdigest(),
            kind="manual",
        )
        done=self.complete()
        result=self.scheduler.finalize_committed()
        self.assertIn(older.backup_id,result["pruned_backup_ids"])
        remaining={r.backup_id for r in self.workflow.vault.list()}
        self.assertEqual(remaining,{manual.backup_id,done.backup_id})

    def test_force_request_while_disabled_is_explicit_and_pending(self):
        self.policy(enabled=False)
        result=self.scheduler.run_due(force=True)
        self.assertTrue(result["accepted"])
        self.assertEqual(self.workflow.inspect().phase,"accepted")
        self.assertEqual(self.authority.started,1)

    def test_last_backup_destination_failure_prevents_next_periodic_run(self):
        dest=tempfile.TemporaryDirectory()
        self.addCleanup(dest.cleanup)
        self.policy(destination_type="filesystem",destination_path=dest.name)
        completed=self.complete()
        target=Path(dest.name)/(completed.backup_id+".zip")
        target.write_bytes(b"colliding NAS file")
        with self.assertRaises(BackupDestinationError):
            self.scheduler.run_due(force=True)
        self.assertEqual(self.authority.started,1)
        self.assertEqual(len(self.workflow.vault.list()),1)


if __name__=="__main__":
    unittest.main(verbosity=2)
