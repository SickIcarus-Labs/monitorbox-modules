"""Development-only native scheduled Backup/Restore policy and retention adapter.

This deliberately reuses the existing module-owned BackupPolicyStore,
FilesystemBackupDestination and NativeBackupVault retention. Never call the
legacy v2 vault.create or mark a schedule successful on HTTP 202. A scheduled
ZIP is independently signed and committed locally before copying to a NAS
destination or pruning old scheduled backups.

Not installed by build6; all behavior is tested with an isolated synthetic
signed archive. The full signed build7 candidate remains a separate gate.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from monitorbox_backup_restore_b2_policy import BackupPolicyStore, BackupPolicyError
from monitorbox_backup_restore_b2_destinations import (
    FilesystemBackupDestination, BackupDestinationError,
)
from backup_restore_native_workflow import NativeBackupWorkflow, NativeBackupWorkflowError


class NativeScheduledBackup:
    def __init__(
        self, workflow: NativeBackupWorkflow,
        policy_store: BackupPolicyStore,
    ):
        self.workflow=workflow
        self.policy_store=policy_store

    def _latest_scheduled(self):
        return next((record for record in self.workflow.vault.list()
                     if record.kind=="scheduled"),None)

    def is_due(self, *, now: datetime | None = None) -> bool:
        policy=self.policy_store.load()
        if not policy.enabled:
            return False
        item=self.workflow.inspect()
        if item is not None and item.phase in {
            "requested","accepted","transfer_verified",
        }:
            return False
        latest=self._latest_scheduled()
        if latest is None:
            return True
        now=now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise BackupPolicyError("scheduled backup clock must be timezone-aware")
        try:
            when=datetime.fromisoformat(latest.created_at)
        except ValueError as exc:
            # Corrupt schedule timing is not authority to repeatedly create
            # duplicate signed backups.
            raise BackupPolicyError("last signed scheduled backup timestamp invalid") from exc
        if when.tzinfo is None:
            raise BackupPolicyError("last signed scheduled backup timestamp has no offset")
        return now>=when+timedelta(hours=policy.interval_hours)

    @staticmethod
    def _verify_existing_destination(destination: Path, *, size: int, digest: str) -> bool:
        if not destination.exists() and not destination.is_symlink():
            return False
        if not destination.is_file() or destination.is_symlink():
            raise BackupDestinationError("existing scheduled destination is unsafe")
        checksum=hashlib.sha256()
        with destination.open("rb") as stream:
            for data in iter(lambda:stream.read(1<<20),b""):
                checksum.update(data)
        if destination.stat().st_size!=size or checksum.hexdigest()!=digest:
            raise BackupDestinationError(
                "scheduled destination already contains different backup bytes"
            )
        return True

    def finalize_committed(self) -> dict[str, Any]:
        """Idempotent post-commit destination copy then scheduled-only prune.

        If NAS publication fails, the verified local ZIP remains safe and
        pruning is postponed; the next Core start may retry the exact copy.
        """
        item=self.workflow.inspect()
        if item is None or item.phase!="committed" or item.kind!="scheduled":
            return {"finalized":False,"reason":"no_committed_scheduled_backup"}
        policy=self.policy_store.load()
        record=self.workflow.vault.get(item.planned_backup_id,verify=True)
        destination=None
        if policy.destination_type=="filesystem":
            path=Path(str(policy.destination_path)).expanduser()
            publisher=FilesystemBackupDestination(path)
            filename=record.backup_id+".zip"
            existing=path/filename
            if not self._verify_existing_destination(
                existing,size=record.bytes,digest=record.sha256,
            ):
                source=self.workflow.vault.archive_path(record.backup_id,verify=True)
                outcome=publisher.publish(source,filename=filename)
                if outcome.sha256!=record.sha256 or outcome.bytes!=record.bytes:
                    raise BackupDestinationError("signed scheduled copy proof mismatch")
            destination=str(existing)
        elif policy.destination_type is not None:
            raise BackupPolicyError("unsupported scheduled destination")
        pruned=self.workflow.vault.prune_scheduled(
            retention_count=policy.retention_count,
            retention_bytes=policy.retention_bytes,
        )
        return {
            "finalized":True,"backup_id":record.backup_id,
            "destination":destination,"pruned_backup_ids":list(pruned),
        }

    def run_due(self, *, force: bool=False, now:datetime|None=None) -> dict[str, Any]:
        """Admit at most one new scheduled native job; never return saved=true."""
        current=self.workflow.inspect()
        if current is not None and current.phase in {
            "requested","accepted","transfer_verified",
        }:
            return {
                "created":False,"reason":"native_job_pending",
                "request_id":current.request_id,
            }
        if current is not None and current.phase=="committed" and current.kind=="scheduled":
            # Do not start a new snapshot while destination publication or
            # post-commit retention for the old job is unresolved.
            self.finalize_committed()
        policy=self.policy_store.load()
        if not force and not policy.enabled:
            return {"created":False,"reason":"schedule_disabled"}
        if not force and current is not None and current.phase=="failed":
            # Five-second progress polling must not create an endless stream
            # of costly snapshots after one authoritative failure. Keep the
            # failed job visible for diagnosis until the configured interval
            # has elapsed, unless an administrator explicitly forces retry.
            checked=now or datetime.now(timezone.utc)
            failed_at=datetime.fromisoformat(current.created_at)
            if checked.tzinfo is None or failed_at.tzinfo is None:
                raise BackupPolicyError("scheduled retry clock is invalid")
            if checked < failed_at+timedelta(hours=policy.interval_hours):
                return {"created":False,"reason":"failed_retry_backoff"}
        if not force and not self.is_due(now=now):
            return {"created":False,"reason":"not_due"}
        item=self.workflow.request(kind="scheduled",include_previous=True)
        return {
            "created":False,"accepted":True,
            "request_id":item.request_id,"phase":item.phase,
            "reason":"native_job_accepted",
        }
