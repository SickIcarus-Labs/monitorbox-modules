"""Unsigned candidate native Full ZIP backup orchestrator (manual and scheduled intent).

Versioned source for an unsigned, unpromoted build-7 candidate.
Its only purpose is to prove cross-Core-restart transaction composition:
journal intent -> Supervisor job -> verified transfer -> independently
signed ZIP vault commit -> terminal journal record.

Caller invokes these blocking methods using asyncio.to_thread in a future
module API. A pending response is NEVER a saved-backup success. Supervisor
may kill Core during snapshot; the next Core resumes from the durable journal.
"""
from __future__ import annotations

import fcntl
import functools
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from monitorbox_backup_restore_b7_native_jobs import NativeBackupJob, NativeBackupJobStore, NativeBackupJobError
from monitorbox_backup_restore_b7_native_vault import NativeBackupVault, BackupVaultError, open_native_backup_vault


class NativeBackupWorkflowError(RuntimeError):
    """Credential-free native backup operation failed or is not yet ready."""


def _serialized_native_job(operation):
    """One snapshot/transfer step across concurrent and restarted Core processes.

    The original module-owned journal uses a short lock for each atomic state
    transition; it cannot protect the *entire* multi-minute transfer interval.
    This independent process-wide nonblocking flock serializes starts and
    transfers without holding the journal's metadata lock during I/O. Crash
    releases flock via the kernel; new Core can then resume the durable job.
    """
    @functools.wraps(operation)
    def wrapped(self, *args, **kwargs):
        lock_path = self.vault.path / ".native-fullzip-operation.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise NativeBackupWorkflowError("native backup lock unavailable") from exc
        try:
            mode = os.fstat(fd).st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                raise NativeBackupWorkflowError("native backup lock file is unsafe")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise NativeBackupWorkflowError(
                    "native backup operation is already active"
                ) from exc
            return operation(self, *args, **kwargs)
        finally:
            os.close(fd)
    return wrapped


class NativeBackupWorkflow:
    def __init__(self, platform: object) -> None:
        self.vault: NativeBackupVault = open_native_backup_vault(platform)
        self.jobs = NativeBackupJobStore(Path(getattr(platform, "root")))
        self.native = getattr(platform, "native_full_archive")
        for method in (
            "generation_id", "begin_backup", "backup_status",
            "fetch_backup", "release_backup",
        ):
            if getattr(self.native, method, None) is None:
                raise NativeBackupWorkflowError("native backup job capability unavailable")
        self.transfer_root = self.vault.path / ".native-transfers"
        if not self.transfer_root.exists():
            self.transfer_root.mkdir(mode=0o700)
        if (
            self.transfer_root.resolve(strict=True) != self.transfer_root
            or not stat.S_ISDIR(self.transfer_root.lstat().st_mode)
            or self.transfer_root.lstat().st_mode & 0o077
        ):
            raise NativeBackupWorkflowError("native transfer staging is unsafe")

    @_serialized_native_job
    def request(self, *, kind: str = "manual", include_previous: bool = False) -> NativeBackupJob:
        """Durably reserve first, then begin/reclaim one exact Supervisor job."""
        try:
            generation = self.native.generation_id
            reservation = self.jobs.reserve(
                request_id=secrets.token_hex(16), generation=generation,
                kind=kind, include_previous=include_previous,
            )
            # Always report admitted / pending on initial request, never a
            # terminal saved backup even if a tiny ZIP is already ready.
            # Snapshot quiescence can restart Core during this one RPC.
            try:
                job_id = self.native.begin_backup(
                    include_previous=reservation.include_previous
                )
            except Exception as exc:
                # A job may have started before Core died; keep the durable
                # pre-begin request so restart can reattach. No ZIP is saved.
                raise NativeBackupWorkflowError(
                    "native backup begin is unresolved; retry after Core restart"
                ) from exc
            return self.jobs.accept(
                request_id=reservation.request_id, job_id=job_id
            )
        except (NativeBackupJobError, NativeBackupWorkflowError):
            raise
        except Exception as exc:
            raise NativeBackupWorkflowError("native backup start is pending recovery") from exc

    def inspect(self) -> NativeBackupJob | None:
        return self.jobs.inspect()

    def _committed_if_present(self, item: NativeBackupJob) -> NativeBackupJob | None:
        """Crash after vault publication but before journal commit."""
        if item.phase != "transfer_verified":
            return None
        try:
            return self.jobs.commit(
                request_id=item.request_id, backup_id=item.planned_backup_id,
                vault=self.vault,
            )
        except NativeBackupJobError:
            return None

    @_serialized_native_job
    def advance(self) -> NativeBackupJob:
        """One bounded synchronous progress iteration; never invent success."""
        item = self.jobs.inspect()
        if item is None:
            raise NativeBackupWorkflowError("no native backup has been requested")
        if item.phase in {"committed", "failed"}:
            return item
        if self.native.generation_id != item.generation:
            raise NativeBackupWorkflowError("native backup generation changed; recovery required")

        recovered = self._committed_if_present(item)
        if recovered is not None:
            return recovered

        if item.phase == "requested":
            try:
                job_id = self.native.begin_backup(
                    include_previous=item.include_previous
                )
                item = self.jobs.accept(request_id=item.request_id, job_id=job_id)
            except Exception as exc:
                # The Supervisor may have started the job and killed Core
                # before receipt was durably journaled. Retain requested.
                raise NativeBackupWorkflowError(
                    "native backup begin is unresolved; retry after Core restart"
                ) from exc

        if item.job_id is None:
            raise NativeBackupWorkflowError("native archive job not bound")
        try:
            status = self.native.backup_status(item.job_id)
        except Exception as exc:
            raise NativeBackupWorkflowError("native archive status temporarily unavailable") from exc
        if not isinstance(status, dict) or status.get("job_id") != item.job_id:
            raise NativeBackupWorkflowError("native archive job status does not match request")
        phase = status.get("phase")
        if phase == "preparing":
            return item
        if phase == "failed":
            return self.jobs.fail(request_id=item.request_id, failure_code="archive_failed")
        if phase != "ready":
            raise NativeBackupWorkflowError("native archive job not in a publishable state")

        source = self.transfer_root / (item.request_id + ".zip")
        if source.is_symlink():
            raise NativeBackupWorkflowError("native transfer staging contains unsafe link")
        if source.exists():
            if not source.is_file():
                raise NativeBackupWorkflowError("native transfer staging is unsafe")
            source.unlink()  # Partial output from crashed Core; retransfer from Supervisor
        try:
            transferred = self.native.fetch_backup(item.job_id, source)
            if not isinstance(transferred, dict):
                raise NativeBackupWorkflowError("native transfer receipt is invalid")
            size, digest = transferred.get("size"), transferred.get("sha256")
            if (
                type(size) is not int or not 0 < size <= (64 << 30) + (4 << 20)
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise NativeBackupWorkflowError("native transfer receipt is invalid")
            if (
                type(status.get("size")) is not int or status["size"] != size
                or status.get("sha256") != digest
            ):
                raise NativeBackupWorkflowError("native job metadata does not match transfer")
            item = self.jobs.mark_transfer_verified(
                request_id=item.request_id, bytes_count=size, sha256=digest,
            )
            record = self.vault.create_from_verified_transfer(
                source, transport_bytes=size, transport_sha256=digest,
                kind=item.kind, planned_backup_id=item.planned_backup_id,
            )
            item = self.jobs.commit(
                request_id=item.request_id, backup_id=record.backup_id,
                vault=self.vault,
            )
        except (NativeBackupWorkflowError, NativeBackupJobError, BackupVaultError):
            raise
        except Exception as exc:
            # Preserve accepted/transfer_verified. A commit may have taken
            # place before failure; retry reconciles reserved backup ID first.
            raise NativeBackupWorkflowError("native backup not yet durably committed") from exc
        finally:
            source.unlink(missing_ok=True)
        try:
            self.native.release_backup(item.job_id)
        except Exception:
            # A signed saved vault record is already durable. Release is
            # housekeeping; native Supervisor TTL independently reclaims.
            pass
        return item
